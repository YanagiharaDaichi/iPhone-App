"""yt-dlp を使って YouTube 動画の情報取得とダウンロードを行う."""

from __future__ import annotations

import copy
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import DownloadCancelled, DownloadError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# エラー
# ---------------------------------------------------------------------------


class UserFacingError(Exception):
    """利用者にそのまま表示できるメッセージを持つエラー."""

    status = 400

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class InvalidURLError(UserFacingError):
    status = 400


class VideoRejected(UserFacingError):
    """ライブ配信や長すぎる動画など、扱わない動画."""

    status = 422


class FetchFailed(UserFacingError):
    """YouTube からの取得に失敗した."""

    status = 502


class Busy(UserFacingError):
    status = 429


# yt-dlp のエラーメッセージ → 利用者向けメッセージ (上から順に判定)
_ERROR_MESSAGES = [
    (r'confirm you.?re not a bot',
     'YouTube にボットと判定されたため取得できませんでした。時間をおいて再試行するか、'
     '自宅の Wi-Fi など別のネットワークで実行してください。'),
    (r'HTTP Error 429|Too Many Requests',
     'YouTube へのアクセスが一時的に制限されています。しばらく時間をおいて再試行してください。'),
    (r'Private video', 'この動画は非公開です。'),
    (r'members[- ]only|Join this channel', 'メンバー限定の動画はダウンロードできません。'),
    (r'confirm your age|age[- ]restricted|inappropriate for some users',
     '年齢制限のある動画はダウンロードできません。'),
    (r'not (?:made this video )?available in your country|geo[- ]?restrict',
     'この地域では視聴できない動画です。'),
    (r'live event will begin|Premieres in', 'まだ公開されていない動画です。'),
    (r'Requested format is not available', '選択した画質が見つかりませんでした。別の画質を選んでください。'),
    (r'(?:ffmpeg|ffprobe)[^.]*not (?:found|installed)', 'ffmpeg が見つからないため処理できませんでした。'),
    (r'No space left on device', 'サーバーの空き容量が不足しています。'),
    (r'Video unavailable|This video is unavailable|has been removed|does not exist',
     '動画が見つかりませんでした。削除されたか、非公開の可能性があります。'),
    (r'HTTP Error 403',
     'YouTube にダウンロードを拒否されました。yt-dlp を最新版に更新するか、時間をおいて再試行してください。'),
    (r'timed out|Connection|Temporary failure in name resolution|Network is unreachable|Unable to download',
     'ネットワークエラーが発生しました。接続を確認して再試行してください。'),
]


def friendly_error(err: BaseException) -> tuple[str, str]:
    """yt-dlp の例外を (利用者向けメッセージ, 詳細) に変換する."""
    raw = str(err)
    detail = re.sub(r'^ERROR:\s*', '', raw).strip()[:500]
    for pattern, message in _ERROR_MESSAGES:
        if re.search(pattern, raw, re.IGNORECASE):
            return message, detail
    return '動画を取得できませんでした。', detail


# ---------------------------------------------------------------------------
# URL の解析
# ---------------------------------------------------------------------------

_VIDEO_ID_RE = re.compile(r'[0-9A-Za-z_-]{11}')
_YOUTUBE_HOSTS = frozenset({
    'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
    'youtube-nocookie.com', 'www.youtube-nocookie.com',
})
_SHORT_HOSTS = frozenset({'youtu.be', 'www.youtu.be'})
# /shorts/<ID> や /live/<ID> のように、パスの 2 番目が動画 ID になる形式
_ID_PATH_PREFIXES = frozenset({'shorts', 'live', 'embed', 'v', 'e'})
_URL_IN_TEXT_RE = re.compile(r'https?://[^\s<>"\'（）「」『』、。]+')


def extract_video_id(text: str) -> str:
    """貼り付けられた文字列から YouTube の動画 ID を取り出す."""
    text = (text or '').strip()
    if not text:
        raise InvalidURLError('URL を入力してください。')
    if _VIDEO_ID_RE.fullmatch(text):
        return text

    # 共有テキストに URL 以外の文字が混ざっていても URL 部分だけを使う
    match = _URL_IN_TEXT_RE.search(text)
    candidate = match.group(0) if match else text
    if '://' not in candidate:
        candidate = 'https://' + candidate
    try:
        parsed = urlparse(candidate)
    except ValueError:
        raise InvalidURLError('YouTube の動画 URL を入力してください。') from None
    host = (parsed.hostname or '').lower()
    parts = [p for p in parsed.path.split('/') if p]

    if host in _SHORT_HOSTS:
        video_id = parts[0] if parts else ''
    elif host in _YOUTUBE_HOSTS:
        query = parse_qs(parsed.query)
        if parts[:1] == ['watch']:
            video_id = (query.get('v') or [''])[0]
        elif len(parts) >= 2 and parts[0] in _ID_PATH_PREFIXES:
            video_id = parts[1]
        elif 'list' in query:
            raise InvalidURLError('プレイリストには対応していません。動画ごとの URL を貼り付けてください。')
        else:
            video_id = ''
    else:
        raise InvalidURLError('YouTube の動画 URL を入力してください。')

    if not _VIDEO_ID_RE.fullmatch(video_id):
        raise InvalidURLError('動画の URL として認識できませんでした。動画ページの URL を貼り付けてください。')
    return video_id


def canonical_url(video_id: str) -> str:
    return f'https://www.youtube.com/watch?v={video_id}'


# ---------------------------------------------------------------------------
# 画質の選択肢
# ---------------------------------------------------------------------------

_STANDARD_HEIGHTS = (144, 240, 360, 480, 720, 1080, 1440, 2160, 4320)
_QUALITY_LABEL_RE = re.compile(r'\d{3,4}p(?:\d{2,3})?')
_MP3_BITRATE = 192  # kbps


def _has_video(f: dict) -> bool:
    return f.get('vcodec') != 'none' and bool(f.get('height'))


def _has_audio(f: dict) -> bool:
    # yt-dlp と同じ扱い: 'none' は音声なし、None は「不明」(音声ありとみなす)
    return f.get('acodec') != 'none'


def _codec_name(vcodec: str | None) -> str:
    v = (vcodec or '').lower()
    if v.startswith(('avc1', 'h264')):
        return 'H.264'
    if v.startswith(('vp09', 'vp9')):
        return 'VP9'
    if v.startswith('av01'):
        return 'AV1'
    if v.startswith(('hev1', 'hvc1', 'h265')):
        return 'H.265'
    return v.split('.')[0].upper()


def _quality_label(f: dict) -> str:
    """'1080p60' のような YouTube と同じ表記の画質名."""
    match = _QUALITY_LABEL_RE.search(f.get('format_note') or '')
    if match:
        return match.group(0)
    width, height = f.get('width'), f['height']
    # 縦長や横長の動画でも YouTube と同じく「短辺」基準の名前にする
    base = max(min(width, height), round(max(width, height) * 9 / 16)) if width else height
    nearest = min(_STANDARD_HEIGHTS, key=lambda s: abs(s - base))
    fps = f.get('fps')
    return f'{nearest}p' + (str(round(fps)) if fps and fps > 30 else '')


def _estimate_size(f: dict, duration: float | None) -> int | None:
    size = f.get('filesize') or f.get('filesize_approx')
    if not size and f.get('tbr') and duration:
        size = f['tbr'] * 1000 / 8 * duration
    return int(size) if size else None


def build_choices(info: dict, has_ffmpeg: bool) -> list[dict]:
    """画面に出す画質の選択肢を作る (動画は高画質順、その後に音声)."""
    formats = [f for f in info.get('formats') or [] if not f.get('has_drm')]
    duration = info.get('duration')

    audio_only = [f for f in formats if f.get('vcodec') == 'none' and _has_audio(f)]
    best_m4a = max((f for f in audio_only if f.get('ext') == 'm4a'),
                   key=lambda f: f.get('abr') or f.get('tbr') or 0, default=None)
    # 動画と組み合わせる音声 (M4A が無ければ一番良い音声)
    audio_source = best_m4a or max(audio_only, key=lambda f: f.get('abr') or f.get('tbr') or 0, default=None)

    videos = [f for f in formats if _has_video(f)]
    if not has_ffmpeg:
        # ffmpeg が無いと映像と音声を結合できないので、音声付きの形式だけを使う
        videos = [f for f in videos if _has_audio(f)]

    by_height: dict[int, list[dict]] = {}
    for f in videos:
        by_height.setdefault(f['height'], []).append(f)

    choices: list[dict] = []
    seen_labels: set[str] = set()
    for height in sorted(by_height, reverse=True):
        group = by_height[height]
        # build_format_options() の書式と同じ優先順で、実際に選ばれる形式を推定する
        if has_ffmpeg:
            video_only = [f for f in group if f.get('acodec') == 'none']
            pools = ([f for f in video_only if _codec_name(f.get('vcodec')) == 'H.264'], video_only, group)
        else:
            pools = ([f for f in group if f.get('ext') == 'mp4'], group)
        pool = next(p for p in pools if p)
        rep = max(pool, key=lambda f: (f.get('fps') or 0, f.get('tbr') or 0))
        label = _quality_label(rep)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        size = _estimate_size(rep, duration)
        if size and not _has_audio(rep) and audio_source:
            size += _estimate_size(audio_source, duration) or 0
        choices.append({
            'id': f'v{height}',
            'kind': 'video',
            'label': label,
            'note': _codec_name(rep.get('vcodec')),
            'ext': 'mp4' if has_ffmpeg else rep.get('ext') or 'mp4',
            'size': size,
            'recommended': False,
        })

    # 既定は 1080p 以下で最も高画質な H.264
    def short_side(choice: dict) -> int:
        return int(re.match(r'\d+', choice['label']).group(0))

    preferred = (
        [c for c in choices if c['note'] == 'H.264' and short_side(c) <= 1080]
        or [c for c in choices if short_side(c) <= 1080]
        or choices
    )
    if preferred:
        preferred[0]['recommended'] = True

    if best_m4a or (has_ffmpeg and (audio_source or any(_has_audio(f) for f in formats))):
        abr = (best_m4a or {}).get('abr')
        choices.append({
            'id': 'm4a',
            'kind': 'audio',
            'label': 'M4A',
            'note': f'AAC {round(abr)}kbps' if abr else 'AAC',
            'ext': 'm4a',
            'size': _estimate_size(audio_source, duration) if audio_source else None,
            'recommended': True,
        })
    if has_ffmpeg and (audio_source or any(_has_audio(f) for f in formats)):
        choices.append({
            'id': 'mp3',
            'kind': 'audio',
            'label': 'MP3',
            'note': f'{_MP3_BITRATE}kbps',
            'ext': 'mp3',
            'size': int(_MP3_BITRATE * 1000 / 8 * duration) if duration else None,
            'recommended': False,
        })
    return choices


def build_format_options(choice_id: str, has_ffmpeg: bool) -> dict:
    """選択肢の ID を yt-dlp のオプションに変換する (利用者に任意の書式を指定させない)."""
    if choice_id == 'm4a':
        if not has_ffmpeg:
            return {'format': 'ba[ext=m4a]'}
        return {
            'format': 'ba[ext=m4a]/ba/b',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}],
        }
    if choice_id == 'mp3' and has_ffmpeg:
        return {
            'format': 'ba/b',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': str(_MP3_BITRATE),
            }],
        }
    match = re.fullmatch(r'v(\d{2,4})', choice_id or '')
    if not match:
        raise UserFacingError('画質の指定が正しくありません。')
    h = int(match.group(1))
    if not has_ffmpeg:
        return {'format': f'b[height={h}][ext=mp4]/b[height={h}]/b[height<={h}]/b'}
    return {
        # H.264 + AAC を優先 → 同じ高さの別コーデック → それも無ければ近い画質
        'format': (
            f'bv[height={h}][vcodec^=avc1]+ba[ext=m4a]/'
            f'bv[height={h}]+ba[ext=m4a]/'
            f'bv[height={h}]+ba/'
            f'b[height={h}]/'
            f'bv*[height<={h}]+ba/b'
        ),
        'merge_output_format': 'mp4',
        'postprocessors': [{'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}],
    }


# ---------------------------------------------------------------------------
# ファイル名
# ---------------------------------------------------------------------------

_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_WINDOWS_RESERVED = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{i}' for i in range(1, 10)]
    + [f'LPT{i}' for i in range(1, 10)]
)
_MAX_FILENAME_BYTES = 180


def safe_filename(title: str, ext: str) -> str:
    """どの OS でも保存できるファイル名にする."""
    name = re.sub(r'\s+', ' ', title or '')  # 改行やタブも空白にそろえる
    name = _INVALID_FILENAME_CHARS.sub('_', name).strip(' .')
    name = name.encode('utf-8')[:_MAX_FILENAME_BYTES].decode('utf-8', 'ignore').rstrip(' .')
    if not name:
        name = 'video'
    if name.upper() in _WINDOWS_RESERVED:
        name += '_'
    return f'{name}.{ext}'


# ---------------------------------------------------------------------------
# ダウンロードジョブ
# ---------------------------------------------------------------------------

ACTIVE_STATUSES = frozenset({'queued', 'preparing', 'downloading', 'processing'})


class Job:
    """1 件のダウンロード。ワーカースレッドが更新し、API が読み取る."""

    def __init__(self, video_id: str, choice_id: str, title: str = ''):
        self.id = uuid.uuid4().hex
        self.video_id = video_id
        self.choice_id = choice_id
        self.title = title
        self.status = 'queued'
        self.error: str | None = None
        self.detail: str | None = None
        self.file_path: Path | None = None
        self.download_name: str | None = None
        self.finished_at: float | None = None
        self.expires_at: float | None = None
        self.cancel_requested = False
        self._lock = threading.Lock()
        self._expected: dict[str, int | None] = {}  # format_id -> 予想サイズ
        self._streams: dict[str, tuple[int, int | None]] = {}  # format_id -> (取得済み, 合計)
        self._speed: float | None = None
        self._max_progress = 0.0

    def set_expected(self, sizes: dict[str, int | None]) -> None:
        with self._lock:
            self._expected = dict(sizes)

    def update_stream(self, key: str, done: int, total: int | None, speed: float | None) -> None:
        with self._lock:
            self._streams[key] = (done, total)
            self._speed = speed
            if self.status in ('queued', 'preparing'):
                self.status = 'downloading'

    def _progress(self) -> tuple[int, int | None, float | None]:
        with self._lock:
            totals = dict(self._expected)
            # 映像と音声を ffmpeg で同時に落とすと '137+140' のようなキーで届く
            for key in list(totals):
                if key not in self._streams and any(key in k.split('+') for k in self._streams):
                    del totals[key]
            done = 0
            for key, (downloaded, total) in self._streams.items():
                done += downloaded
                if total or key not in totals:
                    totals[key] = total
            total_bytes = sum(v for v in totals.values() if v) or None
            return done, total_bytes, self._speed

    def snapshot(self) -> dict:
        status = self.status  # ワーカースレッドが途中で書き換えても一貫した内容を返す
        done, total, speed = self._progress()
        progress = eta = None
        if status == 'finished':
            progress = 100.0
        elif total and status in ('downloading', 'processing'):
            # 合計サイズの見積もりが途中で変わっても、進捗バーは戻さない
            progress = self._max_progress = max(self._max_progress, min(99.0, done / total * 100))
            if speed and status == 'downloading':
                eta = max(0, round((total - done) / speed))
        return {
            'id': self.id,
            'status': status,
            'title': self.title,
            'progress': progress,
            'downloaded_bytes': done,
            'total_bytes': total,
            'speed': speed if status == 'downloading' else None,
            'eta': eta,
            'error': self.error,
            'detail': self.detail,
            'filename': self.download_name,
            'file_url': f'/api/jobs/{self.id}/file' if status == 'finished' else None,
        }


class _PlanRecorderPP(PostProcessor):
    """ダウンロード直前に、実際に取得するストリームと予想サイズを記録する."""

    def __init__(self, job: Job):
        super().__init__()
        self._job = job

    def run(self, info):
        duration = info.get('duration')
        formats = info.get('requested_formats') or [info]
        self._job.set_expected({str(f.get('format_id')): _estimate_size(f, duration) for f in formats})
        if info.get('title'):
            self._job.title = info['title']
        return [], info


class _YtDlpLogger:
    """yt-dlp の出力を logging に流す."""

    _log = logging.getLogger('yt_dlp')

    def debug(self, msg: str) -> None:
        self._log.debug(msg)

    def info(self, msg: str) -> None:
        self._log.debug(msg)

    def warning(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------


def find_ffmpeg() -> str | None:
    """PATH 上の ffmpeg を優先し、無ければ imageio-ffmpeg に同梱のものを使う."""
    path = shutil.which('ffmpeg')
    if path:
        return path
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # 未インストール、または未対応のプラットフォーム
        return None
    if sys.platform.startswith('linux'):
        # Linux 版は静的リンクされており、OS 側の文字コード変換モジュール (gconv) を
        # 読み込むとクラッシュする。子プロセスの ffmpeg に読み込ませないようにする。
        os.environ.setdefault('GCONV_PATH', os.devnull)
    return path


@dataclass
class Settings:
    download_dir: Path
    max_concurrent: int = 2
    file_ttl: int = 30 * 60  # 秒
    max_duration: int = 0  # 秒 (0 は無制限)
    ffmpeg_path: str | None = None

    @classmethod
    def from_env(cls, environ=os.environ) -> Settings:
        def number(name: str, default: int) -> int:
            value = environ.get(name, '').strip()
            if not value:
                return default
            try:
                return max(0, int(value))
            except ValueError:
                raise ValueError(f'環境変数 {name} は整数で指定してください: {value!r}') from None

        download_dir = environ.get('DOWNLOAD_DIR') or os.path.join(tempfile.gettempdir(), 'youtube-downloader')
        return cls(
            download_dir=Path(download_dir),
            max_concurrent=max(1, number('MAX_CONCURRENT_DOWNLOADS', 2)),
            file_ttl=max(1, number('FILE_TTL_MINUTES', 30)) * 60,
            max_duration=number('MAX_DURATION_MINUTES', 0) * 60,
            ffmpeg_path=environ.get('FFMPEG_PATH') or find_ffmpeg(),
        )


# ---------------------------------------------------------------------------
# ダウンローダー本体
# ---------------------------------------------------------------------------


class Downloader:
    INFO_CACHE_TTL = 5 * 60  # 秒。取得した情報をダウンロード時に再利用する
    INFO_CACHE_SIZE = 20
    MAX_ACTIVE_JOBS = 10
    ALLOWED_EXTRACTORS = ['youtube']

    def __init__(self, settings: Settings, *, start_janitor: bool = True):
        self.settings = settings
        self.has_ffmpeg = bool(settings.ffmpeg_path)
        self._jobs: dict[str, Job] = {}
        self._info_cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=settings.max_concurrent, thread_name_prefix='download')
        settings.download_dir.mkdir(parents=True, exist_ok=True)
        self._remove_leftovers()
        if start_janitor:
            threading.Thread(target=self._janitor, name='janitor', daemon=True).start()

    # -- yt-dlp ----------------------------------------------------------

    def _ydl_opts(self, **extra) -> dict:
        opts = {
            'logger': _YtDlpLogger(),
            'quiet': True,
            'noprogress': True,
            'noplaylist': True,
            'allowed_extractors': self.ALLOWED_EXTRACTORS,
            # YouTube の仕組みを解くための JavaScript ランタイム (見つかったものを使う)
            'js_runtimes': {'deno': {}, 'node': {}, 'bun': {}},
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
        }
        if self.settings.ffmpeg_path:
            opts['ffmpeg_location'] = self.settings.ffmpeg_path
        opts.update(extra)
        return opts

    def _check_video(self, info: dict) -> None:
        live_status = info.get('live_status')
        if info.get('is_live') or live_status == 'is_live':
            raise VideoRejected('ライブ配信中の動画はダウンロードできません。配信が終わってからお試しください。')
        if live_status == 'is_upcoming':
            raise VideoRejected('まだ公開されていない動画です。')
        limit = self.settings.max_duration
        duration = info.get('duration')
        if limit and duration and duration > limit:
            raise VideoRejected(f'{limit // 60} 分を超える動画はダウンロードできません。')

    def _match_filter(self, info: dict, *, incomplete: bool = False) -> None:
        self._check_video(info)  # 対象外なら VideoRejected がそのまま伝わる

    # -- 情報取得 --------------------------------------------------------

    def fetch_info(self, text: str) -> dict:
        video_id = extract_video_id(text)
        try:
            with YoutubeDL(self._ydl_opts()) as ydl:
                info = ydl.extract_info(canonical_url(video_id), download=False, process=False)
        except DownloadError as e:
            raise FetchFailed(*friendly_error(e)) from None
        except Exception as e:
            log.exception('動画情報の取得に失敗しました (video=%s)', video_id)
            raise FetchFailed('動画情報の取得中に予期しないエラーが発生しました。', str(e)[:500]) from None
        if not info or info.get('_type', 'video') != 'video':
            raise VideoRejected('この URL は動画として扱えませんでした。')
        self._check_video(info)

        choices = build_choices(info, self.has_ffmpeg)
        if not choices:
            raise FetchFailed('ダウンロードできる形式が見つかりませんでした。')
        # 字幕の一覧はダウンロードに使わないうえ大きいので、キャッシュには残さない
        cached = {k: v for k, v in info.items() if k not in ('subtitles', 'automatic_captions')}
        with self._lock:
            self._info_cache.pop(video_id, None)
            self._info_cache[video_id] = (time.monotonic(), cached)
            while len(self._info_cache) > self.INFO_CACHE_SIZE:
                del self._info_cache[next(iter(self._info_cache))]  # 一番古いものから消す
        return {
            'id': video_id,
            'title': info.get('title') or video_id,
            'uploader': info.get('uploader') or info.get('channel'),
            'duration': info.get('duration'),
            'thumbnail': f'https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg',
            'thumbnail_fallback': f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
            'choices': choices,
        }

    def _cached_info(self, video_id: str) -> dict | None:
        with self._lock:
            entry = self._info_cache.get(video_id)
        if not entry or time.monotonic() - entry[0] > self.INFO_CACHE_TTL:
            return None
        try:
            return copy.deepcopy(entry[1])  # yt-dlp は渡した dict を書き換えるため複製する
        except Exception:
            return None

    def _forget_info(self, video_id: str) -> None:
        with self._lock:
            self._info_cache.pop(video_id, None)

    # -- ジョブ ----------------------------------------------------------

    def start_job(self, text: str, choice_id: str) -> Job:
        video_id = extract_video_id(text)
        build_format_options(choice_id, self.has_ffmpeg)  # 不正な指定はここで弾く
        with self._lock:
            active = sum(1 for j in self._jobs.values() if j.status in ACTIVE_STATUSES)
            if active >= self.MAX_ACTIVE_JOBS:
                raise Busy('現在混み合っています。しばらくしてから再度お試しください。')
            cached = self._info_cache.get(video_id)
            job = Job(video_id, choice_id, title=cached[1].get('title', '') if cached else '')
            self._jobs[job.id] = job
        self._executor.submit(self._run_job, job)
        return job

    def get_job(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> Job | None:
        job = self.get_job(job_id)
        if job and job.status in ACTIVE_STATUSES:
            job.cancel_requested = True
        return job

    def shutdown(self) -> None:
        """実行中のダウンロードを止める (Ctrl+C ですぐに終了できるように)."""
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            if job.status in ACTIVE_STATUSES:
                job.cancel_requested = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    def touch(self, job: Job) -> None:
        """ファイルの取得中に削除されないよう有効期限を延ばす."""
        job.expires_at = max(job.expires_at or 0, time.time() + self.settings.file_ttl)

    def _run_job(self, job: Job) -> None:
        workdir = self.settings.download_dir / job.id
        try:
            if job.cancel_requested:
                raise DownloadCancelled()
            job.status = 'preparing'
            workdir.mkdir(parents=True, exist_ok=True)
            opts = self._ydl_opts(
                outtmpl={'default': str(workdir / 'media.%(ext)s')},
                progress_hooks=[lambda d: self._on_progress(job, d)],
                postprocessor_hooks=[lambda d: self._on_postprocess(job, d)],
                match_filter=self._match_filter,
                **build_format_options(job.choice_id, self.has_ffmpeg),
            )
            cached = self._cached_info(job.video_id)
            with YoutubeDL(opts) as ydl:
                ydl.add_post_processor(_PlanRecorderPP(job), when='before_dl')
                if cached is not None:
                    info = ydl.process_ie_result(cached, download=True)
                else:
                    info = ydl.extract_info(canonical_url(job.video_id), download=True)
            path = _find_output(info, workdir)
            job.title = info.get('title') or job.title or job.video_id
            job.download_name = safe_filename(job.title, path.suffix.lstrip('.') or 'mp4')
            job.file_path = path
            job.status = 'finished'
        except DownloadCancelled:
            job.status = 'canceled'
        except UserFacingError as e:
            job.error, job.detail = e.message, e.detail
            job.status = 'error'
        except DownloadError as e:
            self._forget_info(job.video_id)
            job.error, job.detail = friendly_error(e)
            job.status = 'error'
        except Exception as e:
            log.exception('ダウンロードに失敗しました (job=%s)', job.id)
            self._forget_info(job.video_id)
            job.error, job.detail = 'ダウンロード中に予期しないエラーが発生しました。', str(e)[:500]
            job.status = 'error'
        finally:
            job.finished_at = time.time()
            job.expires_at = job.finished_at + self.settings.file_ttl
            if job.status != 'finished':
                shutil.rmtree(workdir, ignore_errors=True)

    @staticmethod
    def _on_progress(job: Job, d: dict) -> None:
        if job.cancel_requested:
            raise DownloadCancelled()
        key = str((d.get('info_dict') or {}).get('format_id') or d.get('filename') or '')
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        if d.get('status') == 'downloading':
            job.update_stream(key, d.get('downloaded_bytes') or 0, total, d.get('speed'))
        elif d.get('status') == 'finished':
            size = d.get('total_bytes') or d.get('downloaded_bytes') or total or 0
            job.update_stream(key, size, size, None)

    @staticmethod
    def _on_postprocess(job: Job, d: dict) -> None:
        if job.cancel_requested:
            raise DownloadCancelled()
        if d.get('status') == 'started' and job.status == 'downloading':
            job.status = 'processing'

    # -- 後片付け --------------------------------------------------------

    def cleanup(self, now: float | None = None) -> None:
        """期限切れのファイルとキャッシュを削除する."""
        now = time.time() if now is None else now
        with self._lock:
            expired = [j for j in self._jobs.values() if j.expires_at and now > j.expires_at]
            for job in expired:
                del self._jobs[job.id]
            mono = time.monotonic()
            for video_id, (fetched_at, _) in list(self._info_cache.items()):
                if mono - fetched_at > self.INFO_CACHE_TTL:
                    del self._info_cache[video_id]
        for job in expired:
            shutil.rmtree(self.settings.download_dir / job.id, ignore_errors=True)

    def _janitor(self) -> None:
        while True:
            time.sleep(60)
            try:
                self.cleanup()
            except Exception:
                log.exception('後片付けに失敗しました')

    def _remove_leftovers(self) -> None:
        """前回の起動時に残った作業フォルダを消す (ジョブ ID 形式のフォルダのみ)."""
        for child in self.settings.download_dir.iterdir():
            if child.is_dir() and re.fullmatch(r'[0-9a-f]{32}', child.name):
                shutil.rmtree(child, ignore_errors=True)


def _find_output(info: dict, workdir: Path) -> Path:
    for item in info.get('requested_downloads') or []:
        path = item.get('filepath')
        if path and os.path.isfile(path):
            return Path(path)
    files = [p for p in workdir.iterdir()
             if p.is_file() and not p.name.endswith(('.part', '.ytdl', '.temp'))]
    if not files:
        raise RuntimeError('ダウンロードしたファイルが見つかりませんでした。')
    return max(files, key=lambda p: p.stat().st_size)
