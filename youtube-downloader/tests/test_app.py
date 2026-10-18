import base64
import time

import pytest

from app import content_disposition, create_app
from conftest import VIDEO_URL


@pytest.fixture
def client(downloader):
    app = create_app(downloader, password='')
    return app.test_client()


def wait_until_done(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        data = client.get(f'/api/jobs/{job_id}').get_json()
        if data['status'] in ('finished', 'error', 'canceled'):
            return data
        assert time.monotonic() < deadline, data
        time.sleep(0.02)


def test_index_page(client):
    res = client.get('/')
    assert res.status_code == 200
    assert '<title>動画ダウンローダー</title>' in res.get_data(as_text=True)
    assert "script-src 'self'" in res.headers['Content-Security-Policy']
    assert res.headers['X-Content-Type-Options'] == 'nosniff'


def test_static_files(client):
    assert client.get('/static/app.js').status_code == 200
    assert client.get('/static/style.css').status_code == 200
    res = client.get('/manifest.webmanifest')
    assert res.status_code == 200
    assert res.mimetype == 'application/manifest+json'
    assert res.get_json()['short_name'] == '動画DL'


def test_info_rejects_invalid_url(client):
    res = client.post('/api/info', json={'url': 'https://example.com/video'})
    assert res.status_code == 400
    assert 'YouTube の動画 URL' in res.get_json()['error']
    # 日本語はエスケープせずに返す
    assert 'YouTube の動画 URL' in res.get_data(as_text=True)


def test_info_without_body(client):
    res = client.post('/api/info')
    assert res.status_code == 400
    assert res.get_json()['error'] == 'URL を入力してください。'


def test_info_returns_choices(client):
    res = client.post('/api/info', json={'url': VIDEO_URL})
    assert res.status_code == 200
    data = res.get_json()
    assert data['title'] == 'テスト動画: "サンプル" / 1080p'
    assert [c['id'] for c in data['choices']] == ['v1440', 'v1080', 'v720', 'v360', 'm4a', 'mp3']
    assert res.headers['Cache-Control'] == 'no-store'


def test_download_flow(client):
    res = client.post('/api/jobs', json={'url': VIDEO_URL, 'choice': 'v1080'})
    assert res.status_code == 202
    job = wait_until_done(client, res.get_json()['id'])
    assert job['status'] == 'finished', job
    assert job['progress'] == 100.0

    file_res = client.get(job['file_url'])
    assert file_res.status_code == 200
    assert file_res.mimetype == 'video/mp4'
    assert file_res.data == b'fake video data'
    # 日本語のファイル名は RFC 5987 形式 (filename*=UTF-8'') で送り、古いブラウザ向けの代替名も付ける
    assert file_res.headers['Content-Disposition'] == (
        'attachment; filename="video.mp4"; '
        "filename*=UTF-8''%E3%83%86%E3%82%B9%E3%83%88%E5%8B%95%E7%94%BB_%20_"
        "%E3%82%B5%E3%83%B3%E3%83%97%E3%83%AB_%20_%201080p.mp4"
    )


def test_content_disposition_for_ascii_names():
    assert content_disposition('My Video (1).mp4') == (
        "attachment; filename=\"My Video (1).mp4\"; filename*=UTF-8''My%20Video%20%281%29.mp4")


def test_create_job_rejects_unknown_choice(client):
    res = client.post('/api/jobs', json={'url': VIDEO_URL, 'choice': 'bv*+ba/b'})
    assert res.status_code == 400
    assert '画質の指定' in res.get_json()['error']


def test_unknown_job(client):
    res = client.get('/api/jobs/0123456789abcdef0123456789abcdef')
    assert res.status_code == 404
    assert client.get('/api/jobs/nope/file').status_code == 404
    assert client.delete('/api/jobs/nope').status_code == 404


def test_file_is_not_served_before_finish(client, downloader, fake_ydl):
    import threading
    fake_ydl.gate = threading.Event()
    job_id = client.post('/api/jobs', json={'url': VIDEO_URL, 'choice': 'v720'}).get_json()['id']
    assert client.get(f'/api/jobs/{job_id}/file').status_code == 404
    res = client.delete(f'/api/jobs/{job_id}')
    assert res.status_code == 200
    fake_ydl.gate.set()
    assert wait_until_done(client, job_id)['status'] == 'canceled'


def test_password_protection(downloader):
    client = create_app(downloader, password='secret').test_client()
    res = client.get('/')
    assert res.status_code == 401
    assert res.headers['WWW-Authenticate'].startswith('Basic')

    wrong = base64.b64encode(b'user:wrong').decode()
    assert client.get('/', headers={'Authorization': f'Basic {wrong}'}).status_code == 401

    token = base64.b64encode(b'anyone:secret').decode()
    assert client.get('/', headers={'Authorization': f'Basic {token}'}).status_code == 200
