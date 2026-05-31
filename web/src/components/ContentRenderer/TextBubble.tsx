import React, { Fragment, useMemo } from "react";
import { marked } from "marked";
import { CodeBlock } from "./CodeBlock";
import { FilePreviewPane, extractFilesFromText } from "./FilePreviewPane";

marked.setOptions({ breaks: true, gfm: true });

interface Props {
  text: string;
}

/* ── Unified JSON wrapper detection ───────────────────────────── */

interface ParsedWrapper {
  kind: "file" | "preview" | "code" | "text";
  title?: string;
  fileName?: string;
  mimeType?: string;
  language?: string;
  content: string;
  prefix: string;
  rawArgs?: Record<string, unknown>;
}

function tryJsonParse(text: string): Record<string, unknown> | null {
  try {
    const trimmed = text.trim();
    if (!trimmed.startsWith("{")) return null;
    return JSON.parse(trimmed) as Record<string, unknown>;
  } catch {
    return null;
  }
}

function stringVal(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function digContent(obj: Record<string, unknown>, maxDepth = 4): string | null {
  if (maxDepth <= 0) return null;

  for (const key of ["content", "text", "result"]) {
    const val = obj[key];
    if (typeof val === "string" && val.length > 10) return val;
  }

  const args = obj.arguments ?? obj.args ?? obj.parameters ?? obj.input ?? obj.data ?? obj.payload;
  if (args && typeof args === "object" && !Array.isArray(args)) {
    const inner = digContent(args as Record<string, unknown>, maxDepth - 1);
    if (inner) return inner;
  }

  return null;
}

function parseJsonWrapper(text: string): ParsedWrapper | null {
  const top = tryJsonParse(text);
  if (!top) return null;

  const args = (top.arguments ?? top.args ?? top.parameters) as Record<string, unknown> | undefined;
  const kind = stringVal(args?.kind ?? top.kind) ?? "text";

  if (kind === "file" && args) {
    const content = stringVal(args.content);
    if (content) {
      return {
        kind: "file",
        title: stringVal(args.title),
        fileName: stringVal(args.file_name ?? args.fileName) ?? stringVal(args.title) ?? "untitled",
        mimeType: stringVal(args.mime_type ?? args.mimeType) ?? "text/plain",
        content,
        prefix: "",
        rawArgs: args,
      };
    }
  }

  if (kind === "preview" && args) {
    return {
      kind: "preview",
      title: stringVal(args.title) ?? "预览",
      fileName: stringVal(args.file_name) ?? stringVal(args.title) ?? "preview.html",
      mimeType: "text/html",
      content: stringVal(args.content) ?? "",
      prefix: "",
      rawArgs: args,
    };
  }

  const content = digContent(top);
  if (content) {
    return {
      kind: "text",
      content: unHtmlify(content),
      prefix: "",
    };
  }

  return null;
}

function tryParseJsonAt(text: string, startPos: number): { obj: Record<string, unknown>; braceIdx: number } | null {
  const braceIdx = text.indexOf("{", startPos);
  if (braceIdx === -1) return null;
  const candidate = text.slice(braceIdx);
  try {
    const obj = JSON.parse(candidate) as Record<string, unknown>;
    return { obj, braceIdx };
  } catch {
    return null;
  }
}

function findEmbeddedWrapper(text: string): ParsedWrapper | null {
  let searchFrom = 0;
  while (true) {
    const braceIdx = text.indexOf("{", searchFrom);
    if (braceIdx === -1) return null;

    const result = tryParseJsonAt(text, searchFrom);
    if (!result) {
      searchFrom = braceIdx + 1;
      continue;
    }

    const args = (result.obj.arguments ?? result.obj.args ?? result.obj.parameters) as Record<string, unknown> | undefined;
    if (!args) {
      searchFrom = result.braceIdx + 1;
      continue;
    }

    const kind = stringVal(args.kind);
    if (kind !== "file" && kind !== "preview") {
      const content = digContent(result.obj);
      if (content) {
        return {
          kind: "text",
          content: unHtmlify(content),
          prefix: text.slice(0, result.braceIdx).trim(),
        };
      }
      searchFrom = result.braceIdx + 1;
      continue;
    }

    const fileContent = stringVal(args.content);
    if (!fileContent) {
      searchFrom = result.braceIdx + 1;
      continue;
    }

    return {
      kind: kind as "file" | "preview",
      title: stringVal(args.title),
      fileName: stringVal(args.file_name ?? args.fileName) ?? stringVal(args.title) ?? "untitled",
      mimeType: stringVal(args.mime_type ?? args.mimeType) ?? (kind === "file" ? "text/markdown" : "text/html"),
      content: fileContent,
      prefix: text.slice(0, result.braceIdx).trim(),
      rawArgs: args,
    };
  }
}

/* ── HTML / Markdown helpers ──────────────────────────────────── */

function unHtmlify(text: string): string {
  return text
    .replace(/<strong\b[^>]*>(.*?)<\/strong>/g, "**$1**")
    .replace(/<b\b[^>]*>(.*?)<\/b>/g, "**$1**")
    .replace(/<em\b[^>]*>(.*?)<\/em>/g, "*$1*")
    .replace(/<i\b[^>]*>(.*?)<\/i>/g, "*$1*")
    .replace(/<code\b[^>]*>(.*?)<\/code>/g, "`$1`")
    .replace(/<pre\b[^>]*>(.*?)<\/pre>/gs, "```\n$1\n```")
    .replace(/<hr\b[^>]*\/?>/gi, "\n---\n")
    .replace(/<br\b[^>]*\/?>/gi, "\n")
    .replace(/<p\b[^>]*>/gi, "\n\n")
    .replace(/<\/p>/gi, "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}

function sanitizeHtml(html: string): string {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, "")
    .replace(/\son\w+\s*=\s*'[^']*'/gi, "")
    .replace(/javascript\s*:/gi, "blocked:");
}

function renderMarkdown(text: string): string {
  try {
    return sanitizeHtml(marked.parse(text) as string);
  } catch {
    return text;
  }
}

/* ── Text parts & inline parsing ──────────────────────────────── */

const CODE_FENCE_RE = /```([\w.+-]*)\n([\s\S]*?)```/g;

interface TextPart {
  type: "text" | "code";
  code?: string;
  language?: string;
  text?: string;
}

function parseTextParts(text: string): TextPart[] {
  const parts: TextPart[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = CODE_FENCE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", text: text.slice(lastIndex, match.index) });
    }
    parts.push({
      type: "code",
      language: match[1]?.trim() || undefined,
      code: match[2] ?? "",
    });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: "text", text: text.slice(lastIndex) });
  }

  return parts.length > 0 ? parts : [{ type: "text", text }];
}

/* ── Inline markdown ──────────────────────────────────────────── */

const INLINE_RE = /(\*\*(.+?)\*\*)|(\*(.+?)\*)|(`([^`]+)`)|(\[([^\]]+)\]\(([^)]+)\))/g;

function renderInline(text: string) {
  const segments: { type: "text" | "bold" | "italic" | "code" | "link"; text: string; href?: string }[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;

  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, m.index) });
    }
    if (m[1]) segments.push({ type: "bold", text: m[2] });
    else if (m[3]) segments.push({ type: "italic", text: m[4] });
    else if (m[5]) segments.push({ type: "code", text: m[6] });
    else if (m[7]) segments.push({ type: "link", text: m[8], href: m[9] });
    lastIndex = m.index + m[0].length;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", text: text.slice(lastIndex) });
  }
  if (segments.length === 0) {
    segments.push({ type: "text", text });
  }

  return segments.map((seg, i) => {
    switch (seg.type) {
      case "bold":
        return <strong key={i} className="font-semibold text-fg">{seg.text}</strong>;
      case "italic":
        return <em key={i} className="italic text-fg/90">{seg.text}</em>;
      case "code":
        return <code key={i} className="px-1 py-[1px] rounded bg-border/50 text-[12px] font-mono text-accent">{seg.text}</code>;
      case "link":
        return (
          <a key={i} href={seg.href} target="_blank" rel="noopener noreferrer"
            className="underline underline-offset-2 text-accent hover:text-accent-hover transition-colors">
            {seg.text}
          </a>
        );
      default:
        return <Fragment key={i}>{seg.text}</Fragment>;
    }
  });
}

/* ── Paragraph / block parsing ────────────────────────────────── */

function isTableRow(line: string): boolean { return /^\|.*\|$/.test(line.trim()); }
function isTableSeparator(line: string): boolean { return /^\|[\s:-]+\|[\s|:-]*$/.test(line.trim()); }

function parseTableRow(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

interface ParaBlock {
  kind: "para" | "ul" | "ol" | "table" | "heading";
  items?: string[];
  text?: string;
  level?: number;
  header?: string[];
  rows?: string[][];
}

function parseParagraphs(text: string): ParaBlock[] {
  const blocks: ParaBlock[] = [];
  const rawLines = text.split("\n");
  let i = 0;

  while (i < rawLines.length) {
    const line = rawLines[i];

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      blocks.push({ kind: "heading", level: headingMatch[1].length, text: headingMatch[2] });
      i++;
      continue;
    }

    const ulMatch = line.match(/^[*-]\s+(.*)$/);
    if (ulMatch) {
      const items: string[] = [ulMatch[1]];
      i++;
      while (i < rawLines.length) {
        const next = rawLines[i].match(/^[*-]\s+(.*)$/);
        if (!next) break;
        items.push(next[1]);
        i++;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }

    const olMatch = line.match(/^\d+[.)]\s+(.*)$/);
    if (olMatch) {
      const items: string[] = [olMatch[1]];
      i++;
      while (i < rawLines.length) {
        const next = rawLines[i].match(/^\d+[.)]\s+(.*)$/);
        if (!next) break;
        items.push(next[1]);
        i++;
      }
      blocks.push({ kind: "ol", items });
      continue;
    }

    if (isTableRow(line) && !isTableSeparator(line)) {
      const headerCells = parseTableRow(line);
      const nextIdx = i + 1;
      if (nextIdx < rawLines.length && isTableSeparator(rawLines[nextIdx])) {
        const rows: string[][] = [];
        let j = nextIdx + 1;
        while (j < rawLines.length && isTableRow(rawLines[j]) && !isTableSeparator(rawLines[j])) {
          rows.push(parseTableRow(rawLines[j]));
          j++;
        }
        blocks.push({ kind: "table", header: headerCells, rows });
        i = j;
        continue;
      }
    }

    if (/^---+\s*$/.test(line) || /^\*\*\*+\s*$/.test(line)) {
      blocks.push({ kind: "para", text: "---" });
      i++;
      continue;
    }

    if (line.trim() === "") { i++; continue; }

    const paraLines: string[] = [line];
    i++;
    while (i < rawLines.length && rawLines[i].trim() !== "") {
      paraLines.push(rawLines[i]);
      i++;
    }
    blocks.push({ kind: "para", text: paraLines.join("\n") });
  }

  return blocks;
}

/* ── Rich text render body ────────────────────────────────────── */

function RichTextBody({ text: rawText }: { text: string }) {
  const parts = useMemo(() => parseTextParts(rawText), [rawText]);

  return (
    <div className="text-sm leading-relaxed space-y-1">
      {parts.map((part, pi) =>
        part.type === "code" ? (
          <CodeBlock key={`code-${pi}`} code={part.code ?? ""} language={part.language} />
        ) : (
          <div key={`text-${pi}`} className="whitespace-pre-wrap break-words">
            {parseParagraphs(part.text ?? "").map((block, bi) => {
              if (block.kind === "table" && block.header && block.rows) {
                return (
                  <div key={bi} className="my-2 overflow-x-auto">
                    <table className="w-full border-collapse text-sm">
                      <thead>
                        <tr className="border-b border-border">
                          {block.header.map((h, hi) => (
                            <th key={hi} className="px-3 py-1.5 text-left font-semibold text-fg">{renderInline(h)}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {block.rows.map((row, ri) => (
                          <tr key={ri} className="border-b border-border/50">
                            {row.map((cell, ci) => (
                              <td key={ci} className="px-3 py-1.5 text-fg/90">{renderInline(cell)}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              }
              if (block.kind === "heading") {
                const Tag = `h${Math.min(block.level ?? 2, 6)}` as keyof JSX.IntrinsicElements;
                const sz = (block.level ?? 2) === 1 ? "text-lg font-bold" : (block.level ?? 2) === 2 ? "text-base font-semibold" : "text-sm font-semibold";
                return React.createElement(Tag, { key: bi, className: `${sz} text-fg mt-3 mb-1 first:mt-0` }, renderInline(block.text ?? ""));
              }
              if (block.kind === "ul" && block.items) {
                return (
                  <ul key={bi} className="list-disc list-inside space-y-0.5 my-1">
                    {block.items.map((item, ii) => <li key={ii}>{renderInline(item)}</li>)}
                  </ul>
                );
              }
              if (block.kind === "ol" && block.items) {
                return (
                  <ol key={bi} className="list-decimal list-inside space-y-0.5 my-1">
                    {block.items.map((item, ii) => <li key={ii}>{renderInline(item)}</li>)}
                  </ol>
                );
              }
              if (block.text === "---") return <hr key={bi} className="my-2 border-border/50" />;
              return <p key={bi} className="min-h-[1.2em]">{renderInline(block.text ?? "")}</p>;
            })}
          </div>
        ),
      )}
    </div>
  );
}

/* ── File Card (for kind="file" wrappers) ─────────────────────── */

const FILE_ICON = (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
    <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    <line x1="8" y1="7" x2="16" y2="7" /><line x1="8" y1="11" x2="14" y2="11" /><line x1="8" y1="15" x2="16" y2="15" />
  </svg>
);

function FileCardView({ wrapper }: { wrapper: ParsedWrapper }) {
  const html = useMemo(() => renderMarkdown(wrapper.content), [wrapper.content]);

  return (
    <div className="text-sm leading-relaxed space-y-2">
      {wrapper.prefix && <p className="whitespace-pre-wrap break-words">{wrapper.prefix}</p>}
      <div className="rounded-xl border border-border bg-bg overflow-hidden shadow-[0_4px_16px_rgba(0,0,0,0.1)]">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border bg-bg/60">
          <span className="text-purple-400">{FILE_ICON}</span>
          <span className="text-xs font-medium text-fg truncate">{wrapper.fileName}</span>
          <span className="text-[10px] text-muted">{wrapper.mimeType}</span>
          {wrapper.title && wrapper.title !== wrapper.fileName && (
            <span className="text-[10px] text-muted/60 ml-auto truncate max-w-[40%]">{wrapper.title}</span>
          )}
        </div>
        <div className="max-h-[500px] overflow-auto">
          <div
            className="px-4 py-3 text-[14px] leading-relaxed text-fg markdown-body"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        </div>
      </div>
    </div>
  );
}

/* ── Main component ───────────────────────────────────────────── */

function hasMultiCodeFences(text: string): boolean {
  const matches = text.match(/```/g);
  return matches !== null && matches.length >= 6;
}

export const TextBubble = React.memo(function TextBubble({ text }: Props) {
  const wrapper = useMemo(() => {
    const top = parseJsonWrapper(text);
    if (top) return top;
    return findEmbeddedWrapper(text);
  }, [text]);

  const multiFiles = useMemo(() => {
    if (wrapper?.kind === "file") return null;
    if (!hasMultiCodeFences(text)) return null;
    const files = extractFilesFromText(text);
    if (files.length >= 3) return files;
    return null;
  }, [text, wrapper]);

  const treePrefix = useMemo(() => {
    if (!multiFiles) return null;
    const firstFenceIdx = text.indexOf("```");
    if (firstFenceIdx <= 0) return null;
    const prefix = text.slice(0, firstFenceIdx).trim();
    if (!prefix) return null;
    const treeLines = prefix.split("\n").filter((l) => l.trim());
    const treeChars = treeLines.join("").length;
    const boxChars = (prefix.match(/[│├└─┌┐┘┤┬┴┼]/g) || []).length;
    return boxChars >= 3 && treeChars < 3000 ? prefix : null;
  }, [text, multiFiles]);

  if (multiFiles) {
    return (
      <div className="text-sm leading-relaxed space-y-2">
        {treePrefix && (
          <pre className="text-[11px] text-fg/80 whitespace-pre font-mono leading-tight bg-bg/50 rounded-lg p-3 border border-border overflow-x-auto">
            {treePrefix}
          </pre>
        )}
        <FilePreviewPane files={multiFiles} />
      </div>
    );
  }

  if (wrapper?.kind === "file") {
    return <FileCardView wrapper={wrapper} />;
  }

  if (wrapper?.kind === "text" && wrapper.content) {
    return <RichTextBody text={wrapper.content} />;
  }

  if (wrapper && wrapper.prefix) {
    return <RichTextBody text={wrapper.prefix} />;
  }

  return <RichTextBody text={text} />;
});
