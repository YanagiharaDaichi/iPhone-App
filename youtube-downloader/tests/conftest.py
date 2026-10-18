import copy
import threading
import time
from pathlib import Path

import pytest

import downloader as downloader_module
from downloader import Downloader, Settings

VIDEO_ID = 'AbC-123_xyZ'
VIDEO_URL = f'https://youtu.be/{VIDEO_ID}?si=share'


def make_info(**overrides) -> dict:
    """yt-dlp が YouTube から返す情報 (process=False) を模したもの."""
    info = {
        '_type': 'video',
        'id': VIDEO_ID,
        'title': 'テスト動画: "サンプル" / 1080p',
        'uploader': 'テストチャンネル',
        'duration': 100,
        'live_status': 'not_live',
        'formats': [
            {'format_id': 'sb0', 'ext': 'mhtml', 'vcodec': 'none', 'acodec': 'none',
             'width': 160, 'height': 90, 'format_note': 'storyboard'},
            {'format_id': '18', 'ext': 'mp4', 'vcodec': 'avc1.42001E', 'acodec': 'mp4a.40.2',
             'width': 640, 'height': 360, 'format_note': '360p', 'filesize': 5_000_000},
            {'format_id': '134', 'ext': 'mp4', 'vcodec': 'avc1.4d401e', 'acodec': 'none',
             'width': 640, 'height': 360, 'format_note': '360p', 'filesize': 3_000_000},
            {'format_id': '136', 'ext': 'mp4', 'vcodec': 'avc1.4d401f', 'acodec': 'none',
             'width': 1280, 'height': 720, 'format_note': '720p', 'filesize': 10_000_000},
            {'format_id': '137', 'ext': 'mp4', 'vcodec': 'avc1.640028', 'acodec': 'none',
             'width': 1920, 'height': 1080, 'fps': 30, 'format_note': '1080p', 'filesize': 20_000_000},
            {'format_id': '299', 'ext': 'mp4', 'vcodec': 'avc1.64002a', 'acodec': 'none',
             'width': 1920, 'height': 1080, 'fps': 60, 'format_note': '1080p60', 'filesize': 30_000_000},
            {'format_id': '248', 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none',
             'width': 1920, 'height': 1080, 'format_note': '1080p', 'filesize': 15_000_000},
            {'format_id': '271', 'ext': 'webm', 'vcodec': 'vp9', 'acodec': 'none',
             'width': 2560, 'height': 1440, 'format_note': '1440p', 'filesize': 40_000_000},
            {'format_id': '140', 'ext': 'm4a', 'vcodec': 'none', 'acodec': 'mp4a.40.2',
             'abr': 129.5, 'format_note': 'medium', 'filesize': 1_000_000},
            {'format_id': '251', 'ext': 'webm', 'vcodec': 'none', 'acodec': 'opus',
             'abr': 135, 'format_note': 'medium', 'filesize': 1_100_000},
        ],
    }
    info.update(overrides)
    return info


class FakeYoutubeDL:
    """yt_dlp.YoutubeDL の代わり。ネットワークに接続せずにダウンロードを模倣する."""

    info: dict = {}
    error: Exception | None = None
    gate: threading.Event | None = None  # 指定するとダウンロード途中で待つ
    calls: list = []

    def __init__(self, params=None):
        self.params = params or {}
        self._pps = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def add_post_processor(self, pp, when='post_process'):
        self._pps.append(pp)

    def extract_info(self, url, download=True, process=True):
        self.calls.append(('extract_info', url, download))
        if self.error:
            raise self.error
        info = copy.deepcopy(self.info)
        return self._download(info) if download else info

    def process_ie_result(self, ie_result, download=True, extra_info=None):
        self.calls.append(('process_ie_result', ie_result.get('id'), download))
        if self.error:
            raise self.error
        return self._download(ie_result)

    def _download(self, info):
        match_filter = self.params.get('match_filter')
        if match_filter:
            match_filter(info, incomplete=False)
        streams = [('137', 2000), ('140', 1000)]
        # 本物の yt-dlp と同じく、渡された dict をその場で書き換える
        info['requested_formats'] = [{'format_id': fid, 'filesize': size} for fid, size in streams]
        for pp in self._pps:
            pp.run(info)

        hooks = self.params.get('progress_hooks', [])
        for fid, size in streams:
            for done in (0, size // 2):
                for hook in hooks:
                    hook({'status': 'downloading', 'downloaded_bytes': done, 'total_bytes': size,
                          'speed': 1000.0, 'eta': 1, 'info_dict': {'format_id': fid}})
                if self.gate is not None:
                    self.gate.wait(timeout=5)
            for hook in hooks:
                hook({'status': 'finished', 'downloaded_bytes': size, 'total_bytes': size,
                      'info_dict': {'format_id': fid}})

        for hook in self.params.get('postprocessor_hooks', []):
            hook({'status': 'started', 'postprocessor': 'Merger'})
        output = self.params['outtmpl']['default'].replace('%(ext)s', 'mp4')
        Path(output).write_bytes(b'fake video data')
        info['requested_downloads'] = [{'filepath': output}]
        return info


@pytest.fixture
def fake_ydl(monkeypatch):
    class YDL(FakeYoutubeDL):
        info = make_info()
        error = None
        gate = None
        calls = []

    monkeypatch.setattr(downloader_module, 'YoutubeDL', YDL)
    return YDL


@pytest.fixture
def settings(tmp_path):
    return Settings(download_dir=tmp_path / 'downloads', ffmpeg_path='ffmpeg')


@pytest.fixture
def downloader(settings, fake_ydl):
    dl = Downloader(settings, start_janitor=False)
    yield dl
    dl._executor.shutdown(wait=True)


def wait_for(job, statuses=('finished', 'error', 'canceled'), timeout=5.0):
    deadline = time.monotonic() + timeout
    while job.status not in statuses:
        if time.monotonic() > deadline:
            raise AssertionError(f'job stuck in {job.status!r}')
        time.sleep(0.01)
    return job
