const BLOCK_ELEMENTS = new Set([
  "html", "head", "body", "header", "footer", "main", "nav", "aside",
  "section", "article", "div", "table", "thead", "tbody", "tfoot", "tr",
  "th", "td", "caption", "colgroup", "col", "ul", "ol", "li", "dl", "dt", "dd",
  "h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "hr", "br",
  "fieldset", "legend", "form", "figure", "figcaption", "details", "summary",
  "dialog", "address",
]);

const VOID_ELEMENTS = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr",
]);

const PRESERVE_BLOCKS = ["style", "script", "pre", "code", "svg"];

interface Token {
  kind: "text" | "open" | "close" | "self_close" | "comment" | "doctype" | "raw_block";
  raw: string;
  tagName?: string;
  blockEnd?: string;
  indentChange?: number;
}

function tokenize(html: string): Token[] {
  const tokens: Token[] = [];
  let pos = 0;

  while (pos < html.length) {
    const rest = html.slice(pos);

    const doctypeMatch = rest.match(/^<!doctype\s[^>]*>/i);
    if (doctypeMatch) {
      tokens.push({ kind: "doctype", raw: doctypeMatch[0] });
      pos += doctypeMatch[0].length;
      continue;
    }

    const commentMatch = rest.match(/^<!--[\s\S]*?-->/);
    if (commentMatch) {
      tokens.push({ kind: "comment", raw: commentMatch[0] });
      pos += commentMatch[0].length;
      continue;
    }

    const tagMatch = rest.match(/^<\/?([a-zA-Z][\w-]*)([\s\S]*?)>/);
    if (tagMatch) {
      const tagName = tagMatch[1].toLowerCase();
      const fullTag = tagMatch[0];
      const isClosing = fullTag.startsWith("</");
      const isSelfClose = fullTag.endsWith("/>") || VOID_ELEMENTS.has(tagName);

      if (PRESERVE_BLOCKS.includes(tagName)) {
        const blockEnd = `</${tagName}>`;
        const endIdx = html.toLowerCase().indexOf(blockEnd, pos + fullTag.length);
        if (endIdx !== -1) {
          const inner = html.slice(pos + fullTag.length, endIdx);
          tokens.push({
            kind: "raw_block",
            raw: fullTag + inner + blockEnd,
            tagName,
            blockEnd,
          });
          pos = endIdx + blockEnd.length;
          continue;
        }
      }

      if (isSelfClose) {
        tokens.push({ kind: "self_close", raw: fullTag, tagName });
      } else if (isClosing) {
        tokens.push({ kind: "close", raw: fullTag, tagName });
      } else {
        tokens.push({ kind: "open", raw: fullTag, tagName });
      }
      pos += fullTag.length;
      continue;
    }

    const nextTagIdx = rest.indexOf("<");
    if (nextTagIdx === -1) {
      const text = rest;
      if (text.trim()) {
        tokens.push({ kind: "text", raw: text });
      }
      break;
    }

    if (nextTagIdx > 0) {
      const text = rest.slice(0, nextTagIdx);
      if (text.trim()) {
        tokens.push({ kind: "text", raw: text });
      }
      pos += nextTagIdx;
    } else {
      pos++;
    }
  }

  return tokens;
}

export function formatHtml(html: string): string {
  if (!html || html.trim().length === 0) return html;
  if (!/<[a-zA-Z!]/.test(html)) return html;

  const tokens = tokenize(html);
  const lines: string[] = [];
  let indent = 0;
  let lineBuffer = "";
  const TAB = "  ";

  function flushLine() {
    const trimmed = lineBuffer.trimEnd();
    if (trimmed) {
      lines.push(TAB.repeat(Math.max(0, indent)) + trimmed);
    } else {
      lines.push("");
    }
    lineBuffer = "";
  }

  function appendToLine(str: string) {
    lineBuffer += str;
  }

  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    const next = tokens[i + 1];
    const prev = tokens[i - 1];

    if (t.kind === "doctype") {
      flushLine();
      appendToLine(t.raw);
      flushLine();
      continue;
    }

    if (t.kind === "comment") {
      const prevIsBlock = prev && (prev.kind === "open" || prev.kind === "close" || prev.kind === "self_close" || prev.kind === "doctype");
      if (prevIsBlock && lineBuffer.trim()) {
        flushLine();
      }
      if (t.raw.includes("\n")) {
        flushLine();
        const commentLines = t.raw.split("\n");
        for (const cl of commentLines) {
          const trimmed = cl.trim();
          if (trimmed) {
            lines.push(TAB.repeat(indent) + trimmed);
          }
        }
      } else {
        appendToLine(" " + t.raw);
      }
      continue;
    }

    if (t.kind === "raw_block") {
      flushLine();
      const blockLines = t.raw.split("\n");
      for (const bl of blockLines) {
        lines.push(TAB.repeat(indent) + bl);
      }
      flushLine();
      continue;
    }

    if (t.kind === "text") {
      const trimmed = t.raw.trim();
      if (!trimmed) continue;
      appendToLine(trimmed);
      continue;
    }

    if (t.kind === "open") {
      const tagName = t.tagName!;
      const isBlock = BLOCK_ELEMENTS.has(tagName);

      if (isBlock) {
        flushLine();
        appendToLine(t.raw);
        const nextIsText = next && next.kind === "text";
        const nextIsBlockClose = next && next.kind === "close" && BLOCK_ELEMENTS.has(next.tagName!);
        if (!nextIsText && !nextIsBlockClose) {
          flushLine();
        }
        indent++;
      } else {
        const prevIsBlock = prev && (prev.kind === "open" || prev.kind === "close" || prev.kind === "self_close" || prev.kind === "doctype" || prev.kind === "raw_block");
        if (prevIsBlock) {
          flushLine();
        }
        appendToLine(t.raw);
      }
      continue;
    }

    if (t.kind === "self_close") {
      const tagName = t.tagName!;
      const isBlock = BLOCK_ELEMENTS.has(tagName);
      if (isBlock) {
        flushLine();
        appendToLine(t.raw);
        flushLine();
      } else {
        appendToLine(t.raw);
      }
      continue;
    }

    if (t.kind === "close") {
      const tagName = t.tagName!;
      const isBlock = BLOCK_ELEMENTS.has(tagName);
      if (isBlock) {
        indent = Math.max(0, indent - 1);
        flushLine();
        appendToLine(t.raw);
        flushLine();
      } else {
        appendToLine(t.raw);
      }
      continue;
    }
  }

  flushLine();
  return lines.join("\n").trim();
}
