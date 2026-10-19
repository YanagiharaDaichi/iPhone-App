// Minimal Markdown → HTML for model replies. Everything is HTML-escaped first and only a
// fixed set of tags is produced, so model output can never inject markup.

const escapeHTML = (text) =>
  text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

export function renderMarkdown(text) {
  // Fenced code blocks first; an unclosed fence (still streaming) runs to the end.
  return text
    .split('```')
    .map((part, index) => (index % 2 === 1 ? codeBlock(part) : blocks(part)))
    .join('');
}

function codeBlock(part) {
  const newline = part.indexOf('\n');
  // The first line is the language tag (```swift).
  const code = newline >= 0 ? part.slice(newline + 1) : part;
  return `<pre><code>${escapeHTML(code.replace(/\n$/, ''))}</code></pre>`;
}

function blocks(text) {
  const html = [];
  let paragraph = [];
  let list = null; // { ordered, items }

  const flushParagraph = () => {
    if (paragraph.length) html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
    paragraph = [];
  };
  const flushList = () => {
    if (list) {
      const tag = list.ordered ? 'ol' : 'ul';
      html.push(`<${tag}>${list.items.map((item) => `<li>${inline(item)}</li>`).join('')}</${tag}>`);
    }
    list = null;
  };

  for (const line of text.split('\n')) {
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    const bullet = line.match(/^\s*(?:[-*+・•])\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);

    if (!line.trim()) {
      flushParagraph();
      flushList();
    } else if (heading) {
      flushParagraph();
      flushList();
      html.push(`<h4>${inline(heading[1])}</h4>`);
    } else if (bullet || numbered) {
      flushParagraph();
      const ordered = !!numbered;
      if (list && list.ordered !== ordered) flushList();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)[1]);
    } else if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushParagraph();
      flushList();
      html.push('<hr>');
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return html.join('');
}

function inline(text) {
  // Pull out code spans so their contents are not formatted.
  const spans = [];
  const placeholder = (html) => `\u0000${spans.push(html) - 1}\u0000`;
  let out = escapeHTML(text).replace(/`([^`]+)`/g, (_, code) => placeholder(`<code>${code}</code>`));

  out = out
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  return out.replace(/\u0000(\d+)\u0000/g, (_, i) => spans[Number(i)]);
}

/**
 * Splits `<think>…</think>` reasoning from the visible answer. Handles a reply still
 * streaming its reasoning, and templates that put `<think>` in the prompt.
 */
export function parseReply(text) {
  // End-of-turn markers some models print as text instead of stopping on them.
  const raw = text.replace(/(?:<\/s>|<\|im_end\|>|<\|endoftext\|>|<end_of_turn>|<\|im_start\|>)\s*$/g, '');
  const end = raw.indexOf('</think>');
  if (end >= 0) {
    const start = raw.indexOf('<think>');
    const thinking = raw.slice(start >= 0 && start < end ? start + 7 : 0, end).trim();
    return { thinking: thinking || null, answer: raw.slice(end + 8).trim(), isThinking: false };
  }
  const start = raw.indexOf('<think>');
  if (start >= 0) {
    return { thinking: raw.slice(start + 7).trim(), answer: raw.slice(0, start).trim(), isThinking: true };
  }
  return { thinking: null, answer: raw.trim(), isThinking: false };
}
