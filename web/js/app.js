import { Engine, hasWebGPU, isAbortError, storage } from './engine.js';
import { renderMarkdown, parseReply } from './markdown.js';
import { MODELS, customModel } from './models.js';

const APP_VERSION = '1.0.0';

const $ = (selector) => document.querySelector(selector);
const el = {
  scroller: $('#scroller'),
  messages: $('#messages'),
  empty: $('#empty'),
  banners: $('#banners'),
  input: $('#input'),
  composer: $('#composer'),
  sendButton: $('#sendButton'),
  newChatButton: $('#newChatButton'),
  modelButton: $('#modelButton'),
  modelTitle: $('#modelTitle'),
  modelStatus: $('#modelStatus'),
  settingsButton: $('#settingsButton'),
  modelsSheet: $('#modelsSheet'),
  settingsSheet: $('#settingsSheet'),
  modelList: $('#modelList'),
  gpuStatus: $('#gpuStatus'),
  storageUsage: $('#storageUsage'),
  customForm: $('#customForm'),
  customInput: $('#customInput'),
  customHint: $('#customHint'),
};

// ---------------------------------------------------------------- persistence

const KEYS = {
  settings: 'llm.settings.v1',
  chat: 'llm.chat.v1',
  lastModel: 'llm.lastModel.v1',
  custom: 'llm.customModels.v1',
  pending: 'llm.pending.v1',
  installHint: 'llm.installHintDismissed.v1',
};

const read = (key, fallback) => {
  try {
    const value = localStorage.getItem(key);
    return value == null ? fallback : JSON.parse(value);
  } catch {
    return fallback;
  }
};
const write = (key, value) => {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or unavailable: the app still works for this session.
  }
};

const DEFAULT_SETTINGS = {
  systemPrompt: 'あなたは親切で有能なアシスタントです。ユーザーと同じ言語で、簡潔かつ正確に答えてください。',
  temperature: 0.7,
  maxTokens: 768,
  enableThinking: false,
  contextLevel: 'normal',
  useGPU: true,
};

// ---------------------------------------------------------------- state

const state = {
  settings: { ...DEFAULT_SETTINGS, ...read(KEYS.settings, {}) },
  messages: read(KEYS.chat, []).filter((m) => m && (m.role === 'user' || m.role === 'assistant')),
  customURLs: read(KEYS.custom, []),
  downloaded: new Set(),
  downloadedBytes: 0,
  engine: null,
  /** idle | loading(model, progress: 0...1 | null while loading into memory) | ready(model) | failed(model, message) */
  status: { kind: 'idle' },
  generation: null, // { replyID, controller }
  notice: null, // { title, text, actions }
  error: null,
};

let loadController = null;
// The in-flight load, so a new one never starts while another model is still in memory.
let loading = null;
let wakeLock = null;

const allModels = () => [...MODELS, ...state.customURLs.map(customModel).filter(Boolean)];
const findModel = (id) => allModels().find((m) => m.id === id);
const activeModel = () => (state.status.kind === 'ready' ? state.status.model : null);
const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

function contextSizeFor(model) {
  const sizes = { short: 1024, normal: model.contextSize, long: Math.max(model.contextSize * 2, 4096) };
  return sizes[state.settings.contextLevel] ?? model.contextSize;
}

function saveChat() {
  // Keep the newest messages; localStorage holds a few MB at most.
  write(KEYS.chat, state.messages.slice(-80).map(({ id, role, text, stats, error }) => ({ id, role, text, stats, error })));
}

// Marks work that can get the page killed for using too much memory, so the next launch
// can tell the user what happened instead of silently reloading into the same crash.
const setPending = (pending) => write(KEYS.pending, pending ? { ...pending, at: Date.now() } : null);

// ---------------------------------------------------------------- model lifecycle

async function refreshDownloaded() {
  const files = await storage.downloadedFiles();
  state.downloaded = new Set(files.keys());
  state.downloadedBytes = [...files.values()].reduce((sum, size) => sum + size, 0);
  renderModelList();
  el.storageUsage.textContent = formatBytes(state.downloadedBytes);
}

async function activate(model) {
  if (state.status.model?.id === model.id && (state.status.kind === 'ready' || state.status.kind === 'loading')) return;

  const controller = new AbortController();
  loadController?.abort();
  loadController = controller;
  setStatus({ kind: 'loading', model, progress: state.downloaded.has(model.url) ? null : 0 });

  await stopGenerating();
  await loading?.catch(() => {});
  if (loadController !== controller) return;
  const previous = state.engine;
  state.engine = null;
  await previous?.unload();
  if (loadController !== controller) return;

  loading = load(model, controller);
  await loading.catch(() => {});
}

async function load(model, controller) {
  const downloaded = state.downloaded.has(model.url);
  setStatus({ kind: 'loading', model, progress: downloaded ? null : 0 });
  setPending({ phase: downloaded ? 'load' : 'download', modelID: model.id });
  requestWakeLock();

  try {
    const engine = await Engine.load(model, {
      contextSize: contextSizeFor(model),
      useGPU: state.settings.useGPU,
      signal: controller.signal,
      onProgress(fraction) {
        if (loadController !== controller) return;
        if (fraction >= 1) {
          setPending({ phase: 'load', modelID: model.id });
          setStatus({ kind: 'loading', model, progress: null });
        } else {
          setStatus({ kind: 'loading', model, progress: fraction });
        }
      },
    });
    if (loadController !== controller) {
      await engine.unload();
      return;
    }
    state.engine = engine;
    write(KEYS.lastModel, model.id);
    setPending(null);
    setStatus({ kind: 'ready', model });
    navigator.storage?.persist?.().catch(() => {});
  } catch (error) {
    if (loadController !== controller) return;
    setPending(null);
    if (controller.signal.aborted || isAbortError(error)) {
      setStatus({ kind: 'idle' });
    } else {
      console.error(error);
      setStatus({ kind: 'failed', model, message: describeError(error) });
    }
  } finally {
    if (loadController === controller) loadController = null;
    releaseWakeLock();
    refreshDownloaded();
  }
}

function cancelLoading() {
  loadController?.abort();
  loadController = null;
  setPending(null);
  releaseWakeLock();
  setStatus({ kind: 'idle' });
}

async function reloadModel() {
  const model = state.status.model;
  if (!model) return;
  await stopGenerating();
  const previous = state.engine;
  state.engine = null;
  setStatus({ kind: 'idle' });
  if (previous) await previous.unload();
  activate(model);
}

async function deleteModel(model) {
  if (!confirm(`${model.name} を削除しますか？\n次に使うときは再ダウンロードが必要です。`)) return;
  if (state.status.model?.id === model.id) {
    loadController?.abort();
    loadController = null;
    await stopGenerating();
    await loading?.catch(() => {});
    const engine = state.engine;
    state.engine = null;
    setStatus({ kind: 'idle' });
    write(KEYS.lastModel, null);
    await engine?.unload();
  }
  try {
    await storage.remove(model.url);
  } catch (error) {
    alert(`削除できませんでした: ${describeError(error)}`);
  }
  await refreshDownloaded();
}

async function requestWakeLock() {
  try {
    wakeLock = (await navigator.wakeLock?.request('screen')) ?? null;
  } catch {
    wakeLock = null;
  }
}

function releaseWakeLock() {
  wakeLock?.release().catch(() => {});
  wakeLock = null;
}

// ---------------------------------------------------------------- chat

function buildPrompt(model, contextSize, maxTokens) {
  // Rough token estimate (Japanese is ~1 token per character in these vocabularies).
  const cost = (text) => Math.ceil(text.length * 1.1) + 8;
  const system = state.settings.systemPrompt.trim();
  let budget = contextSize - maxTokens - (system ? cost(system) : 0) - 32;

  const turns = [];
  for (let i = state.messages.length - 1; i >= 0; i--) {
    const message = state.messages[i];
    if (message.streaming) continue;
    const content = message.role === 'assistant' ? parseReply(message.text).answer : message.text;
    if (!content || message.error) continue;
    const needed = cost(content);
    // Always keep the newest message, even if it alone is over budget.
    if (turns.length && needed > budget) break;
    budget -= needed;
    turns.unshift({ role: message.role, content });
  }
  // Templates expect the conversation to start with a user turn.
  while (turns.length && turns[0].role !== 'user') turns.shift();
  return system ? [{ role: 'system', content: system }, ...turns] : turns;
}

async function send(text) {
  const prompt = (text ?? el.input.value).trim();
  const engine = state.engine;
  if (!prompt || state.generation || !engine) return;
  if (text == null) {
    el.input.value = '';
    autoGrow();
  }
  state.error = null;

  const reply = { id: uid(), role: 'assistant', text: '', streaming: true };
  state.messages.push({ id: uid(), role: 'user', text: prompt }, reply);
  const controller = new AbortController();
  let finish;
  state.generation = { replyID: reply.id, controller, finished: new Promise((resolve) => (finish = resolve)) };
  saveChat();
  render();
  scrollToBottom(true);

  const contextSize = contextSizeFor(engine.model);
  const thinking = engine.model.thinking && state.settings.enableThinking;
  const wanted = state.settings.maxTokens + (thinking ? 1024 : 0);
  const maxTokens = Math.min(wanted, Math.max(128, contextSize - 384));
  setPending({ phase: 'generate', modelID: engine.model.id });

  try {
    const stream = engine.chat(buildPrompt(engine.model, contextSize, maxTokens), {
      temperature: state.settings.temperature,
      maxTokens,
      enableThinking: state.settings.enableThinking,
      signal: controller.signal,
    });
    let result;
    while (!(result = await stream.next()).done) {
      reply.text += result.value;
      scheduleMessageUpdate(reply.id);
    }
    const timings = result.value;
    if (timings?.predicted_n) {
      reply.stats = `${timings.predicted_n} トークン・${timings.predicted_per_second.toFixed(1)} トークン/秒`;
    }
  } catch (error) {
    if (!isAbortError(error) && !controller.signal.aborted) {
      console.error(error);
      reply.error = describeError(error);
    }
  } finally {
    setPending(null);
    reply.streaming = false;
    if (!reply.text && !reply.error) {
      state.messages = state.messages.filter((m) => m.id !== reply.id);
    }
    if (state.generation?.replyID === reply.id) state.generation = null;
    saveChat();
    render();
    finish();
  }
}

/** Stops the reply in progress; the returned promise settles once generation has ended. */
function stopGenerating() {
  const generation = state.generation;
  generation?.controller.abort();
  return generation?.finished ?? Promise.resolve();
}

function newChat() {
  stopGenerating();
  state.generation = null;
  state.messages = [];
  state.error = null;
  saveChat();
  render();
  el.input.focus();
}

// ---------------------------------------------------------------- rendering

function setStatus(status) {
  state.status = status;
  render();
  if (el.modelsSheet.open) renderModelList();
}

function render() {
  renderHeader();
  renderBanners();
  renderEmpty();
  renderMessages();
  renderComposer();
}

function renderHeader() {
  const { status } = state;
  el.modelTitle.textContent = status.model?.name ?? 'モデルを選択';
  el.modelStatus.innerHTML =
    status.kind === 'loading' ? '<span class="spinner"></span>' : status.kind === 'failed' ? '⚠️' : '';
  el.newChatButton.disabled = state.messages.length === 0;
}

function renderBanners() {
  const banners = [];
  const { status } = state;

  if (state.notice) {
    banners.push(banner('warning', state.notice.title, state.notice.text, [
      ...(state.notice.actions ?? []),
      { label: '閉じる', run: () => { state.notice = null; render(); } },
    ]));
  }
  if (!hasWebGPU()) {
    banners.push(banner('warning', 'GPU が使えないため CPU で動作します', 'iOS 26 以降にアップデートすると、GPU で数倍速く動きます。'));
  }
  if (status.kind === 'loading' && state.messages.length) {
    banners.push(progressBanner(status));
  }
  if (status.kind === 'failed' && state.messages.length) {
    banners.push(banner('warning', `${status.model.name} を使えませんでした`, status.message, [
      { label: '再試行', run: () => activate(status.model) },
      { label: '別のモデル', run: openModels },
    ]));
  }
  if (shouldShowInstallHint()) {
    banners.push(banner('', 'ホーム画面に追加するとアプリとして使えます',
      'Safari の共有ボタン（□↑）→「ホーム画面に追加」。アイコンから開くと全画面で、オフラインでも使えます。', [
        { label: 'わかった', run: () => { write(KEYS.installHint, true); render(); } },
      ]));
  }
  el.banners.replaceChildren(...banners);
}

function banner(kind, title, text, actions = []) {
  const node = document.createElement('div');
  node.className = `banner ${kind}`;
  const body = document.createElement('div');
  body.className = 'banner-text';
  const strong = document.createElement('strong');
  strong.textContent = title;
  body.append(strong, document.createTextNode(text));
  if (actions.length) {
    const row = document.createElement('div');
    row.className = 'banner-actions';
    for (const action of actions) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = action.label;
      button.addEventListener('click', action.run);
      row.append(button);
    }
    body.append(row);
  }
  node.append(body);
  return node;
}

function progressBanner(status) {
  const node = banner('', progressLabel(status), '', [{ label: 'キャンセル', run: cancelLoading }]);
  if (status.progress != null) {
    const progress = document.createElement('progress');
    progress.value = status.progress;
    node.querySelector('.banner-text strong').after(progress);
  } else {
    const spinner = document.createElement('span');
    spinner.className = 'spinner';
    node.prepend(spinner);
  }
  return node;
}

function progressLabel(status) {
  return status.progress == null
    ? `${status.model.name} を読み込み中…`
    : `${status.model.name} をダウンロード中… ${Math.floor(status.progress * 100)}%`;
}

function shouldShowInstallHint() {
  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.maxTouchPoints > 1 && /Macintosh/.test(navigator.userAgent));
  return isIOS && !isStandalone() && !read(KEYS.installHint, false);
}

const isStandalone = () => navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;

const SUGGESTIONS = [
  '日本の四季の魅力を3行で教えて',
  '取引先へのお礼メールを丁寧に書いて',
  'JavaScript で配列を逆順にする方法は？',
  '冷蔵庫にある卵と玉ねぎで作れる料理は？',
];

function renderEmpty() {
  if (state.messages.length) {
    el.empty.replaceChildren();
    return;
  }
  const { status } = state;
  const parts = [`<img class="logo" src="icons/icon-192.png" alt="">`];

  if (status.kind === 'idle') {
    parts.push(
      '<h1>iPhone の中で動く AI</h1>',
      '<p>モデルを一度ダウンロードすれば、あとは通信なし（機内モードでも）で会話できます。会話の内容が外部に送られることはありません。</p>',
      '<div class="button-row"><button class="primary-button" data-action="models">モデルを選ぶ</button></div>',
    );
  } else if (status.kind === 'loading') {
    parts.push(`<h1>${escapeText(progressLabel(status))}</h1>`);
    parts.push(status.progress == null ? '<div class="spinner large"></div>' : `<progress value="${status.progress}"></progress>`);
    parts.push(
      `<p class="small">${status.progress == null ? '初回は少し時間がかかります。' : '完了するまでアプリを開いたままにしてください（Wi-Fi 推奨）。'}</p>`,
      '<div class="button-row"><button class="secondary-button" data-action="cancel">キャンセル</button></div>',
    );
  } else if (status.kind === 'ready') {
    parts.push(`<h1>${escapeText(status.model.name)} で会話できます</h1>`);
    parts.push(`<div class="suggestions">${SUGGESTIONS.map((s) => `<button class="suggestion" data-suggestion="${escapeText(s)}">${escapeText(s)}</button>`).join('')}</div>`);
  } else if (status.kind === 'failed') {
    parts.push(
      `<h1>${escapeText(status.model.name)} を使えませんでした</h1>`,
      `<p>${escapeText(status.message)}</p>`,
      '<div class="button-row"><button class="primary-button" data-action="retry">再試行</button><button class="secondary-button" data-action="models">別のモデルを選ぶ</button></div>',
    );
  }
  el.empty.innerHTML = parts.join('');
}

function renderMessages() {
  const existing = new Map([...el.messages.children].map((node) => [node.dataset.id, node]));
  const nodes = state.messages.map((message) => {
    const node = existing.get(message.id) ?? createMessageNode(message);
    updateMessageNode(node, message);
    return node;
  });
  el.messages.replaceChildren(...nodes);
}

function createMessageNode(message) {
  const node = document.createElement('div');
  node.className = `msg ${message.role}`;
  node.dataset.id = message.id;
  if (message.role === 'user') {
    node.innerHTML = '<div class="bubble"></div>';
  } else {
    node.innerHTML = `
      <details class="thinking" hidden><summary></summary><div class="thinking-text"></div></details>
      <div class="answer"></div>
      <div class="typing" hidden><span></span><span></span><span></span></div>
      <div class="msg-error" hidden></div>
      <div class="msg-footer" hidden><span class="stats"></span><button type="button" class="copy">コピー</button></div>`;
    node.querySelector('.copy').addEventListener('click', async (event) => {
      const current = state.messages.find((m) => m.id === message.id);
      try {
        await navigator.clipboard.writeText(parseReply(current?.text ?? '').answer);
        event.target.textContent = 'コピーしました';
        setTimeout(() => (event.target.textContent = 'コピー'), 1500);
      } catch {
        event.target.textContent = 'コピーできませんでした';
      }
    });
  }
  return node;
}

function updateMessageNode(node, message) {
  if (message.role === 'user') {
    node.querySelector('.bubble').textContent = message.text;
    return;
  }
  const reply = parseReply(message.text);
  const thinking = node.querySelector('.thinking');
  thinking.hidden = !reply.thinking;
  if (reply.thinking) {
    thinking.querySelector('summary').textContent = reply.isThinking ? '考えています…' : '思考過程';
    thinking.querySelector('.thinking-text').textContent = reply.thinking;
  }
  const answer = node.querySelector('.answer');
  const html = renderMarkdown(reply.answer);
  if (answer.dataset.rendered !== html) {
    answer.innerHTML = html;
    answer.dataset.rendered = html;
  }
  node.querySelector('.typing').hidden = !(message.streaming && !reply.answer && !reply.isThinking);
  const error = node.querySelector('.msg-error');
  error.hidden = !message.error;
  error.textContent = message.error ? `エラー: ${message.error}` : '';
  const footer = node.querySelector('.msg-footer');
  footer.hidden = message.streaming || !reply.answer;
  node.querySelector('.stats').textContent = message.stats ?? '';
}

let pendingFrame = null;
function scheduleMessageUpdate(id) {
  if (pendingFrame) return;
  pendingFrame = requestAnimationFrame(() => {
    pendingFrame = null;
    const node = el.messages.querySelector(`[data-id="${id}"]`);
    const message = state.messages.find((m) => m.id === id);
    if (node && message) updateMessageNode(node, message);
    scrollToBottom(false);
  });
}

function renderComposer() {
  const ready = !!state.engine && state.status.kind === 'ready';
  const generating = !!state.generation;
  el.input.disabled = !ready;
  el.input.placeholder = ready ? 'メッセージ' : 'モデルを準備してください';
  el.sendButton.classList.toggle('stop', generating);
  el.sendButton.setAttribute('aria-label', generating ? '停止' : '送信');
  el.sendButton.disabled = !generating && (!ready || !el.input.value.trim());
}

function scrollToBottom(force) {
  const { scroller } = el;
  const nearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
  if (force || nearBottom) scroller.scrollTop = scroller.scrollHeight;
}

function escapeText(text) {
  const span = document.createElement('span');
  span.textContent = text;
  return span.innerHTML.replace(/"/g, '&quot;');
}

// ---------------------------------------------------------------- models sheet

function openModels() {
  el.customHint.classList.remove('error');
  el.customHint.textContent = 'Hugging Face の GGUF ファイル（目安: 500MB 以下）を追加できます。';
  renderModelList();
  el.gpuStatus.textContent = hasWebGPU() ? '使用できます' : '使用できません（CPU で動作）';
  el.modelsSheet.showModal();
  refreshDownloaded();
}

function renderModelList() {
  const { status } = state;
  el.modelList.replaceChildren(
    ...allModels().map((model) => {
      const downloaded = state.downloaded.has(model.url);
      const isActive = status.kind === 'ready' && status.model.id === model.id;
      const isLoading = status.kind === 'loading' && status.model.id === model.id;

      const row = document.createElement('div');
      row.className = `model-row${isActive ? ' active' : ''}`;
      const tags = [
        model.thinking ? '<span class="tag purple">思考</span>' : '',
        model.heavy ? '<span class="tag orange">大きめ</span>' : '',
      ].join('');
      const meta = [model.bytes ? `約 ${formatBytes(model.bytes)}` : 'サイズ不明', model.custom ? '追加したモデル' : ''].filter(Boolean).join('・');
      row.innerHTML = `
        <button type="button" class="model-main">
          <div class="model-name">${escapeText(model.name)} ${tags}</div>
          <div class="model-summary">${escapeText(model.summary)}</div>
          <div class="model-meta">${escapeText(meta)}</div>
        </button>
        <div class="model-side"></div>`;

      const side = row.querySelector('.model-side');
      if (isLoading) {
        side.innerHTML = status.progress == null ? '<span class="spinner"></span>' : `${Math.floor(status.progress * 100)}%`;
      } else if (downloaded) {
        side.append(textNode(isActive ? '' : '保存済み'));
      } else {
        side.append(textNode('未ダウンロード'));
      }
      if (downloaded || model.custom) {
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'delete';
        remove.textContent = model.custom && !downloaded ? 'リストから外す' : '削除';
        remove.addEventListener('click', async () => {
          if (downloaded) await deleteModel(model);
          if (model.custom && (!downloaded || !state.downloaded.has(model.url))) {
            state.customURLs = state.customURLs.filter((url) => url !== model.url);
            write(KEYS.custom, state.customURLs);
            renderModelList();
          }
        });
        side.append(remove);
      }

      row.querySelector('.model-main').addEventListener('click', () => chooseModel(model, downloaded));
      return row;
    }),
  );
}

function chooseModel(model, downloaded) {
  if (!downloaded) {
    const size = model.bytes ? `約 ${formatBytes(model.bytes)}` : 'モデル';
    const warning = model.heavy ? '\n\nこのモデルは大きめです。メモリが足りない iPhone ではアプリが落ちることがあります。' : '';
    if (!confirm(`${model.name} をダウンロードしますか？\n${size}をダウンロードします（Wi-Fi 推奨）。${warning}`)) return;
  }
  el.modelsSheet.close();
  state.notice = null;
  activate(model);
}

function textNode(text) {
  const span = document.createElement('span');
  span.textContent = text;
  return span;
}

function formatBytes(bytes) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)}GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)}MB`;
  return `${Math.round(bytes / 1e3)}KB`;
}

// ---------------------------------------------------------------- settings sheet

const settingsFields = {
  systemPrompt: $('#systemPrompt'),
  temperature: $('#temperature'),
  maxTokens: $('#maxTokens'),
  enableThinking: $('#enableThinking'),
  contextLevel: $('#contextLevel'),
  useGPU: $('#useGPU'),
};

function openSettings() {
  const { settings } = state;
  settingsFields.systemPrompt.value = settings.systemPrompt;
  settingsFields.temperature.value = settings.temperature;
  $('#temperatureValue').textContent = Number(settings.temperature).toFixed(1);
  settingsFields.maxTokens.value = String(settings.maxTokens);
  settingsFields.enableThinking.checked = settings.enableThinking;
  settingsFields.contextLevel.value = settings.contextLevel;
  settingsFields.useGPU.checked = settings.useGPU && hasWebGPU();
  settingsFields.useGPU.disabled = !hasWebGPU();

  const model = activeModel();
  settingsFields.enableThinking.disabled = !!model && !model.thinking;
  $('#thinkingHint').textContent = model && !model.thinking
    ? '現在のモデルは思考モードに対応していません（Qwen3 で使えます）。'
    : '回答の前にじっくり考えます。複雑な質問で賢くなりますが、応答までの時間が長くなります。';
  $('#reloadModelButton').disabled = !state.status.model;
  el.settingsSheet.showModal();
}

function updateSetting(name, value) {
  state.settings = { ...state.settings, [name]: value };
  write(KEYS.settings, state.settings);
}

settingsFields.systemPrompt.addEventListener('input', (e) => updateSetting('systemPrompt', e.target.value));
settingsFields.temperature.addEventListener('input', (e) => {
  updateSetting('temperature', Number(e.target.value));
  $('#temperatureValue').textContent = Number(e.target.value).toFixed(1);
});
settingsFields.maxTokens.addEventListener('change', (e) => updateSetting('maxTokens', Number(e.target.value)));
settingsFields.enableThinking.addEventListener('change', (e) => updateSetting('enableThinking', e.target.checked));
settingsFields.contextLevel.addEventListener('change', (e) => updateSetting('contextLevel', e.target.value));
settingsFields.useGPU.addEventListener('change', (e) => updateSetting('useGPU', e.target.checked));

$('#resetSettingsButton').addEventListener('click', () => {
  if (!confirm('設定を初期値に戻しますか？')) return;
  state.settings = { ...DEFAULT_SETTINGS };
  write(KEYS.settings, state.settings);
  openSettings();
});
$('#reloadModelButton').addEventListener('click', () => {
  el.settingsSheet.close();
  reloadModel();
});
$('#updateAppButton').addEventListener('click', async () => {
  const button = $('#updateAppButton');
  button.textContent = '確認中…';
  try {
    const registration = await navigator.serviceWorker?.getRegistration();
    await registration?.update();
  } catch {
    // Offline: just reload what we have.
  }
  location.reload();
});

// ---------------------------------------------------------------- events

el.composer.addEventListener('submit', (event) => {
  event.preventDefault();
  if (state.generation) stopGenerating();
  else send();
});

el.input.addEventListener('input', () => {
  autoGrow();
  renderComposer();
});

el.input.addEventListener('keydown', (event) => {
  // On a hardware keyboard, Enter sends and Shift+Enter adds a line. On touch screens the
  // return key always adds a line (it also confirms Japanese IME conversion).
  const coarse = matchMedia('(pointer: coarse)').matches;
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229 && !coarse) {
    event.preventDefault();
    el.composer.requestSubmit();
  }
});

function autoGrow() {
  el.input.style.height = 'auto';
  el.input.style.height = `${Math.min(el.input.scrollHeight, 160)}px`;
}

el.newChatButton.addEventListener('click', newChat);
el.modelButton.addEventListener('click', openModels);
el.settingsButton.addEventListener('click', openSettings);

el.empty.addEventListener('click', (event) => {
  const suggestion = event.target.closest('[data-suggestion]');
  if (suggestion) return send(suggestion.dataset.suggestion);
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'models') openModels();
  if (action === 'cancel') cancelLoading();
  if (action === 'retry' && state.status.model) activate(state.status.model);
});

for (const sheet of [el.modelsSheet, el.settingsSheet]) {
  sheet.addEventListener('click', (event) => {
    if (event.target === sheet || event.target.closest('[data-close]')) sheet.close();
  });
}

el.customForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const model = customModel(el.customInput.value);
  if (!model) {
    el.customHint.classList.add('error');
    el.customHint.textContent = '「https://…/ファイル.gguf」または「作者/リポジトリ/ファイル.gguf」の形式で入力してください。';
    return;
  }
  if (!state.customURLs.includes(model.url) && !MODELS.some((m) => m.url === model.url)) {
    state.customURLs.push(model.url);
    write(KEYS.custom, state.customURLs);
  }
  el.customInput.value = '';
  el.customHint.classList.remove('error');
  renderModelList();
  chooseModel(findModel(model.id) ?? MODELS.find((m) => m.url === model.url), state.downloaded.has(model.url));
});

// Keep the composer above the on-screen keyboard (iOS shrinks only the visual viewport).
function fitViewport() {
  const viewport = window.visualViewport;
  const height = viewport ? viewport.height : window.innerHeight;
  document.documentElement.style.setProperty('--app-height', `${height}px`);
  document.body.classList.toggle('keyboard-open', !!viewport && window.innerHeight - viewport.height > 120);
  if (viewport && viewport.offsetTop) window.scrollTo(0, 0);
}
window.visualViewport?.addEventListener('resize', () => {
  fitViewport();
  scrollToBottom(false);
});
window.visualViewport?.addEventListener('scroll', fitViewport);
window.addEventListener('resize', fitViewport);

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') saveChat();
  else if (loadController && !wakeLock) requestWakeLock();
});

// ---------------------------------------------------------------- startup

function describeError(error) {
  const message = String(error?.message ?? error);
  if (/Failed to fetch|NetworkError|network|Load failed|offline/i.test(message)) {
    return 'インターネットに接続できません。モデルの初回ダウンロードには通信が必要です。';
  }
  if (/memory|OOM|allocat|Out of bounds|RangeError/i.test(message)) {
    return `メモリが足りませんでした。より小さいモデルを選ぶか、設定で「会話の記憶の長さ」を短くしてください。（${message}）`;
  }
  if (/context|exceed/i.test(message)) {
    return '会話が長くなりすぎました。「新しいチャット」を始めてください。';
  }
  return message;
}

function noticeFromLastSession() {
  const pending = read(KEYS.pending, null);
  write(KEYS.pending, null);
  if (!pending) return null;
  const model = findModel(pending.modelID);
  const name = model?.name ?? 'モデル';
  const smaller = [{ label: '別のモデルを選ぶ', run: openModels }];
  if (pending.phase === 'download') {
    return { title: 'ダウンロードが中断されました', text: `${name} をもう一度選ぶと、最初からダウンロードし直します。`, actions: smaller };
  }
  if (pending.phase === 'load') {
    return { title: '前回、モデルの読み込み中にアプリが終了しました', text: `メモリ不足の可能性があります。より小さいモデルを選ぶか、設定で「会話の記憶の長さ」を「短い」にしてから ${name} を選び直してください。`, actions: smaller, blockAutoload: true };
  }
  if (pending.phase === 'generate') {
    return { title: '前回、応答の生成中にアプリが終了しました', text: 'メモリ不足の可能性があります。「新しいチャット」で会話を短くするか、設定で「会話の記憶の長さ」を「短い」にしてください。', actions: smaller, blockAutoload: true };
  }
  return null;
}

async function start() {
  $('#versionInfo').textContent = `ローカルLLM Web版 ${APP_VERSION}・エンジン wllama 3.8.1（llama.cpp）`;
  fitViewport();
  state.notice = noticeFromLastSession();
  render();
  scrollToBottom(true);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js').catch((error) => console.warn('Service worker registration failed', error));
  }

  await refreshDownloaded();
  const last = findModel(read(KEYS.lastModel, ''));
  if (last && state.downloaded.has(last.url) && !state.notice?.blockAutoload) {
    activate(last);
  }
}

start();
