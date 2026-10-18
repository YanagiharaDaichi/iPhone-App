import threading
import time

import pytest
from yt_dlp.utils import DownloadError

from conftest import VIDEO_ID, VIDEO_URL, make_info, wait_for
from downloader import (
    Busy,
    Downloader,
    FetchFailed,
    InvalidURLError,
    Job,
    UserFacingError,
    VideoRejected,
    build_choices,
    build_format_options,
    extract_video_id,
    friendly_error,
    safe_filename,
)


# ---------------------------------------------------------------------------
# URL の解析
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('text', [
    f'https://www.youtube.com/watch?v={VIDEO_ID}',
    f'https://youtu.be/{VIDEO_ID}?si=AbCdEf',
    f'https://m.youtube.com/watch?v={VIDEO_ID}&feature=share',
    f'https://www.youtube.com/watch?app=desktop&v={VIDEO_ID}&list=PL123&index=2',
    f'https://youtube.com/shorts/{VIDEO_ID}?feature=share',
    f'https://www.youtube.com/live/{VIDEO_ID}',
    f'https://www.youtube.com/embed/{VIDEO_ID}',
    f'https://music.youtube.com/watch?v={VIDEO_ID}',
    f'https://www.youtube-nocookie.com/embed/{VIDEO_ID}',
    f'HTTPS://WWW.YOUTUBE.COM/watch?v={VIDEO_ID}',
    f'youtu.be/{VIDEO_ID}',
    f'www.youtube.com/watch?v={VIDEO_ID}',
    f'  https://youtu.be/{VIDEO_ID}  \n',
    f'この動画おすすめ https://youtu.be/{VIDEO_ID} ぜひ見て',
    f'（https://youtu.be/{VIDEO_ID}）',
    VIDEO_ID,
])
def test_extract_video_id_accepts_common_urls(text):
    assert extract_video_id(text) == VIDEO_ID


@pytest.mark.parametrize('text, message', [
    ('', 'URL を入力'),
    ('   ', 'URL を入力'),
    (f'https://example.com/watch?v={VIDEO_ID}', 'YouTube の動画 URL'),
    (f'https://www.youtube.com.evil.example/watch?v={VIDEO_ID}', 'YouTube の動画 URL'),
    (f'https://notyoutube.com/watch?v={VIDEO_ID}', 'YouTube の動画 URL'),
    ('https://www.youtube.com/playlist?list=PL1234567890', 'プレイリスト'),
    ('https://www.youtube.com/@someone', '認識できません'),
    ('https://www.youtube.com/watch?v=short', '認識できません'),
    ('https://youtu.be/', '認識できません'),
    ('javascript:alert(1)', 'YouTube の動画 URL'),
    ('https://[::1', 'YouTube の動画 URL'),
])
def test_extract_video_id_rejects_other_urls(text, message):
    with pytest.raises(InvalidURLError, match=message):
        extract_video_id(text)


# ---------------------------------------------------------------------------
# 画質の選択肢
# ---------------------------------------------------------------------------

def test_build_choices_with_ffmpeg():
    choices = build_choices(make_info(), has_ffmpeg=True)
    summary = [(c['id'], c['label'], c['note'], c['size'], c['recommended']) for c in choices]
    assert summary == [
        ('v1440', '1440p', 'VP9', 41_000_000, False),
        # 1080p は H.264 の 60fps (299) + AAC (140) が選ばれる
        ('v1080', '1080p60', 'H.264', 31_000_000, True),
        ('v720', '720p', 'H.264', 11_000_000, False),
        # 映像のみの 134 + 140 (音声付きの 18 より優先される)
        ('v360', '360p', 'H.264', 4_000_000, False),
        ('m4a', 'M4A', 'AAC 130kbps', 1_000_000, True),
        ('mp3', 'MP3', '192kbps', 2_400_000, False),
    ]
    assert {c['ext'] for c in choices if c['kind'] == 'video'} == {'mp4'}


def test_build_choices_without_ffmpeg_only_offers_muxed_formats():
    choices = build_choices(make_info(), has_ffmpeg=False)
    summary = [(c['id'], c['label'], c['size'], c['recommended']) for c in choices]
    assert summary == [
        ('v360', '360p', 5_000_000, True),
        ('m4a', 'M4A', 1_000_000, True),
    ]


def test_build_choices_labels_vertical_video_by_short_side():
    info = make_info(formats=[
        {'format_id': 'v1', 'ext': 'mp4', 'vcodec': 'avc1.640032', 'acodec': 'none',
         'width': 1080, 'height': 1920, 'fps': 60, 'tbr': 4000},
        {'format_id': 'v2', 'ext': 'mp4', 'vcodec': 'avc1.64001f', 'acodec': 'none',
         'width': 720, 'height': 1280, 'fps': 30, 'tbr': 2000},
        {'format_id': 'a', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2', 'abr': 128, 'tbr': 128},
    ])
    choices = build_choices(info, has_ffmpeg=True)
    assert [(c['id'], c['label']) for c in choices if c['kind'] == 'video'] == [
        ('v1920', '1080p60'),
        ('v1280', '720p'),
    ]
    # filesize が無い場合はビットレートと長さから見積もる: (4000 + 128) kbps * 100 秒
    assert choices[0]['size'] == 4000 * 125 * 100 + 128 * 125 * 100


def test_build_choices_treats_unknown_audio_codec_as_audio():
    # HLS などでは音声のコーデックが不明 (None) のことがある。yt-dlp と同じく音声として扱う
    info = make_info(formats=[
        {'format_id': 'aud', 'ext': 'mp4', 'vcodec': 'none', 'acodec': None, 'tbr': 128},
        {'format_id': '2700', 'ext': 'mp4', 'vcodec': 'avc1.64001f', 'acodec': 'none',
         'width': 1280, 'height': 720, 'tbr': 2700},
    ])
    choices = build_choices(info, has_ffmpeg=True)
    assert [c['id'] for c in choices] == ['v720', 'm4a', 'mp3']
    assert choices[0]['size'] == (2700 + 128) * 125 * 100
    assert choices[1]['note'] == 'AAC'


def test_build_choices_skips_drm_formats():
    info = make_info(formats=[
        {'format_id': 'x', 'ext': 'mp4', 'vcodec': 'avc1', 'acodec': 'mp4a.40.2',
         'width': 640, 'height': 360, 'has_drm': True},
    ])
    assert build_choices(info, has_ffmpeg=True) == []


def test_build_format_options_for_video():
    opts = build_format_options('v1080', has_ffmpeg=True)
    assert opts['format'].startswith('bv[height=1080][vcodec^=avc1]+ba[ext=m4a]/')
    assert opts['format'].endswith('/b')
    assert opts['merge_output_format'] == 'mp4'

    no_ffmpeg = build_format_options('v360', has_ffmpeg=False)
    assert '+' not in no_ffmpeg['format']


def test_build_format_options_for_audio():
    mp3 = build_format_options('mp3', has_ffmpeg=True)
    assert mp3['postprocessors'][0] == {
        'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}
    m4a = build_format_options('m4a', has_ffmpeg=True)
    assert m4a['postprocessors'][0]['preferredcodec'] == 'm4a'
    assert build_format_options('m4a', has_ffmpeg=False) == {'format': 'ba[ext=m4a]'}


@pytest.mark.parametrize('choice, has_ffmpeg', [
    ('', True), ('v', True), ('best', True), ('bv*+ba', True), ('v1080/b', True),
    ('v1080 ', True), ('mp3', False),
])
def test_build_format_options_rejects_unknown_choices(choice, has_ffmpeg):
    with pytest.raises(UserFacingError):
        build_format_options(choice, has_ffmpeg=has_ffmpeg)


# ---------------------------------------------------------------------------
# ファイル名・エラーメッセージ
# ---------------------------------------------------------------------------

def test_safe_filename_replaces_unsafe_characters():
    assert safe_filename('a/b\\c:d*e?f"g<h>i|j', 'mp4') == 'a_b_c_d_e_f_g_h_i_j.mp4'
    assert safe_filename('  タイトル　 \n 2  ', 'mp3') == 'タイトル 2.mp3'
    assert safe_filename('...', 'mp4') == 'video.mp4'
    assert safe_filename('', 'm4a') == 'video.m4a'
    assert safe_filename('con', 'mp4') == 'con_.mp4'


def test_safe_filename_limits_length_in_bytes():
    name = safe_filename('あ' * 200, 'mp4')
    assert name.endswith('.mp4')
    assert len(name.encode('utf-8')) <= 180 + len('.mp4')
    assert name.startswith('あ' * 60)


@pytest.mark.parametrize('raw, expected', [
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies", 'ボット'),
    ('ERROR: [youtube] x: Private video. Sign in if you\'ve been granted access', '非公開'),
    ('ERROR: [youtube] x: Sign in to confirm your age.', '年齢制限'),
    ('ERROR: [youtube] x: Video unavailable', '見つかりませんでした'),
    ('ERROR: unable to download video data: HTTP Error 403: Forbidden', '拒否'),
    ('ERROR: [youtube] x: Something new', '取得できませんでした'),
])
def test_friendly_error(raw, expected):
    message, detail = friendly_error(DownloadError(raw))
    assert expected in message
    assert not detail.startswith('ERROR')


# ---------------------------------------------------------------------------
# 進捗
# ---------------------------------------------------------------------------

def test_job_progress_combines_video_and_audio_streams():
    job = Job(VIDEO_ID, 'v1080')
    job.set_expected({'137': 2000, '140': 1000})
    job.update_stream('137', 1000, 2000, 500.0)
    snap = job.snapshot()
    assert snap['status'] == 'downloading'
    assert snap['progress'] == pytest.approx(1000 / 3000 * 100)
    assert snap['total_bytes'] == 3000
    assert snap['eta'] == 4

    job.update_stream('137', 2000, 2000, None)
    job.update_stream('140', 500, 1000, 250.0)
    assert job.snapshot()['progress'] == pytest.approx(2500 / 3000 * 100)


def test_job_progress_never_goes_backwards():
    job = Job(VIDEO_ID, 'v1080')
    job.update_stream('hls-1', 500, 1000, None)
    assert job.snapshot()['progress'] == pytest.approx(50.0)
    # 分割ダウンロードでは合計サイズの見積もりが途中で増えることがある
    job.update_stream('hls-1', 600, 2000, None)
    assert job.snapshot()['progress'] == pytest.approx(50.0)
    job.update_stream('hls-1', 1800, 2000, None)
    assert job.snapshot()['progress'] == pytest.approx(90.0)


def test_job_progress_with_merged_stream_key():
    job = Job(VIDEO_ID, 'v1080')
    job.set_expected({'137': 2000, '140': 1000})
    job.update_stream('137+140', 1500, 3000, None)
    assert job.snapshot()['progress'] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

def test_fetch_info(downloader, fake_ydl):
    info = downloader.fetch_info(VIDEO_URL)
    assert info['id'] == VIDEO_ID
    assert info['title'] == 'テスト動画: "サンプル" / 1080p'
    assert info['uploader'] == 'テストチャンネル'
    assert info['thumbnail'].startswith('https://i.ytimg.com/vi/AbC-123_xyZ/')
    assert [c['id'] for c in info['choices']] == ['v1440', 'v1080', 'v720', 'v360', 'm4a', 'mp3']
    # 渡すのは常に正規化した URL だけ
    assert fake_ydl.calls == [('extract_info', f'https://www.youtube.com/watch?v={VIDEO_ID}', False)]


def test_fetch_info_reports_friendly_errors(downloader, fake_ydl):
    fake_ydl.error = DownloadError('ERROR: [youtube] x: Private video')
    with pytest.raises(FetchFailed, match='非公開'):
        downloader.fetch_info(VIDEO_URL)


@pytest.mark.parametrize('overrides, message', [
    ({'live_status': 'is_live'}, 'ライブ配信中'),
    ({'is_live': True}, 'ライブ配信中'),
    ({'live_status': 'is_upcoming'}, '公開されていない'),
    ({'_type': 'playlist'}, '動画として扱えません'),
])
def test_fetch_info_rejects_unsupported_videos(downloader, fake_ydl, overrides, message):
    fake_ydl.info = make_info(**overrides)
    with pytest.raises(VideoRejected, match=message):
        downloader.fetch_info(VIDEO_URL)


def test_max_duration(settings, fake_ydl):
    settings.max_duration = 60
    dl = Downloader(settings, start_janitor=False)
    with pytest.raises(VideoRejected, match='1 分を超える'):
        dl.fetch_info(VIDEO_URL)


def test_job_downloads_file(downloader, fake_ydl):
    job = wait_for(downloader.start_job(VIDEO_URL, 'v1080'))
    assert job.status == 'finished', job.error
    snap = job.snapshot()
    assert snap['progress'] == 100.0
    assert snap['filename'] == 'テスト動画_ _サンプル_ _ 1080p.mp4'
    assert snap['file_url'] == f'/api/jobs/{job.id}/file'
    assert job.file_path.read_bytes() == b'fake video data'
    assert fake_ydl.calls == [('extract_info', f'https://www.youtube.com/watch?v={VIDEO_ID}', True)]


def test_job_reuses_info_from_fetch(downloader, fake_ydl):
    downloader.fetch_info(VIDEO_URL)
    job = wait_for(downloader.start_job(VIDEO_URL, 'mp3'))
    assert job.status == 'finished', job.error
    assert [c[0] for c in fake_ydl.calls] == ['extract_info', 'process_ie_result']
    # キャッシュは複製して渡すので、ダウンロードで書き換えられない
    cached = downloader._info_cache[VIDEO_ID][1]
    assert 'requested_downloads' not in cached


def test_job_error_is_reported_and_cleaned_up(downloader, fake_ydl, settings):
    fake_ydl.error = DownloadError('ERROR: [youtube] x: Sign in to confirm your age')
    job = wait_for(downloader.start_job(VIDEO_URL, 'v720'))
    assert job.status == 'error'
    assert '年齢制限' in job.error
    assert not (settings.download_dir / job.id).exists()


def test_job_rejects_live_video(downloader, fake_ydl):
    fake_ydl.info = make_info(live_status='is_live')
    job = wait_for(downloader.start_job(VIDEO_URL, 'v720'))
    assert job.status == 'error'
    assert 'ライブ配信中' in job.error


def test_cancel_job(downloader, fake_ydl, settings):
    fake_ydl.gate = threading.Event()
    job = downloader.start_job(VIDEO_URL, 'v1080')
    wait_for(job, statuses=('downloading',))
    assert downloader.cancel_job(job.id) is job
    fake_ydl.gate.set()
    wait_for(job)
    assert job.status == 'canceled'
    assert not (settings.download_dir / job.id).exists()


def test_shutdown_cancels_running_jobs(downloader, fake_ydl):
    fake_ydl.gate = threading.Event()
    job = downloader.start_job(VIDEO_URL, 'v1080')
    wait_for(job, statuses=('downloading',))
    downloader.shutdown()
    fake_ydl.gate.set()
    assert wait_for(job).status == 'canceled'


def test_info_cache_is_bounded_and_skips_captions(downloader, fake_ydl, monkeypatch):
    monkeypatch.setattr(Downloader, 'INFO_CACHE_SIZE', 2)
    fake_ydl.info = make_info(automatic_captions={'en': [{'ext': 'vtt', 'url': 'https://example.com'}]})
    for video_id in ('aaaaaaaaaaa', 'bbbbbbbbbbb', 'ccccccccccc'):
        downloader.fetch_info(video_id)
    assert list(downloader._info_cache) == ['bbbbbbbbbbb', 'ccccccccccc']
    assert 'automatic_captions' not in downloader._info_cache['ccccccccccc'][1]


def test_too_many_active_jobs(downloader, fake_ydl, monkeypatch):
    monkeypatch.setattr(Downloader, 'MAX_ACTIVE_JOBS', 1)
    fake_ydl.gate = threading.Event()
    first = downloader.start_job(VIDEO_URL, 'v1080')
    with pytest.raises(Busy):
        downloader.start_job(VIDEO_URL, 'v720')
    downloader.cancel_job(first.id)
    fake_ydl.gate.set()
    wait_for(first)


def test_start_job_validates_input(downloader):
    with pytest.raises(InvalidURLError):
        downloader.start_job('https://example.com/', 'v1080')
    with pytest.raises(UserFacingError):
        downloader.start_job(VIDEO_URL, 'bestvideo')


def test_cleanup_removes_expired_jobs(downloader, settings):
    job = wait_for(downloader.start_job(VIDEO_URL, 'v1080'))
    workdir = settings.download_dir / job.id
    assert workdir.exists()

    downloader.cleanup(now=time.time())
    assert downloader.get_job(job.id) is job

    downloader.cleanup(now=time.time() + settings.file_ttl + 1)
    assert downloader.get_job(job.id) is None
    assert not workdir.exists()


def test_leftover_job_folders_are_removed_on_start(settings, fake_ydl):
    settings.download_dir.mkdir(parents=True)
    leftover = settings.download_dir / ('a' * 32)
    leftover.mkdir()
    (leftover / 'media.mp4').write_bytes(b'old')
    unrelated = settings.download_dir / 'keep-me'
    unrelated.mkdir()

    Downloader(settings, start_janitor=False)
    assert not leftover.exists()
    assert unrelated.exists()
