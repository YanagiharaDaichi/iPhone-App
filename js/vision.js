// Google Cloud Vision API の Web 検出(WEB_DETECTION)で、画像に似た画像や
// その画像が掲載されているページをネット上から探す。
// https://cloud.google.com/vision/docs/detecting-web

export const ENDPOINT = 'https://vision.googleapis.com/v1/images:annotate';

export class VisionError extends Error {
  /**
   * @param {string} message
   * @param {{ kind?: 'missing-key' | 'network' | 'server' | 'invalid', code?: number }} [options]
   */
  constructor(message, { kind = 'server', code } = {}) {
    super(message);
    this.name = 'VisionError';
    this.kind = kind;
    this.code = code;
  }
}

export function buildRequestBody(base64Image, maxResults = 30) {
  return {
    requests: [
      {
        image: { content: base64Image },
        features: [{ type: 'WEB_DETECTION', maxResults }],
        imageContext: { webDetectionParams: { includeGeoResults: true } },
      },
    ],
  };
}

/**
 * @param {string} base64Image JPEG などの画像を base64 にしたもの(data: の接頭辞なし)
 * @param {string} apiKey
 * @param {{ signal?: AbortSignal, fetch?: typeof fetch }} [options]
 */
export async function detectWeb(base64Image, apiKey, { signal, fetch: fetchImpl = fetch } = {}) {
  if (!apiKey) {
    throw new VisionError(
      'API キーが設定されていません。右上の設定から Google Cloud Vision API の API キーを登録してください。',
      { kind: 'missing-key' },
    );
  }

  let response;
  try {
    response = await fetchImpl(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Goog-Api-Key': apiKey },
      body: JSON.stringify(buildRequestBody(base64Image)),
      signal,
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new VisionError('ネットワークに接続できませんでした。通信環境を確認してください。', {
      kind: 'network',
    });
  }
  return parseResponse(await response.text(), response.status);
}

export function parseResponse(text, status) {
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // JSON 以外のエラーページが返ることもあるので、下でステータスコードから判断する。
  }

  const error = json?.error ?? json?.responses?.[0]?.error;
  if (error) {
    const code = error.code ?? status;
    throw new VisionError(`検索に失敗しました(${code}): ${error.message ?? ''}`.trim(), { code });
  }
  if (status < 200 || status >= 300) {
    throw new VisionError(`検索に失敗しました(${status})`, { code: status });
  }
  const first = json?.responses?.[0];
  if (!first) {
    throw new VisionError('サーバーから想定外の応答が返されました。', { kind: 'invalid' });
  }
  // 何も見つからなかった場合は webDetection 自体が省略される。
  return normalizeWebDetection(first.webDetection ?? {});
}

/** API の応答を、画面に表示しやすい形に整える。 */
export function normalizeWebDetection(web) {
  const keywords = uniqueBy(
    [
      ...(web.bestGuessLabels ?? []).map((label) => label.label),
      ...(web.webEntities ?? []).map((entity) => entity.description),
    ]
      .map((text) => (text ?? '').trim())
      .filter(Boolean),
    (text) => text.toLowerCase(),
  );

  const imagesOnPages = new Set();
  const pages = uniqueBy(
    (web.pagesWithMatchingImages ?? []).filter((page) => isWebUrl(page.url)),
    (page) => page.url,
  ).map((page) => {
    const full = (page.fullMatchingImages ?? []).filter((image) => isWebUrl(image.url));
    const partial = (page.partialMatchingImages ?? []).filter((image) => isWebUrl(image.url));
    for (const image of [...full, ...partial]) imagesOnPages.add(image.url);

    const host = hostOf(page.url);
    const preview = full[0]?.url ?? partial[0]?.url;
    return {
      url: page.url,
      title: stripHtml(page.pageTitle ?? '') || host,
      host,
      thumbnail: preview ? toHttps(preview) : null,
      // full: 同じ画像(サイズ違いを含む) / partial: 切り抜きや加工をした画像
      match: full.length ? 'full' : partial.length ? 'partial' : null,
    };
  });
  // 完全一致のサイトを先に並べる(sort は安定なので API の並び順は保たれる)。
  const matchRank = { full: 0, partial: 1 };
  pages.sort((a, b) => (matchRank[a.match] ?? 2) - (matchRank[b.match] ?? 2));

  const similarImages = toImages(web.visuallySimilarImages);
  // 掲載サイトが分かっている画像はサイトの一覧に出すので、それ以外だけを残す。
  const otherMatchingImages = toImages([
    ...(web.fullMatchingImages ?? []),
    ...(web.partialMatchingImages ?? []),
  ]).filter((image) => !imagesOnPages.has(image.url));

  return {
    keywords,
    pages,
    similarImages,
    otherMatchingImages,
    isEmpty:
      keywords.length === 0 &&
      pages.length === 0 &&
      similarImages.length === 0 &&
      otherMatchingImages.length === 0,
  };
}

function toImages(images = []) {
  return uniqueBy(
    images.filter((image) => isWebUrl(image.url)),
    (image) => image.url,
  ).map((image) => ({ url: image.url, thumbnail: toHttps(image.url) }));
}

function uniqueBy(items, keyOf) {
  const seen = new Set();
  return items.filter((item) => {
    const key = keyOf(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function isWebUrl(value) {
  try {
    const { protocol } = new URL(value);
    return protocol === 'http:' || protocol === 'https:';
  } catch {
    return false;
  }
}

/** https のページから http の画像は読み込めないため、https に置き換えて読み込みを試みる。 */
export function toHttps(value) {
  const url = new URL(value);
  url.protocol = 'https:';
  return url.href;
}

export function hostOf(value) {
  try {
    return new URL(value).hostname;
  } catch {
    return value;
  }
}

/** pageTitle に含まれる <b> などの HTML タグを取り除き、文字参照を元の文字に戻す。 */
export function stripHtml(html) {
  const named = { lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
  return (
    html
      .replace(/<[^>]*>/g, '')
      .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
      .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(parseInt(code, 16)))
      .replace(/&(lt|gt|quot|apos|nbsp);/g, (_, name) => named[name])
      // "&amp;lt;" を "<" にしてしまわないよう、"&amp;" は最後に置き換える。
      .replace(/&amp;/g, '&')
      .trim()
  );
}

export function googleImageSearchUrl(keyword) {
  const url = new URL('https://www.google.com/search');
  url.searchParams.set('tbm', 'isch');
  url.searchParams.set('q', keyword);
  return url.href;
}
