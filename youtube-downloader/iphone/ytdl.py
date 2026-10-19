#!/usr/bin/env python3
"""iPhone だけで YouTube の動画・音声を保存する (a-Shell で動かすスクリプト).

a-Shell の Documents フォルダ (起動直後の場所。「cd」で戻れる) で実行する:

    python3 bin/ytdl video [URL]   動画 (MP4) を保存
    python3 bin/ytdl audio [URL]   音声 (M4A) を保存
    python3 bin/ytdl mp3 [URL]     音声 (MP3) を保存
    python3 bin/ytdl setup         初回の準備。yt-dlp の更新にも使う
    python3 bin/ytdl check         動作環境を確認
    python3 bin/ytdl clean         保存したファイルを削除

URL を省略するとクリップボードの URL を使う。
保存先は a-Shell の Documents/YouTube (「ファイル」アプリ → このiPhone内 → a-Shell → YouTube)。
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

IS_IOS = sys.platform == 'ios'  # a-Shell の Python では 'ios' になる
_HOME = Path.home()
CONTAINER = _HOME.parent if _HOME.name == 'Documents' else _HOME
SAVE_DIR = CONTAINER / 'Documents' / 'YouTube'
CACHE_DIR = CONTAINER / 'Library' / 'Caches' / 'yt-dlp'
ALLOWED_EXTRACTORS = ['youtube']
WEBKIT_PLUGIN = 'yt-dlp-apple-webkit-jsi'
MP3_BITRATE = 192
MODE_NAMES = {'video': '動画 (MP4)', 'audio': '音声 (M4A)', 'mp3': '音声 (MP3)'}
# a-Shell では「~」を含むパスが正しく扱われないことがあるため、Documents からの相対パスで案内する
COMMAND = 'python3 bin/ytdl'


class UserError(Exception):
    """利用者にそのまま表示するエラー."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


def say(message: str = '') -> None:
    print(message, flush=True)


# ---------------------------------------------------------------------------
# URL の解析
# ---------------------------------------------------------------------------

_VIDEO_ID_RE = re.compile(r'[0-9A-Za-z_-]{11}')
_YOUTUBE_HOSTS = frozenset({
    'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com',
    'youtube-nocookie.com', 'www.youtube-nocookie.com',
})
_SHORT_HOSTS = frozenset({'youtu.be', 'www.youtu.be'})
_ID_PATH_PREFIXES = frozenset({'shorts', 'live', 'embed', 'v', 'e'})
_URL_IN_TEXT_RE = re.compile(r'https?://[^\s<>"\'（）「」『』、。]+')


def extract_video_id(text: str) -> str:
    """貼り付けられた文字列から YouTube の動画 ID を取り出す."""
    text = (text or '').strip()
    if re.match(r'(?i)https?%3a', text):  # ショートカットで URL エンコードされている場合
        text = unquote(text)
    if not text:
        raise UserError('URL を入力してください。')
    if _VIDEO_ID_RE.fullmatch(text):
        return text

    match = _URL_IN_TEXT_RE.search(text)
    candidate = match.group(0) if match else text
    if '://' not in candidate:
        candidate = 'https://' + candidate
    try:
        parsed = urlparse(candidate)
    except ValueError:
        raise UserError('YouTube の動画 URL を入力してください。') from None
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
            raise UserError('プレイリストには対応していません。動画ごとの URL を使ってください。')
        else:
            video_id = ''
    else:
        raise UserError('YouTube の動画 URL を入力してください。')

    if not _VIDEO_ID_RE.fullmatch(video_id):
        raise UserError('動画の URL として認識できませんでした。動画ページの URL を使ってください。')
    return video_id


def canonical_url(video_id: str) -> str:
    return f'https://www.youtube.com/watch?v={video_id}'


# ---------------------------------------------------------------------------
# エラーメッセージ・ファイル名・表示
# ---------------------------------------------------------------------------

_ERROR_MESSAGES = [
    (r'confirm you.?re not a bot',
     'YouTube にボットと判定されました。時間をおくか、Wi-Fi とモバイル通信を切り替えて再試行してください。'),
    (r'HTTP Error 429|Too Many Requests',
     'YouTube へのアクセスが一時的に制限されています。しばらくしてから再試行してください。'),
    (r'Private video', 'この動画は非公開です。'),
    (r'members[- ]only|Join this channel', 'メンバー限定の動画は保存できません。'),
    (r'confirm your age|age[- ]restricted|inappropriate for some users', '年齢制限のある動画は保存できません。'),
    (r'not (?:made this video )?available in your country|geo[- ]?restrict', 'この地域では視聴できない動画です。'),
    (r'live event will begin|Premieres in', 'まだ公開されていない動画です。'),
    (r'Requested format is not available', '保存できる形式が見つかりませんでした。'),
    (r'No space left on device', 'iPhone の空き容量が足りません。'),
    (r'Video unavailable|This video is unavailable|has been removed|does not exist',
     '動画が見つかりませんでした。削除されたか、非公開の可能性があります。'),
    (r'HTTP Error 403',
     f'YouTube にダウンロードを拒否されました。「{COMMAND} setup」で更新してから再試行してください。'),
    (r'timed out|Connection|Temporary failure in name resolution|Network is unreachable|Unable to download',
     '通信エラーが発生しました。電波の良い場所で再試行してください。'),
]


def friendly_error(err: BaseException) -> tuple[str, str]:
    """yt-dlp の例外を (利用者向けメッセージ, 詳細) に変換する."""
    raw = str(err)
    detail = re.sub(r'^ERROR:\s*', '', raw).strip()[:300]
    for pattern, message in _ERROR_MESSAGES:
        if re.search(pattern, raw, re.IGNORECASE):
            return message, detail
    return '保存できませんでした。', detail


# ファイル名に使えない文字に加えて、a-Shell のコマンドに渡すときに問題になる文字も避ける
_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|$`\x00-\x1f\x7f]')


def safe_filename(title: str, ext: str) -> str:
    name = re.sub(r'\s+', ' ', title or '')
    name = _UNSAFE_FILENAME_CHARS.sub('_', name).strip(' .')
    name = name.encode('utf-8')[:150].decode('utf-8', 'ignore').rstrip(' .')
    return f'{name or "video"}.{ext}'


def unique_path(path: Path) -> Path:
    """同じ名前のファイルがあれば「名前 (2).mp4」のようにずらす."""
    candidate, n = path, 2
    while candidate.exists():
        candidate = path.with_name(f'{path.stem} ({n}){path.suffix}')
        n += 1
    return candidate


def format_bytes(n: float | None) -> str:
    if n is None:
        return '?'
    value = float(n)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if value < 1024 or unit == 'GB':
            break
        value /= 1024
    return f'{value:.1f}{unit}' if unit in ('MB', 'GB') else f'{value:.0f}{unit}'


def format_eta(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f'{seconds}秒'
    if seconds < 3600:
        return f'{seconds // 60}分{seconds % 60:02d}秒'
    return f'{seconds // 3600}時間{seconds % 3600 // 60:02d}分'


class Progress:
    """ダウンロードの進み具合を 1 行で表示する (iPhone の狭い画面でも折り返さない長さ)."""

    def __init__(self, out=None):
        self.out = out or sys.stdout
        self._last = 0.0
        self._started: set[str] = set()

    def _write(self, text: str) -> None:
        self.out.write(text)
        self.out.flush()

    @staticmethod
    def _label(info: dict) -> str:
        if info.get('acodec') == 'none':
            return '映像'
        if info.get('vcodec') == 'none':
            return '音声'
        return 'ダウンロード'

    def on_download(self, d: dict) -> None:
        label = self._label(d.get('info_dict') or {})
        done = d.get('downloaded_bytes') or 0
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        if d.get('status') == 'downloading':
            now = time.monotonic()
            if now - self._last < 0.25:
                return
            self._last = now
            parts = [label]
            if total:
                parts.append(f'{min(100, int(done * 100 / total)):3d}%')
                parts.append(f'{format_bytes(done)}/{format_bytes(total)}')
            else:
                parts.append(format_bytes(done))
            if d.get('speed'):
                parts.append(f'{format_bytes(d["speed"])}/秒')
            if d.get('eta') is not None:
                parts.append('残り' + format_eta(d['eta']))
            self._write('\r' + ' '.join(parts) + '\x1b[K')
        elif d.get('status') == 'finished':
            self._write(f'\r{label} 100% {format_bytes(total or done)}\x1b[K\n')

    def on_postprocess(self, d: dict) -> None:
        name = d.get('postprocessor')
        # yt-dlp はオプションで指定した後処理のフックを 2 回呼ぶので、1 回だけ表示する
        if d.get('status') != 'started' or name in self._started:
            return
        self._started.add(name)
        message = {
            'Merger': '映像と音声をまとめています…',
            'ExtractAudio': '音声を変換しています…',
        }.get(name)
        if message:
            self._write(message + '\n')


class YtDlpLogger:
    """yt-dlp の細かい出力は -v を付けたときだけ表示する."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def debug(self, msg: str) -> None:
        if self.verbose:
            say(msg)

    info = debug

    def warning(self, msg: str) -> None:
        if self.verbose:
            say(f'WARNING: {msg}')

    def error(self, msg: str) -> None:
        if self.verbose:
            say(msg)


# ---------------------------------------------------------------------------
# yt-dlp の設定
# ---------------------------------------------------------------------------

def import_yt_dlp():
    importlib.invalidate_caches()
    try:
        import yt_dlp
    except ImportError:
        raise UserError(f'yt-dlp がまだ入っていません。先に「{COMMAND} setup」を実行してください。') from None
    return yt_dlp


def ffmpeg_available() -> bool:
    """a-Shell には ffmpeg が組み込まれているが、念のため実際に動くか確かめる."""
    try:
        from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
        return bool(FFmpegPostProcessor(None).available)
    except Exception:
        return False


def reject_live(info: dict, *, incomplete: bool = False) -> None:
    if info.get('is_live') or info.get('live_status') == 'is_live':
        raise UserError('ライブ配信中の動画は保存できません。配信が終わってからお試しください。')
    if info.get('live_status') == 'is_upcoming':
        raise UserError('まだ公開されていない動画です。')


def base_options(verbose: bool = False) -> dict:
    options = {
        'quiet': True,
        'noprogress': True,
        'noplaylist': True,
        'logger': YtDlpLogger(verbose),
        'allowed_extractors': ALLOWED_EXTRACTORS,
        'match_filter': reject_live,
        # YouTube の仕組みを解くスクリプトが pip の版と合わないときは、yt-dlp 公式の配布物を使う
        # (yt-dlp 側でハッシュを照合するので、改ざんされたものは使われない)
        'remote_components': ['ejs:github'],
        'socket_timeout': 30,
        'retries': 5,
        'fragment_retries': 5,
    }
    if IS_IOS:
        options['cachedir'] = str(CACHE_DIR)  # iOS ではホーム直下に書き込めない
    return options


def build_options(mode: str, max_height: int = 1080, has_ffmpeg: bool = True) -> dict:
    """保存形式ごとの yt-dlp のオプション."""
    if mode == 'video':
        return {
            # 写真アプリで確実に再生できる H.264 + AAC を最優先し、その中で max_height までの最高画質。
            # res は縦長動画でも短い辺で比べるので、ショート動画も 1080p のまま保存される
            'format': 'bv*+ba/b' if has_ffmpeg else 'b',
            'format_sort': ['vcodec:h264', f'res:{max_height}', 'fps', 'acodec:aac', 'ext:mp4:m4a'],
            'merge_output_format': 'mp4',
        }
    if mode == 'audio':
        if not has_ffmpeg:
            return {'format': 'ba[ext=m4a]/ba', 'format_sort': ['acodec:aac']}
        return {
            'format': 'ba[ext=m4a]/ba/b',
            'format_sort': ['acodec:aac'],
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'},
                {'key': 'FFmpegMetadata'},  # 曲名・アーティスト名を埋め込む
            ],
        }
    if mode == 'mp3':
        if not has_ffmpeg:
            raise UserError(f'MP3 への変換には ffmpeg が必要です。「{COMMAND} audio」で M4A として保存してください。')
        return {
            'format': 'ba/b',
            'postprocessors': [
                {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': str(MP3_BITRATE)},
                {'key': 'FFmpegMetadata'},
            ],
        }
    raise UserError(f'保存形式の指定が正しくありません: {mode}')


def _make_announcer(post_processor_class, mode: str):
    """ダウンロード直前に、動画のタイトルと画質を表示する."""

    class AnnouncePP(post_processor_class):  # yt-dlp は名前の末尾 "PP" を除いて表示名にする
        def run(self, info):
            say(f'「{info.get("title") or info.get("id")}」')
            formats = info.get('requested_formats') or [info]
            video = next((f for f in formats if f.get('vcodec') not in (None, 'none')), None)
            if mode == 'video' and video and video.get('height'):
                short_side = min(v for v in (video.get('width'), video['height']) if v)
                vcodec = str(video.get('vcodec'))
                codec = 'H.264' if vcodec.startswith('avc1') else vcodec.split('.')[0].upper()
                say(f'画質: {short_side}p ({codec})')
            return [], info

    return AnnouncePP()


def find_output(info: dict, workdir: Path) -> Path:
    for item in info.get('requested_downloads') or []:
        path = item.get('filepath')
        if path and (workdir / path).is_file():  # 相対パスなら作業フォルダから、絶対パスならそのまま
            return workdir / path
    files = [p for p in workdir.iterdir() if p.is_file() and not p.name.endswith(('.part', '.ytdl', '.temp'))]
    if not files:
        raise UserError('ダウンロードしたファイルが見つかりませんでした。')
    return max(files, key=lambda p: p.stat().st_size)


# ---------------------------------------------------------------------------
# コマンド
# ---------------------------------------------------------------------------

def download(mode: str, url_text: str, *, max_height: int = 1080, verbose: bool = False) -> Path:
    video_id = extract_video_id(url_text)
    yt_dlp = import_yt_dlp()
    from yt_dlp.postprocessor import PostProcessor
    from yt_dlp.utils import DownloadError

    has_ffmpeg = ffmpeg_available()
    options = build_options(mode, max_height, has_ffmpeg)
    if mode == 'video' and not has_ffmpeg:
        say('※ ffmpeg が使えないため、画質が低め (360p など) になります。')

    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    remove_stale_workdirs()
    workdir = Path(tempfile.mkdtemp(prefix='.ytdl-', dir=SAVE_DIR))
    progress = Progress()
    options.update(base_options(verbose))
    options.update(
        outtmpl={'default': 'media.%(ext)s'},
        progress_hooks=[progress.on_download],
        postprocessor_hooks=[progress.on_postprocess],
    )
    say(f'{MODE_NAMES[mode]}を保存します。動画の情報を取得しています…')
    previous_dir = os.getcwd()
    # a-Shell は長い絶対パスを含むコマンドを正しく扱えないことがある (末尾が切れる) ため、
    # 作業フォルダに移動して ffmpeg には短い相対パスだけを渡す
    os.chdir(workdir)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.add_post_processor(_make_announcer(PostProcessor, mode), when='before_dl')
            info = ydl.extract_info(canonical_url(video_id), download=True)
        source = find_output(info, workdir)
        title = info.get('title') or video_id
        destination = unique_path(SAVE_DIR / safe_filename(title, source.suffix.lstrip('.') or 'mp4'))
        shutil.move(str(source), str(destination))
    except DownloadError as e:
        raise UserError(*friendly_error(e)) from None
    finally:
        os.chdir(previous_dir)
        shutil.rmtree(workdir, ignore_errors=True)
    return destination


def remove_stale_workdirs(max_age: float = 24 * 3600) -> None:
    """途中で止まったダウンロードの作業フォルダ (.ytdl-*) を片付ける.

    iPhone ではダウンロード中に a-Shell が閉じられることがあり、そのままだと容量を使い続ける。
    """
    now = time.time()
    for path in SAVE_DIR.glob('.ytdl-*'):
        try:
            if path.is_dir() and now - path.stat().st_mtime > max_age:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def open_preview(path: Path) -> bool:
    """a-Shell の view コマンドで、共有ボタン付きのプレビューを開く."""
    if not IS_IOS:
        return False
    previous_dir = os.getcwd()
    try:
        os.chdir(path.parent)  # 長い絶対パスを避けて、ファイル名だけを渡す
        return os.system(f'view "{path.name}"') == 0
    finally:
        os.chdir(previous_dir)


def clipboard_text() -> str:
    try:
        return subprocess.run(['pbpaste'], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        pass
    if IS_IOS:
        try:
            with os.popen('pbpaste') as f:
                return f.read().strip()
        except Exception:
            pass
    return ''


def cmd_download(args: argparse.Namespace) -> int:
    url_text = args.url
    if not url_text:
        url_text = clipboard_text()
        if not url_text:
            raise UserError('URL がありません。YouTube で動画の URL をコピーしてから実行してください。')
        say(f'クリップボードの URL を使います: {url_text[:80]}')
    path = download(args.mode, url_text, max_height=args.max, verbose=args.verbose)

    say('')
    say(f'保存しました: {path.name} ({format_bytes(path.stat().st_size)})')
    say('場所: 「ファイル」アプリ → このiPhone内 → a-Shell → YouTube')
    if not args.no_preview and open_preview(path):
        if args.mode == 'video':
            say('プレビューの共有ボタン →「ビデオを保存」で写真アプリに保存できます。')
        else:
            say('プレビューの共有ボタン →「"ファイル"に保存」で好きな場所に保存できます。')
    return 0


def ejs_requirement() -> str:
    """最新の yt-dlp が求める yt-dlp-ejs の版 (YouTube の仕組みを解くスクリプト)."""
    try:
        with urllib.request.urlopen('https://pypi.org/pypi/yt-dlp/json', timeout=20) as response:
            data = json.load(response)
        for requirement in data['info'].get('requires_dist') or []:
            match = re.match(r'yt-dlp-ejs\s*==\s*([\w.]+)', requirement)
            if match:
                return f'yt-dlp-ejs=={match.group(1)}'
    except Exception:
        pass
    return 'yt-dlp-ejs'


def pip_install(packages: list[str]) -> int:
    try:
        from pip._internal.cli.main import main as pip_main
    except ImportError:
        raise UserError('pip が見つかりません。a-Shell を最新版に更新してください。') from None
    return pip_main(['install', '--upgrade', '--disable-pip-version-check', *packages])


def cmd_setup(args: argparse.Namespace) -> int:
    say('yt-dlp などをインストールします (1〜2 分かかることがあります)…')
    packages = ['yt-dlp', ejs_requirement()]
    if not args.no_webkit:
        packages.append(WEBKIT_PLUGIN)
    if pip_install(packages) != 0:
        raise UserError(
            f'インストールに失敗しました。通信状態を確認して、もう一度「{COMMAND} setup」を実行してください。')
    with contextlib.suppress(OSError):
        os.chmod(__file__, 0o755)  # 「ytdl」だけで起動できるようにする
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    say('')
    if cmd_check(args) != 0:
        return 1
    say('')
    say('準備ができました。')
    say('次は README の手順で、共有メニューから使うショートカットを作ります。')
    say(f'試すには、YouTube で動画の URL をコピーしてから「{COMMAND} video」と入力します。')
    return 0


def installed_version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


def required_ejs_version() -> str | None:
    """インストール済みの yt-dlp が求める yt-dlp-ejs の版."""
    try:
        requirements = importlib.metadata.requires('yt-dlp') or []
    except importlib.metadata.PackageNotFoundError:
        return None
    for requirement in requirements:
        match = re.match(r'yt-dlp-ejs\s*==\s*([\w.]+)', requirement)
        if match:
            return match.group(1)
    return None


def ffmpeg_runs() -> bool:
    try:
        return subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def cmd_check(args: argparse.Namespace) -> int:
    # setup の直後 (同じプロセスで pip を動かした後) にも呼ぶため、標準ライブラリだけで確認する。
    # pip はインストール後の import を禁止する方向 (pip 26.3〜) なので、ここでは yt-dlp を import しない
    say('動作環境')
    say(f'・Python: {platform.python_version()}' + (' (a-Shell)' if IS_IOS else ''))
    version = installed_version('yt-dlp')
    if version is None:
        say(f'・yt-dlp: 未インストール →「{COMMAND} setup」を実行してください')
        return 1
    say(f'・yt-dlp: {version}')

    ejs_version, expected_ejs = installed_version('yt-dlp-ejs'), required_ejs_version()
    if ejs_version is None:
        say('・解析スクリプト (yt-dlp-ejs): なし (必要なときに自動で取得します)')
    elif expected_ejs and ejs_version.split('.')[:2] != expected_ejs.split('.')[:2]:
        say(f'・解析スクリプト (yt-dlp-ejs): {ejs_version} '
            f'(yt-dlp が求める版は {expected_ejs}。「{COMMAND} setup」で直ります)')
    else:
        say(f'・解析スクリプト (yt-dlp-ejs): {ejs_version}')

    plugin_version = installed_version(WEBKIT_PLUGIN)
    if plugin_version:
        say(f'・WebKit プラグイン: {plugin_version}')
    else:
        say('・WebKit プラグイン: なし (なくても動きますが、取得できる形式が少なくなります)')

    if ffmpeg_runs():
        say('・ffmpeg: OK')
    else:
        say('・ffmpeg: 見つかりません (高画質の動画と MP3 が使えません。a-Shell を最新版にしてください)')
    say(f'・保存先: {SAVE_DIR}')
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    if not SAVE_DIR.is_dir():
        say('保存したファイルはありません。')
        return 0
    files = [p for p in SAVE_DIR.iterdir() if p.is_file() and not p.name.startswith('.')]
    work_dirs = [p for p in SAVE_DIR.iterdir() if p.is_dir() and p.name.startswith('.ytdl-')]
    if not files and not work_dirs:
        say('保存したファイルはありません。')
        return 0
    total = sum(p.stat().st_size for p in files)
    say(f'{SAVE_DIR} にある {len(files)} 個のファイル ({format_bytes(total)}) を削除します。')
    if not args.yes:
        answer = input('よろしいですか？ (y/N): ').strip().lower()
        if answer not in ('y', 'yes'):
            say('中止しました。')
            return 0
    for path in files:
        path.unlink()
    for path in work_dirs:
        shutil.rmtree(path, ignore_errors=True)
    say('削除しました。')
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description='iPhone だけで YouTube の動画・音声を保存します (a-Shell 用)。',
        epilog='URL を省略するとクリップボードの URL を使います。',
    )
    sub = parser.add_subparsers(dest='command', metavar='コマンド')

    for mode in ('video', 'audio', 'mp3'):
        help_text = f'{MODE_NAMES[mode]}を保存'
        p = sub.add_parser(mode, help=help_text, description=help_text)
        p.add_argument('url', nargs='?', help='YouTube の URL (省略するとクリップボードから)')
        if mode == 'video':
            p.add_argument('--max', type=int, default=1080, metavar='高さ',
                           help='最高画質 (例: 720)。既定は 1080')
        p.add_argument('--no-preview', action='store_true', help='保存後にプレビューを開かない')
        p.add_argument('-v', '--verbose', action='store_true', help='詳しい情報を表示する')
        p.set_defaults(func=cmd_download, mode=mode, max=1080)

    p = sub.add_parser('setup', help='初回の準備・yt-dlp の更新', description='yt-dlp などをインストール・更新します。')
    p.add_argument('--no-webkit', action='store_true', help='WebKit プラグイン (非公式) を入れない')
    p.set_defaults(func=cmd_setup)
    p = sub.add_parser('update', help='setup と同じ (yt-dlp を最新版に更新)')
    p.add_argument('--no-webkit', action='store_true', help='WebKit プラグイン (非公式) を入れない')
    p.set_defaults(func=cmd_setup)
    sub.add_parser('check', help='動作環境を確認').set_defaults(func=cmd_check)
    p = sub.add_parser('clean', help='保存したファイルを削除')
    p.add_argument('-y', '--yes', action='store_true', help='確認せずに削除する')
    p.set_defaults(func=cmd_clean)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, 'func', None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except UserError as e:
        say('')
        say(f'エラー: {e.message}')
        if e.detail:
            say(f'(詳細: {e.detail})')
        return 1
    except KeyboardInterrupt:
        say('\n中止しました。')
        return 130


if __name__ == '__main__':
    sys.exit(main())
