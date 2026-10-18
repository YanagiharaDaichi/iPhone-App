"""iphone/ytdl.py (a-Shell 用スクリプト) のテスト."""

import importlib.metadata
import importlib.util
import io
import json
import os
import time
from pathlib import Path

import pytest
import yt_dlp

import downloader
from conftest import VIDEO_ID, VIDEO_URL, FakeYoutubeDL, make_info

_SPEC = importlib.util.spec_from_file_location('ytdl_iphone', Path(__file__).parents[1] / 'iphone' / 'ytdl.py')
ytdl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ytdl)


@pytest.fixture
def save_dir(tmp_path, monkeypatch):
    path = tmp_path / 'YouTube'
    monkeypatch.setattr(ytdl, 'SAVE_DIR', path)
    return path


@pytest.fixture
def fake_ydl(monkeypatch):
    class YDL(FakeYoutubeDL):
        info = make_info()
        error = None
        gate = None
        calls = []

    monkeypatch.setattr(yt_dlp, 'YoutubeDL', YDL)
    monkeypatch.setattr(ytdl, 'ffmpeg_available', lambda: True)
    return YDL


# ---------------------------------------------------------------------------
# URL・ファイル名・表示
# ---------------------------------------------------------------------------

URL_CASES = [
    f'https://www.youtube.com/watch?v={VIDEO_ID}',
    f'https://youtu.be/{VIDEO_ID}?si=AbCdEf',
    f'https://m.youtube.com/watch?v={VIDEO_ID}&feature=share',
    f'https://youtube.com/shorts/{VIDEO_ID}?feature=share',
    f'https://www.youtube.com/live/{VIDEO_ID}',
    f'https://music.youtube.com/watch?v={VIDEO_ID}&list=RD123',
    f'youtu.be/{VIDEO_ID}',
    f'見て https://youtu.be/{VIDEO_ID} ',
    VIDEO_ID,
    '',
    'https://example.com/watch?v=AbC-123_xyZ',
    'https://www.youtube.com/playlist?list=PL123',
    'https://www.youtube.com/@someone',
    'https://youtu.be/short',
]


@pytest.mark.parametrize('text', URL_CASES)
def test_url_parsing_matches_pc_version(text):
    """iPhone 版は単体で動く必要があるため URL の解析を複製している。PC 版と結果が同じであること."""
    try:
        expected = downloader.extract_video_id(text)
    except downloader.InvalidURLError as e:
        with pytest.raises(ytdl.UserError) as raised:
            ytdl.extract_video_id(text)
        assert raised.value.message == e.message.replace('貼り付けて', '使って')
    else:
        assert ytdl.extract_video_id(text) == expected


def test_url_encoded_input_from_shortcuts():
    assert ytdl.extract_video_id('https%3A%2F%2Fyoutu.be%2FAbC-123_xyZ%3Fsi%3Dx') == VIDEO_ID


def test_safe_filename_avoids_shell_special_characters():
    assert ytdl.safe_filename('A "quoted" $HOME `cmd` a/b', 'mp4') == 'A _quoted_ _HOME _cmd_ a_b.mp4'
    assert ytdl.safe_filename(' \n ', 'm4a') == 'video.m4a'
    long_name = ytdl.safe_filename('あ' * 100, 'mp4')
    assert len(long_name.encode('utf-8')) <= 150 + len('.mp4')


def test_unique_path(tmp_path):
    (tmp_path / 'a.mp4').write_bytes(b'')
    (tmp_path / 'a (2).mp4').write_bytes(b'')
    assert ytdl.unique_path(tmp_path / 'a.mp4') == tmp_path / 'a (3).mp4'
    assert ytdl.unique_path(tmp_path / 'b.mp4') == tmp_path / 'b.mp4'


def test_format_helpers():
    assert ytdl.format_bytes(512) == '512B'
    assert ytdl.format_bytes(2048) == '2KB'
    assert ytdl.format_bytes(5 * 1024 * 1024) == '5.0MB'
    assert ytdl.format_bytes(None) == '?'
    assert ytdl.format_eta(42) == '42秒'
    assert ytdl.format_eta(125) == '2分05秒'
    assert ytdl.format_eta(3720) == '1時間02分'


def test_progress_line():
    out = io.StringIO()
    progress = ytdl.Progress(out)
    progress.on_download({'status': 'downloading', 'downloaded_bytes': 512 * 1024, 'total_bytes': 1024 * 1024,
                          'speed': 256 * 1024, 'eta': 2, 'info_dict': {'vcodec': 'avc1', 'acodec': 'none'}})
    progress.on_download({'status': 'finished', 'downloaded_bytes': 1024 * 1024, 'total_bytes': 1024 * 1024,
                          'info_dict': {'vcodec': 'none', 'acodec': 'mp4a'}})
    progress.on_postprocess({'status': 'started', 'postprocessor': 'Merger'})
    progress.on_postprocess({'status': 'started', 'postprocessor': 'Merger'})  # yt-dlp は 2 回呼ぶことがある
    progress.on_postprocess({'status': 'finished', 'postprocessor': 'Merger'})
    assert out.getvalue() == (
        '\r映像  50% 512KB/1.0MB 256KB/秒 残り2秒\x1b[K'
        '\r音声 100% 1.0MB\x1b[K\n'
        '映像と音声をまとめています…\n'
    )


# ---------------------------------------------------------------------------
# 形式の選び方 (本物の yt-dlp で確認)
# ---------------------------------------------------------------------------

def _fmt(fid, ext, vcodec, acodec, w=None, h=None, fps=None, tbr=None):
    return {'format_id': fid, 'ext': ext, 'vcodec': vcodec, 'acodec': acodec, 'width': w, 'height': h,
            'fps': fps, 'tbr': tbr, 'url': f'https://example.invalid/{fid}', 'protocol': 'https'}


AUDIO = [_fmt('140', 'm4a', 'none', 'mp4a.40.2', tbr=129), _fmt('251', 'webm', 'none', 'opus', tbr=140)]
MUXED_360 = _fmt('18', 'mp4', 'avc1.42001E', 'mp4a.40.2', 640, 360, 30, 500)


def _select(formats, mode, *, has_ffmpeg=True, max_height=1080):
    options = {'quiet': True, 'simulate': True, **ytdl.build_options(mode, max_height, has_ffmpeg)}
    options.pop('postprocessors', None)
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.process_ie_result({
            'id': 'x', 'title': 't', 'formats': [dict(f) for f in formats],
            'extractor': 'test', 'extractor_key': 'Test', 'webpage_url': 'https://example.invalid',
        }, download=False)
    return info['format_id']


@pytest.mark.parametrize('formats, max_height, expected', [
    # 1080p までは H.264、4K は VP9/AV1 しかない一般的な動画 → 1080p の H.264
    ([_fmt('137', 'mp4', 'avc1.640028', 'none', 1920, 1080, 30, 4000),
      _fmt('136', 'mp4', 'avc1.4d401f', 'none', 1280, 720, 30, 2000),
      _fmt('313', 'webm', 'vp9', 'none', 3840, 2160, 30, 18000),
      _fmt('401', 'mp4', 'av01.0.12M.08', 'none', 3840, 2160, 30, 15000), MUXED_360, *AUDIO], 1080, '137+140'),
    # 縦長のショート動画も 1080p のまま
    ([_fmt('137', 'mp4', 'avc1.640028', 'none', 1080, 1920, 30, 4000),
      _fmt('135', 'mp4', 'avc1.4d401f', 'none', 480, 854, 30, 1000), *AUDIO], 1080, '137+140'),
    # 画質の上限を下げた場合
    ([_fmt('137', 'mp4', 'avc1.640028', 'none', 1920, 1080, 30, 4000),
      _fmt('136', 'mp4', 'avc1.4d401f', 'none', 1280, 720, 30, 2000), *AUDIO], 720, '136+140'),
    # 高画質が VP9 しかない場合は、写真アプリで再生できる H.264 を優先する
    ([_fmt('248', 'webm', 'vp9', 'none', 1920, 1080, 30, 2500),
      _fmt('134', 'mp4', 'avc1.4d401e', 'none', 640, 360, 30, 600), *AUDIO], 1080, '134+140'),
])
def test_video_format_selection(formats, max_height, expected):
    assert _select(formats, 'video', max_height=max_height) == expected


def test_video_without_ffmpeg_uses_muxed_format():
    formats = [_fmt('137', 'mp4', 'avc1.640028', 'none', 1920, 1080, 30, 4000), MUXED_360, *AUDIO]
    assert _select(formats, 'video', has_ffmpeg=False) == '18'


def test_audio_format_selection():
    assert _select([MUXED_360, *AUDIO], 'audio') == '140'
    assert _select([MUXED_360, *AUDIO], 'audio', has_ffmpeg=False) == '140'


def test_mp3_requires_ffmpeg():
    with pytest.raises(ytdl.UserError, match='ffmpeg'):
        ytdl.build_options('mp3', has_ffmpeg=False)
    postprocessors = ytdl.build_options('mp3')['postprocessors']
    assert postprocessors[0] == {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}


# ---------------------------------------------------------------------------
# ダウンロード
# ---------------------------------------------------------------------------

def test_download_saves_file_with_title(save_dir, fake_ydl, capsys):
    path = ytdl.download('video', VIDEO_URL)
    assert path == save_dir / 'テスト動画_ _サンプル_ _ 1080p.mp4'
    assert path.read_bytes() == b'fake video data'
    assert fake_ydl.calls == [('extract_info', f'https://www.youtube.com/watch?v={VIDEO_ID}', True)]
    assert [p.name for p in save_dir.iterdir()] == [path.name]  # 作業フォルダは消えている
    output = capsys.readouterr().out
    assert '「テスト動画: "サンプル" / 1080p」' in output
    assert '映像と音声をまとめています…' in output

    second = ytdl.download('video', VIDEO_URL)
    assert second.name == 'テスト動画_ _サンプル_ _ 1080p (2).mp4'


def test_download_reports_friendly_error(save_dir, fake_ydl, capsys):
    fake_ydl.error = yt_dlp.utils.DownloadError('ERROR: [youtube] x: Sign in to confirm you’re not a bot.')
    assert ytdl.main(['video', VIDEO_URL]) == 1
    output = capsys.readouterr().out
    assert 'エラー: YouTube にボットと判定されました。' in output
    assert '(詳細: [youtube] x: Sign in to confirm you’re not a bot.)' in output
    assert list(save_dir.iterdir()) == []


def test_download_rejects_live_video(save_dir, fake_ydl, capsys):
    fake_ydl.info = make_info(live_status='is_live')
    assert ytdl.main(['audio', VIDEO_URL, '--no-preview']) == 1
    assert 'ライブ配信中の動画は保存できません' in capsys.readouterr().out


def test_main_uses_clipboard_when_url_is_omitted(save_dir, fake_ydl, monkeypatch, capsys):
    monkeypatch.setattr(ytdl, 'clipboard_text', lambda: VIDEO_URL)
    assert ytdl.main(['audio']) == 0
    output = capsys.readouterr().out
    assert 'クリップボードの URL を使います' in output
    assert '保存しました: テスト動画_ _サンプル_ _ 1080p.mp4' in output


def test_main_without_url_or_clipboard(save_dir, monkeypatch, capsys):
    monkeypatch.setattr(ytdl, 'clipboard_text', lambda: '')
    assert ytdl.main(['video']) == 1
    assert 'URL がありません' in capsys.readouterr().out


def test_main_with_invalid_url(capsys):
    assert ytdl.main(['video', 'https://example.com/']) == 1
    assert 'エラー: YouTube の動画 URL を入力してください。' in capsys.readouterr().out


def test_remove_stale_workdirs(save_dir):
    save_dir.mkdir()
    old, fresh = save_dir / '.ytdl-old', save_dir / '.ytdl-new'
    old.mkdir()
    fresh.mkdir()
    two_days_ago = time.time() - 2 * 24 * 3600
    os.utime(old, (two_days_ago, two_days_ago))
    ytdl.remove_stale_workdirs()
    assert not old.exists()
    assert fresh.exists()


def test_clean(save_dir, monkeypatch, capsys):
    save_dir.mkdir()
    (save_dir / 'a.mp4').write_bytes(b'x' * 10)
    (save_dir / '.ytdl-work').mkdir()

    monkeypatch.setattr('builtins.input', lambda prompt: 'n')
    assert ytdl.main(['clean']) == 0
    assert (save_dir / 'a.mp4').exists()

    assert ytdl.main(['clean', '--yes']) == 0
    assert list(save_dir.iterdir()) == []
    assert '削除しました' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 準備 (setup)
# ---------------------------------------------------------------------------

def test_ejs_requirement_follows_yt_dlp(monkeypatch):
    payload = {'info': {'requires_dist': [
        'brotli; extra == "default"', 'yt-dlp-ejs==0.9.1; extra == "default"', 'deno>=2.6.6; extra == "deno"']}}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(ytdl.urllib.request, 'urlopen', lambda url, timeout: Response(json.dumps(payload).encode()))
    assert ytdl.ejs_requirement() == 'yt-dlp-ejs==0.9.1'

    def offline(url, timeout):
        raise OSError('offline')

    monkeypatch.setattr(ytdl.urllib.request, 'urlopen', offline)
    assert ytdl.ejs_requirement() == 'yt-dlp-ejs'


@pytest.mark.parametrize('argv, expected', [
    (['setup'], ['yt-dlp', 'yt-dlp-ejs==0.8.0', 'yt-dlp-apple-webkit-jsi']),
    (['update', '--no-webkit'], ['yt-dlp', 'yt-dlp-ejs==0.8.0']),
])
def test_setup_installs_packages(save_dir, monkeypatch, capsys, argv, expected):
    installed = []
    monkeypatch.setattr(ytdl, 'ejs_requirement', lambda: 'yt-dlp-ejs==0.8.0')
    monkeypatch.setattr(ytdl, 'pip_install', lambda packages: installed.append(packages) or 0)
    assert ytdl.main(argv) == 0
    assert installed == [expected]
    assert save_dir.is_dir()
    assert '準備ができました。' in capsys.readouterr().out


def test_setup_reports_pip_failure(save_dir, monkeypatch, capsys):
    monkeypatch.setattr(ytdl, 'ejs_requirement', lambda: 'yt-dlp-ejs')
    monkeypatch.setattr(ytdl, 'pip_install', lambda packages: 1)
    assert ytdl.main(['setup']) == 1
    assert 'インストールに失敗しました' in capsys.readouterr().out


def test_check(save_dir, capsys):
    assert ytdl.main(['check']) == 0
    output = capsys.readouterr().out
    assert f'・yt-dlp: {importlib.metadata.version("yt-dlp")}' in output
    assert f'・保存先: {save_dir}' in output


def test_required_ejs_version_comes_from_installed_yt_dlp():
    assert ytdl.required_ejs_version() == importlib.metadata.version('yt-dlp-ejs')
