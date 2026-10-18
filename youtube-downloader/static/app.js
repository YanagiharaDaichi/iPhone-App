'use strict';

(() => {
  const $ = (id) => document.getElementById(id);

  const els = {
    form: $('url-form'),
    input: $('url-input'),
    clearBtn: $('clear-btn'),
    pasteBtn: $('paste-btn'),
    fetchBtn: $('fetch-btn'),
    formError: $('form-error'),
    videoCard: $('video-card'),
    thumb: $('thumb'),
    duration: $('duration'),
    title: $('video-title'),
    uploader: $('video-uploader'),
    tabs: $('kind-tabs'),
    choices: $('choices'),
    codecHint: $('codec-hint'),
    downloadBtn: $('download-btn'),
    progressCard: $('progress-card'),
    progress: $('progress'),
    progressBar: $('progress-bar'),
    progressLabel: $('progress-label'),
    progressPercent: $('progress-percent'),
    progressDetail: $('progress-detail'),
    cancelBtn: $('cancel-btn'),
    doneCard: $('done-card'),
    doneFilename: $('done-filename'),
    saveLink: $('save-link'),
    iosHint: $('ios-hint'),
    againBtn: $('again-btn'),
    jobErrorCard: $('job-error-card'),
    jobError: $('job-error'),
    retryBtn: $('retry-btn'),
  };

  const state = {
    info: null, // /api/info の結果
    url: '', // 情報を取得した URL
    kind: 'video', // 'video' | 'audio'
    selected: { video: null, audio: null },
    infoRequest: 0,
    job: null, // 実行中のジョブ ID
    pollTimer: 0,
    pollFailures: 0,
  };

  const STATUS_LABELS = {
    queued: '順番を待っています…',
    preparing: '準備しています…',
    downloading: 'ダウンロードしています…',
    processing: 'ファイルを仕上げています…',
  };

  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.userAgent.includes('Macintosh') && navigator.maxTouchPoints > 1);

  class ApiError extends Error {
    constructor(message, { detail = null, status = 0 } = {}) {
      super(message);
      this.detail = detail;
      this.status = status;
    }
  }

  // ---------- 表示用の整形 ----------

  function formatBytes(bytes) {
    if (bytes == null) return '';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let i = 0;
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024;
      i += 1;
    }
    const digits = i >= 3 ? 2 : i === 2 ? 1 : 0;
    return `${value.toFixed(digits)} ${units[i]}`;
  }

  function formatDuration(seconds) {
    if (!seconds) return '';
    const s = Math.round(seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, '0');
    return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
  }

  function formatEta(seconds) {
    if (seconds == null) return '';
    if (seconds < 60) return `残り ${Math.max(1, seconds)} 秒`;
    const m = Math.round(seconds / 60);
    return m < 60 ? `残り約 ${m} 分` : `残り約 ${Math.floor(m / 60)} 時間 ${m % 60} 分`;
  }

  function looksLikeYouTube(text) {
    return /(?:youtube\.com|youtu\.be|youtube-nocookie\.com)\//i.test(text);
  }

  // ---------- 共通 ----------

  async function api(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        ...options,
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      });
    } catch {
      throw new ApiError('サーバーに接続できませんでした。アプリが起動しているか確認してください。');
    }
    let data = null;
    try {
      data = await response.json();
    } catch {
      // JSON 以外の応答
    }
    if (!response.ok) {
      throw new ApiError(data?.error || `エラーが発生しました (${response.status})`, {
        detail: data?.detail,
        status: response.status,
      });
    }
    return data;
  }

  function showMessage(el, message, detail) {
    el.replaceChildren(document.createTextNode(message));
    if (detail) {
      const small = document.createElement('span');
      small.className = 'detail';
      small.textContent = detail;
      el.append(small);
    }
    el.hidden = false;
  }

  function setLoading(button, loading, text) {
    const label = button.querySelector('.btn-text');
    label.dataset.default ??= label.textContent;
    label.textContent = loading ? text : label.dataset.default;
    button.classList.toggle('loading', loading);
    button.disabled = loading;
  }

  function scrollIntoViewSoon(el, block) {
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    requestAnimationFrame(() => el.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block }));
  }

  function updateClearButton() {
    els.clearBtn.hidden = !els.input.value;
  }

  // ---------- 動画情報の読み込み ----------

  async function loadInfo() {
    const url = els.input.value.trim();
    els.formError.hidden = true;
    if (!url) {
      showMessage(els.formError, 'YouTube の動画 URL を入力してください。');
      els.input.focus();
      return;
    }

    abandonJob();
    els.videoCard.hidden = true;
    els.doneCard.hidden = true;
    els.jobErrorCard.hidden = true;
    els.input.blur();
    const requestId = ++state.infoRequest;
    setLoading(els.fetchBtn, true, '読み込み中…');
    try {
      const info = await api('/api/info', { method: 'POST', body: JSON.stringify({ url }) });
      if (requestId !== state.infoRequest) return;
      state.info = info;
      state.url = url;
      renderInfo(info);
    } catch (err) {
      if (requestId !== state.infoRequest) return;
      showMessage(els.formError, err.message, err.detail);
    } finally {
      if (requestId === state.infoRequest) setLoading(els.fetchBtn, false);
    }
  }

  function setThumbnail(src, fallback) {
    const img = els.thumb;
    img.hidden = false;
    img.onerror = () => {
      if (fallback && img.src !== fallback) img.src = fallback;
      else img.hidden = true;
    };
    img.onload = () => {
      // 高画質のサムネイルが無い動画では 120px の代替画像が返ってくる
      if (img.naturalWidth <= 120 && fallback && img.src !== fallback) img.src = fallback;
    };
    img.src = src;
  }

  function firstChoice(kind) {
    const list = state.info.choices.filter((c) => c.kind === kind);
    return (list.find((c) => c.recommended) || list[0])?.id ?? null;
  }

  function renderInfo(info) {
    setThumbnail(info.thumbnail, info.thumbnail_fallback);
    els.title.textContent = info.title;
    els.uploader.textContent = info.uploader || '';
    els.uploader.hidden = !info.uploader;
    els.duration.textContent = formatDuration(info.duration);
    els.duration.hidden = !info.duration;

    state.selected = { video: firstChoice('video'), audio: firstChoice('audio') };
    els.tabs.hidden = !(state.selected.video && state.selected.audio);
    setKind(state.selected.video ? 'video' : 'audio');
    setControlsDisabled(false);
    els.videoCard.hidden = false;
    scrollIntoViewSoon(els.videoCard, 'start');
  }

  function setKind(kind) {
    state.kind = kind;
    for (const tab of els.tabs.querySelectorAll('[role="tab"]')) {
      tab.setAttribute('aria-selected', String(tab.dataset.kind === kind));
    }
    renderChoices();
  }

  function currentChoice() {
    const id = state.selected[state.kind];
    return state.info?.choices.find((c) => c.id === id) || null;
  }

  function renderChoices() {
    const list = state.info.choices.filter((c) => c.kind === state.kind);
    const nodes = list.map((choice) => {
      const label = document.createElement('label');
      label.className = 'choice';

      const input = document.createElement('input');
      input.type = 'radio';
      input.name = 'choice';
      input.value = choice.id;
      input.checked = choice.id === state.selected[state.kind];
      input.addEventListener('change', () => {
        state.selected[state.kind] = choice.id;
        updateCodecHint();
      });

      const main = document.createElement('span');
      main.className = 'choice-main';
      const name = document.createElement('span');
      name.className = 'choice-label';
      name.textContent = choice.label;
      main.append(name);
      if (choice.note) {
        const note = document.createElement('span');
        note.className = 'choice-note';
        note.textContent = choice.note;
        main.append(note);
      }
      if (choice.recommended && choice.kind === 'video') {
        const badge = document.createElement('span');
        badge.className = 'badge';
        badge.textContent = 'おすすめ';
        main.append(badge);
      }

      const size = document.createElement('span');
      size.className = 'choice-size';
      size.textContent = choice.size ? `約 ${formatBytes(choice.size)}` : '';

      label.append(input, main, size);
      return label;
    });
    els.choices.replaceChildren(...nodes);
    updateCodecHint();
  }

  function updateCodecHint() {
    const choice = currentChoice();
    els.codecHint.hidden = !(choice && choice.kind === 'video' && choice.note && choice.note !== 'H.264');
  }

  function setControlsDisabled(disabled) {
    els.downloadBtn.disabled = disabled;
    for (const el of els.videoCard.querySelectorAll('[role="tab"], input[type="radio"]')) {
      el.disabled = disabled;
    }
  }

  // ---------- ダウンロード ----------

  async function startDownload() {
    const choice = currentChoice();
    if (!choice) return;
    abandonJob();
    els.doneCard.hidden = true;
    els.jobErrorCard.hidden = true;
    setControlsDisabled(true);
    showProgress({ status: 'queued' });
    scrollIntoViewSoon(els.progressCard, 'nearest');
    try {
      const job = await api('/api/jobs', {
        method: 'POST',
        body: JSON.stringify({ url: state.url, choice: choice.id }),
      });
      state.job = job.id;
      state.pollFailures = 0;
      handleJob(job);
    } catch (err) {
      showJobError(err.message, err.detail);
    }
  }

  function stopPolling() {
    clearTimeout(state.pollTimer);
    state.pollTimer = 0;
  }

  function schedulePoll() {
    stopPolling();
    state.pollTimer = setTimeout(poll, 800);
  }

  async function poll() {
    const jobId = state.job;
    if (!jobId) return;
    try {
      const job = await api(`/api/jobs/${jobId}`);
      if (state.job !== jobId) return;
      state.pollFailures = 0;
      handleJob(job);
    } catch (err) {
      if (state.job !== jobId) return;
      state.pollFailures += 1;
      if (err.status === 404 || state.pollFailures >= 5) showJobError(err.message, err.detail);
      else schedulePoll();
    }
  }

  function handleJob(job) {
    switch (job.status) {
      case 'finished':
        showDone(job);
        break;
      case 'error':
        showJobError(job.error || 'ダウンロードに失敗しました。', job.detail);
        break;
      case 'canceled':
        backToChoices();
        break;
      default:
        showProgress(job);
        schedulePoll();
    }
  }

  function showProgress(job) {
    els.progressCard.hidden = false;
    els.progressLabel.textContent = STATUS_LABELS[job.status] || '処理しています…';

    const known = job.status === 'downloading' && typeof job.progress === 'number';
    els.progress.classList.toggle('indeterminate', !known);
    els.progressBar.style.width = known ? `${job.progress.toFixed(1)}%` : '';
    els.progressPercent.textContent = known ? `${Math.floor(job.progress)}%` : '';
    if (known) els.progress.setAttribute('aria-valuenow', String(Math.floor(job.progress)));
    else els.progress.removeAttribute('aria-valuenow');

    const parts = [];
    if (job.status === 'downloading' && job.total_bytes) {
      parts.push(`${formatBytes(job.downloaded_bytes)} / ${formatBytes(job.total_bytes)}`);
    }
    if (job.speed) parts.push(`${formatBytes(job.speed)}/秒`);
    if (job.eta != null) parts.push(formatEta(job.eta));
    if (job.status === 'processing') parts.push('映像と音声の結合や変換をしています');
    els.progressDetail.textContent = parts.join(' ・ ');
  }

  function showDone(job) {
    stopPolling();
    state.job = null;
    els.progressCard.hidden = true;
    els.doneFilename.textContent = job.filename || '';
    els.saveLink.href = job.file_url;
    els.saveLink.setAttribute('download', job.filename || '');

    if (isIOS) {
      const isAudio = /\.(mp3|m4a)$/i.test(job.filename || '');
      let hint;
      if (navigator.standalone) {
        hint = isAudio
          ? 'プレビューが開いたら、共有ボタンから「"ファイル"に保存」を選んでください。'
          : 'プレビューが開いたら、共有ボタンから「ビデオを保存」(写真アプリ) または「"ファイル"に保存」を選んでください。';
      } else {
        hint = isAudio
          ? '保存したファイルは「ファイル」アプリの「ダウンロード」フォルダに入ります。'
          : '保存したファイルは「ファイル」アプリの「ダウンロード」フォルダに入ります。写真アプリに入れるには、ファイルを開いて共有ボタン →「ビデオを保存」をタップしてください。';
      }
      els.iosHint.textContent = hint;
      els.iosHint.hidden = false;
    }

    els.doneCard.hidden = false;
    setControlsDisabled(false);
    scrollIntoViewSoon(els.doneCard, 'nearest');
  }

  function showJobError(message, detail) {
    stopPolling();
    state.job = null;
    els.progressCard.hidden = true;
    showMessage(els.jobError, message, detail);
    els.jobErrorCard.hidden = false;
    setControlsDisabled(false);
    scrollIntoViewSoon(els.jobErrorCard, 'nearest');
  }

  function backToChoices() {
    stopPolling();
    state.job = null;
    els.progressCard.hidden = true;
    setControlsDisabled(false);
  }

  /** 実行中のダウンロードがあれば取り消す (結果は待たない) */
  function abandonJob() {
    const jobId = state.job;
    backToChoices();
    if (jobId) api(`/api/jobs/${jobId}`, { method: 'DELETE' }).catch(() => {});
  }

  function resetAll() {
    abandonJob();
    state.infoRequest += 1;
    setLoading(els.fetchBtn, false);
    state.info = null;
    state.url = '';
    for (const el of [els.videoCard, els.doneCard, els.jobErrorCard, els.formError]) el.hidden = true;
    els.input.value = '';
    updateClearButton();
    window.scrollTo({ top: 0 });
    els.input.focus();
  }

  // ---------- イベント ----------

  els.form.addEventListener('submit', (event) => {
    event.preventDefault();
    loadInfo();
  });

  els.input.addEventListener('input', updateClearButton);

  // URL を貼り付けたらそのまま読み込む
  els.input.addEventListener('paste', () => {
    setTimeout(() => {
      updateClearButton();
      if (looksLikeYouTube(els.input.value)) loadInfo();
    }, 0);
  });

  els.clearBtn.addEventListener('click', () => {
    els.input.value = '';
    updateClearButton();
    els.formError.hidden = true;
    els.input.focus();
  });

  // クリップボードの読み取りは HTTPS (または localhost) でのみ使える
  if (navigator.clipboard && typeof navigator.clipboard.readText === 'function') {
    els.pasteBtn.hidden = false;
    els.pasteBtn.addEventListener('click', async () => {
      try {
        const text = (await navigator.clipboard.readText()).trim();
        if (!text) {
          showMessage(els.formError, 'クリップボードが空です。');
          return;
        }
        els.input.value = text;
        updateClearButton();
        loadInfo();
      } catch {
        showMessage(els.formError, 'クリップボードを読み取れませんでした。入力欄を長押しして「ペースト」してください。');
        els.input.focus();
      }
    });
  }

  els.tabs.addEventListener('click', (event) => {
    const tab = event.target.closest('[role="tab"]');
    if (tab && !tab.disabled && tab.dataset.kind !== state.kind) setKind(tab.dataset.kind);
  });

  els.downloadBtn.addEventListener('click', startDownload);
  els.cancelBtn.addEventListener('click', abandonJob);
  els.retryBtn.addEventListener('click', startDownload);
  els.againBtn.addEventListener('click', resetAll);

  // 共有メニューや iOS のショートカットから ?url=... 付きで開かれた場合
  const params = new URLSearchParams(window.location.search);
  const shared = params.get('url') || params.get('text') || '';
  if (shared) {
    els.input.value = shared;
    updateClearButton();
    window.history.replaceState(null, '', window.location.pathname);
    loadInfo();
  }
})();
