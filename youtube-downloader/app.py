"""YouTube 動画ダウンローダー (Flask Web アプリ).

起動: python app.py  → ブラウザで http://localhost:8000 を開く
"""

from __future__ import annotations

import hmac
import logging
import os
import socket
from pathlib import Path
from urllib.parse import quote

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

from downloader import Downloader, Settings, UserFacingError

STATIC_DIR = Path(__file__).resolve().parent / 'static'

MIME_TYPES = {
    '.mp4': 'video/mp4',
    '.m4a': 'audio/mp4',
    '.mp3': 'audio/mpeg',
    '.webm': 'video/webm',
}

CONTENT_SECURITY_POLICY = '; '.join([
    "default-src 'self'",
    "img-src 'self' data: https://i.ytimg.com",
    "script-src 'self'",
    "style-src 'self'",
    "connect-src 'self'",
    "manifest-src 'self'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def create_app(downloader: Downloader | None = None, password: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path='/static')
    app.json.ensure_ascii = False
    dl = downloader or Downloader(Settings.from_env())
    password = os.environ.get('APP_PASSWORD', '') if password is None else password
    app.extensions['downloader'] = dl

    @app.before_request
    def require_password():
        if not password:
            return None
        auth = request.authorization
        if auth and auth.password and hmac.compare_digest(auth.password.encode(), password.encode()):
            return None
        return Response('パスワードが必要です。', 401, {
            'WWW-Authenticate': 'Basic realm="Video Downloader", charset="UTF-8"',
            'Content-Type': 'text/plain; charset=utf-8',
        })

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers.setdefault('Content-Security-Policy', CONTENT_SECURITY_POLICY)
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Referrer-Policy', 'no-referrer')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        if request.path.startswith('/api/'):
            response.headers.setdefault('Cache-Control', 'no-store')
        return response

    @app.errorhandler(UserFacingError)
    def handle_user_error(e: UserFacingError):
        return jsonify(error=e.message, detail=e.detail), e.status

    @app.errorhandler(404)
    def handle_not_found(_e):
        return jsonify(error='見つかりませんでした。'), 404

    @app.get('/')
    def index():
        return send_from_directory(STATIC_DIR, 'index.html', max_age=0)

    @app.get('/manifest.webmanifest')
    def manifest():
        return send_from_directory(STATIC_DIR, 'manifest.webmanifest', mimetype='application/manifest+json')

    @app.post('/api/info')
    def api_info():
        data = request.get_json(silent=True) or {}
        return jsonify(dl.fetch_info(str(data.get('url') or '')))

    @app.post('/api/jobs')
    def api_create_job():
        data = request.get_json(silent=True) or {}
        job = dl.start_job(str(data.get('url') or ''), str(data.get('choice') or ''))
        return jsonify(job.snapshot()), 202

    @app.get('/api/jobs/<job_id>')
    def api_job(job_id: str):
        job = dl.get_job(job_id)
        if not job:
            return jsonify(error='ダウンロードが見つかりません。もう一度やり直してください。'), 404
        return jsonify(job.snapshot())

    @app.delete('/api/jobs/<job_id>')
    def api_cancel_job(job_id: str):
        job = dl.cancel_job(job_id)
        if not job:
            return jsonify(error='ダウンロードが見つかりません。'), 404
        return jsonify(job.snapshot())

    @app.get('/api/jobs/<job_id>/file')
    def api_job_file(job_id: str):
        job = dl.get_job(job_id)
        if not job or job.status != 'finished' or not job.file_path or not job.file_path.is_file():
            return jsonify(error='ファイルが見つかりません。保存期限が切れた可能性があります。'), 404
        dl.touch(job)
        response = send_file(
            job.file_path,
            mimetype=MIME_TYPES.get(job.file_path.suffix.lower(), 'application/octet-stream'),
            max_age=0,
        )
        response.headers['Content-Disposition'] = content_disposition(job.download_name)
        return response

    return app


def content_disposition(filename: str) -> str:
    """日本語のファイル名でも正しく保存されるヘッダーを作る (RFC 6266 / RFC 5987)."""
    try:
        filename.encode('ascii')
        fallback = filename.replace('\\', '_').replace('"', '_')
    except UnicodeEncodeError:
        # 古いブラウザ向けの代替名。Werkzeug 任せだと日本語が抜け落ちた不完全な名前になる
        fallback = 'video' + os.path.splitext(filename)[1]
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def _lan_address() -> str | None:
    """同じネットワークの端末からアクセスするための IP アドレス."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 80))  # UDP なので実際には何も送信しない
            return s.getsockname()[0]
    except OSError:
        return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', '8000'))
    app = create_app()
    downloader: Downloader = app.extensions['downloader']

    lines = ['', '動画ダウンローダーを起動しました', f'  このPCで開く : http://localhost:{port}']
    lan = _lan_address() if host in ('0.0.0.0', '::') else None
    if lan:
        lines.append(f'  iPhoneで開く : http://{lan}:{port}  (同じWi-Fiにつないでください)')
    if not downloader.has_ffmpeg:
        lines.append('  [注意] ffmpeg が見つかりません。選べる画質が限られます (README を参照)')
    lines += ['  終了するには Ctrl+C', '']
    print('\n'.join(lines), flush=True)

    from waitress import serve
    try:
        serve(app, host=host, port=port, threads=8)
    finally:
        downloader.shutdown()


if __name__ == '__main__':
    main()
