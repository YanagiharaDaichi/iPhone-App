FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 映像と音声の結合・MP3 変換に使う
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py downloader.py ./
COPY static ./static

RUN useradd --create-home --uid 10001 app
USER app

ENV HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000
CMD ["python", "app.py"]
