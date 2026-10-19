// Thin wrapper over wllama (llama.cpp compiled to WebAssembly, with WebGPU when available).
//
// Safari has neither JSPI nor wasm64, so wllama runs its "compat" build there. Both builds
// are served from this site; the wasm and worker code are handed over as blob: URLs so the
// model can still be loaded with no network (the service worker has cached the files).

import { ModelManager, Wllama } from '../vendor/wllama-3.8.1/index.js';

const asset = (path) => new URL(`../vendor/${path}`, import.meta.url).href;

const ASSETS = {
  wasm: asset('wllama-3.8.1/wllama.wasm'),
  compatWasm: asset('wllama-compat-3.8.1/wllama.wasm'),
  compatWorker: asset('wllama-compat-3.8.1/wllama.js'),
};

const quietLogger = {
  debug() {},
  log() {},
  warn: (...args) => console.warn('[wllama]', ...args),
  error: (...args) => console.error('[wllama]', ...args),
};

let blobAssets;

async function localAssets() {
  if (!blobAssets) {
    const get = async (url) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`アプリのファイルを読み込めませんでした (${response.status})`);
      return response;
    };
    const blobURL = async (url) => URL.createObjectURL(await (await get(url)).blob());
    const needsCompat = !('Suspending' in WebAssembly) || !supportsMemory64();
    blobAssets = needsCompat
      ? {
          paths: { default: ASSETS.wasm },
          compat: { wasm: await blobURL(ASSETS.compatWasm), worker: { code: await (await get(ASSETS.compatWorker)).text() } },
        }
      : { paths: { default: await blobURL(ASSETS.wasm) }, compat: null };
  }
  return blobAssets;
}

function supportsMemory64() {
  try {
    new WebAssembly.Memory({ address: 'i64', initial: 1n });
    return true;
  } catch {
    return false;
  }
}

export const hasWebGPU = () => typeof navigator !== 'undefined' && !!navigator.gpu;

async function createWllama() {
  const { paths, compat } = await localAssets();
  const wllama = new Wllama(paths, {
    suppressNativeLog: true,
    allowOffline: true,
    parallelDownloads: 2,
    logger: quietLogger,
  });
  wllama.setCompat(compat);
  return wllama;
}

let modelManager;
const manager = () => (modelManager ??= new ModelManager({ logger: quietLogger, allowOffline: true }));

/** Lists and deletes downloaded model files (stored in OPFS by wllama). */
export const storage = {
  /** Completed downloads: model URL → bytes on disk. */
  async downloadedFiles() {
    try {
      const models = await manager().getModels();
      return new Map(models.map((m) => [m.url, m.size]));
    } catch {
      return new Map();
    }
  },

  async remove(url) {
    const models = await manager().getModels({ includeInvalid: true });
    await Promise.all(models.filter((m) => m.url === url).map((m) => m.remove()));
  },
};

export class Engine {
  constructor(model, wllama) {
    this.model = model;
    this.wllama = wllama;
  }

  /**
   * Downloads the model if needed, then loads it.
   * @param {(fraction: number) => void} onProgress download progress, 0...1
   */
  static async load(model, { contextSize, useGPU, onProgress, signal }) {
    const tryLoad = async (gpu) => {
      const wllama = await createWllama();
      try {
        await wllama.loadModelFromUrl(model.url, {
          n_ctx: contextSize,
          n_batch: 256,
          n_ubatch: 256,
          n_gpu_layers: gpu ? 999 : 0,
          // Keep <think>…</think> in the text; the UI splits it out.
          reasoning_format: 'none',
          progressCallback: ({ loaded, total }) => onProgress?.(total > 0 ? loaded / total : 0),
          signal,
        });
        return new Engine(model, wllama);
      } catch (error) {
        await wllama.exit().catch(() => {});
        throw error;
      }
    };

    const gpu = useGPU && hasWebGPU();
    try {
      return await tryLoad(gpu);
    } catch (error) {
      if (!gpu || signal?.aborted || isNetworkError(error)) throw error;
      console.warn('GPU load failed, retrying on CPU', error);
      return await tryLoad(false);
    }
  }

  /**
   * Streams the reply to `messages` (OpenAI-style). Yields text chunks; returns stats.
   */
  async *chat(messages, { temperature, maxTokens, enableThinking, signal }) {
    const stream = await this.wllama.createChatCompletion({
      messages,
      stream: true,
      max_tokens: maxTokens,
      temperature,
      ...this.model.sampling,
      chat_template_kwargs: { enable_thinking: this.model.thinking && enableThinking },
      abortSignal: signal,
    });
    let timings;
    for await (const chunk of stream) {
      const text = chunk.choices?.[0]?.delta?.content;
      if (text) yield text;
      if (chunk.timings) timings = chunk.timings;
    }
    return timings;
  }

  async unload() {
    await this.wllama.exit().catch(() => {});
  }
}

export function isAbortError(error) {
  return error?.name === 'AbortError' || error?.name === 'WllamaAbortError';
}

function isNetworkError(error) {
  return error instanceof TypeError || /fetch|network|download/i.test(String(error?.message));
}
