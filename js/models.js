// Models small enough for iPhone Safari, which kills a page that uses much more than
// ~1GB. All are GGUF files on Hugging Face, downloaded once and kept on the device.

const hf = (repo, file) => `https://huggingface.co/${repo}/resolve/main/${file}`;

export const MODELS = [
  {
    id: 'sarashina2.2-0.5b',
    name: 'Sarashina2.2 0.5B',
    summary: 'おすすめ。日本語に特化した小型モデル（SB Intuitions）。正確で自然な日本語。',
    url: hf('mmnga/sarashina2.2-0.5b-instruct-v0.1-gguf', 'sarashina2.2-0.5b-instruct-v0.1-Q3_K_M.gguf'),
    bytes: 438_600_000,
    thinking: false,
    contextSize: 2048,
    sampling: { top_k: 40, top_p: 0.9, repeat_penalty: 1.1, stop: ['</s>'] },
  },
  {
    id: 'lfm2.5-1.2b-jp',
    name: 'LFM2.5 1.2B JP',
    summary: '一番賢い日本語特化モデル。大きめなので新しい iPhone 向け（メモリ不足で落ちることがあります）。',
    url: hf('LiquidAI/LFM2.5-1.2B-JP-202606-GGUF', 'LFM2.5-1.2B-JP-202606-Q4_0.gguf'),
    bytes: 695_800_000,
    thinking: false,
    contextSize: 2048,
    heavy: true,
    sampling: { min_p: 0.15, top_p: 1, repeat_penalty: 1.05 },
  },
  {
    id: 'lfm2.5-350m',
    name: 'LFM2.5 350M',
    summary: '最軽量・最速。古めの iPhone や、まず動作を試したいときに。',
    url: hf('LiquidAI/LFM2.5-350M-GGUF', 'LFM2.5-350M-Q4_K_M.gguf'),
    bytes: 229_300_000,
    thinking: false,
    contextSize: 4096,
    sampling: { min_p: 0.15, top_p: 1, repeat_penalty: 1.05 },
  },
  {
    id: 'qwen3-0.6b',
    name: 'Qwen3 0.6B',
    summary: '「思考モード」に対応（答える前に考える）。日本語の正確さは控えめ。',
    url: hf('unsloth/Qwen3-0.6B-GGUF', 'Qwen3-0.6B-Q4_K_M.gguf'),
    bytes: 396_700_000,
    thinking: true,
    contextSize: 2048,
    sampling: { top_k: 20, top_p: 0.9, repeat_penalty: 1.1 },
  },
];


/** A model the user added by URL (or Hugging Face "owner/repo/file.gguf"). */
export function customModel(source) {
  const url = normalizeModelURL(source);
  if (!url) return null;
  const file = decodeURIComponent(url.split('/').pop() || url);
  return {
    id: `custom:${url}`,
    name: file.replace(/\.gguf$/i, ''),
    summary: url,
    url,
    bytes: null,
    thinking: /qwen3/i.test(file),
    contextSize: 2048,
    custom: true,
    sampling: { top_k: 40, top_p: 0.9, repeat_penalty: 1.1 },
  };
}

function normalizeModelURL(source) {
  const text = source.trim();
  if (/^https:\/\/\S+\.gguf(\?\S*)?$/i.test(text)) {
    return text.replace('/blob/', '/resolve/');
  }
  // owner/repo/path/to/file.gguf
  const match = text.match(/^([\w.-]+\/[\w.-]+)\/(\S+\.gguf)$/i);
  return match ? hf(match[1], match[2]) : null;
}
