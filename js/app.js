import { detectWeb, googleImageSearchUrl, VisionError } from './vision.js';
import { toJpegBase64 } from './image.js';

const API_KEY_STORAGE = 'image-search:vision-api-key';

const $ = (selector) => document.querySelector(selector);
const picker = $('#picker');
const preview = $('#preview');
const pickerTitle = $('#picker-title');
const fileInput = $('#file-input');
const cameraInput = $('#camera-input');
const statusArea = $('#status');
const resultsArea = $('#results');
const keyNotice = $('#key-notice');
const settingsDialog = $('#settings-dialog');
const apiKeyInput = $('#api-key-input');

let currentFile = null;
let previewUrl = null;
let controller = null;
let lastSearchFailed = false;

// API キーの保存

function loadApiKey() {
  try {
    return localStorage.getItem(API_KEY_STORAGE) ?? '';
  } catch {
    return '';
  }
}

function saveApiKey(key) {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
    return true;
  } catch {
    return false;
  }
}

function updateKeyNotice() {
  keyNotice.hidden = Boolean(loadApiKey());
}

// 画像の選択と検索

function selectFile(file) {
  if (!file) return;
  if (!file.type.startsWith('image/')) {
    showError('画像ファイルを選んでください。');
    return;
  }

  currentFile = file;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = URL.createObjectURL(file);
  preview.src = previewUrl;
  preview.hidden = false;
  picker.classList.add('has-image');
  pickerTitle.textContent = '別の画像で検索';
  search();
}

async function search() {
  if (!currentFile) return;

  // 前の検索が終わっていなければ取り消し、新しい検索に置き換える。
  controller?.abort();
  const current = new AbortController();
  controller = current;

  resultsArea.replaceChildren();
  showLoading();

  try {
    const base64 = await toJpegBase64(currentFile);
    if (current.signal.aborted) return;
    const detection = await detectWeb(base64, loadApiKey(), { signal: current.signal });
    lastSearchFailed = false;
    statusArea.replaceChildren();
    renderResults(detection);
  } catch (error) {
    if (current.signal.aborted) return;
    lastSearchFailed = true;
    const keyProblem =
      error instanceof VisionError &&
      (error.kind === 'missing-key' || error.code === 400 || error.code === 403);
    showError(error.message, { showSettings: keyProblem, showRetry: true });
  } finally {
    if (controller === current) controller = null;
  }
}

// 状態の表示

function showLoading() {
  statusArea.replaceChildren(
    el('div', { class: 'loading' }, [el('span', { class: 'spinner', 'aria-hidden': 'true' }), '検索中…']),
  );
}

function showError(message, { showSettings = false, showRetry = false } = {}) {
  const actions = [];
  if (showRetry) {
    actions.push(el('button', { class: 'button', type: 'button', onclick: search }, ['もう一度試す']));
  }
  if (showSettings) {
    actions.push(el('button', { class: 'button primary', type: 'button', onclick: openSettings }, ['設定を開く']));
  }
  statusArea.replaceChildren(
    el('div', { class: 'message error', role: 'alert' }, [
      el('p', { class: 'message-title', text: '検索できませんでした' }),
      el('p', { class: 'message-body', text: message }),
      actions.length ? el('div', { class: 'message-actions' }, actions) : '',
    ]),
  );
}

function renderResults(detection) {
  if (detection.isEmpty) {
    resultsArea.replaceChildren(
      el('div', { class: 'message' }, [
        el('p', { class: 'message-title', text: '見つかりませんでした' }),
        el('p', { class: 'message-body', text: '似ている画像は見つかりませんでした。別の画像でお試しください。' }),
      ]),
    );
    return;
  }

  const sections = [];
  if (detection.pages.length) {
    sections.push(
      section(
        '同じ画像が見つかったサイト',
        detection.pages.length,
        [el('div', { class: 'pages' }, detection.pages.map(pageRow))],
        'タップすると、その画像が載っているページが開きます。',
      ),
    );
  }
  if (detection.keywords.length) {
    sections.push(
      section('キーワード', null, [
        el(
          'div',
          { class: 'chips' },
          detection.keywords.map((keyword) =>
            externalLink(googleImageSearchUrl(keyword), { class: 'chip', title: `「${keyword}」で画像検索` }, [
              keyword,
            ]),
          ),
        ),
      ]),
    );
  }
  if (detection.similarImages.length) {
    sections.push(section('類似画像', detection.similarImages.length, [imageGrid(detection.similarImages)]));
  }
  if (detection.otherMatchingImages.length) {
    sections.push(
      section(
        'その他の同じ画像',
        detection.otherMatchingImages.length,
        [imageGrid(detection.otherMatchingImages)],
        '掲載ページが分からなかった画像です。タップすると画像そのものが開きます。',
      ),
    );
  }
  resultsArea.replaceChildren(...sections);
}

const matchLabels = { full: '完全一致', partial: '一部一致' };

function pageRow(page) {
  const meta = [el('span', { class: 'page-host', text: page.host })];
  if (page.match) {
    meta.unshift(el('span', { class: `badge ${page.match}`, text: matchLabels[page.match] }));
  }
  return externalLink(page.url, { class: 'page' }, [
    thumbnail(page.thumbnail),
    el('span', { class: 'page-text' }, [
      el('span', { class: 'page-title', text: page.title }),
      el('span', { class: 'page-meta' }, meta),
    ]),
    el('span', { class: 'page-open', 'aria-hidden': 'true' }),
  ]);
}

function section(title, count, children, note) {
  const heading = el('h2', {}, [title]);
  if (count != null) heading.append(el('span', { class: 'count', text: `${count}件` }));
  const parts = [heading];
  if (note) parts.push(el('p', { class: 'section-note', text: note }));
  return el('section', { class: 'result-section' }, [...parts, ...children]);
}

function imageGrid(images) {
  return el(
    'div',
    { class: 'grid' },
    images.map((image) => externalLink(image.url, { class: 'grid-item' }, [thumbnail(image.thumbnail)])),
  );
}

function thumbnail(src) {
  const frame = el('span', { class: 'thumb' });
  if (!src) {
    frame.classList.add('broken');
    return frame;
  }
  // 直リンクを拒否するサイトが多いため、リファラーを送らずに読み込む。
  const image = el('img', { alt: '', loading: 'lazy', decoding: 'async', referrerpolicy: 'no-referrer', src });
  image.addEventListener('error', () => frame.classList.add('broken'), { once: true });
  frame.append(image);
  return frame;
}

function externalLink(href, props, children) {
  return el('a', { ...props, href, target: '_blank', rel: 'noopener noreferrer' }, children);
}

/** 外部から来た文字列は textContent で入れ、HTML として解釈させない。 */
function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

// 設定

function openSettings() {
  apiKeyInput.value = loadApiKey();
  settingsDialog.returnValue = '';
  settingsDialog.showModal();
}

settingsDialog.addEventListener('close', () => {
  if (settingsDialog.returnValue !== 'save') return;
  if (!saveApiKey(apiKeyInput.value.trim())) {
    alert('API キーを保存できませんでした。プライベートブラウズを使っている場合は解除してお試しください。');
    return;
  }
  updateKeyNotice();
  // API キーが原因で失敗していた場合に備え、同じ画像で検索し直す。
  if (lastSearchFailed) search();
});

$('#cancel-settings').addEventListener('click', () => settingsDialog.close('cancel'));
$('#settings-button').addEventListener('click', openSettings);
document.querySelectorAll('[data-open-settings]').forEach((button) => button.addEventListener('click', openSettings));

// 画像の入力(ファイル選択・カメラ・ドロップ・貼り付け)

$('#choose-button').addEventListener('click', () => fileInput.click());
$('#camera-button').addEventListener('click', () => cameraInput.click());

for (const input of [fileInput, cameraInput]) {
  input.addEventListener('change', () => {
    selectFile(input.files?.[0]);
    // 同じ画像をもう一度選んでも change が発生するように空にしておく。
    input.value = '';
  });
}

document.addEventListener('dragover', (event) => {
  event.preventDefault();
  picker.classList.add('dragging');
});
document.addEventListener('dragleave', (event) => {
  if (!event.relatedTarget) picker.classList.remove('dragging');
});
document.addEventListener('drop', (event) => {
  event.preventDefault();
  picker.classList.remove('dragging');
  selectFile(event.dataTransfer?.files?.[0]);
});

document.addEventListener('paste', (event) => {
  if (event.target instanceof HTMLInputElement) return;
  const file = [...(event.clipboardData?.files ?? [])].find((item) => item.type.startsWith('image/'));
  if (file) {
    event.preventDefault();
    selectFile(file);
  }
});

updateKeyNotice();
