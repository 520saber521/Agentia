import { useCallback, useEffect, useState } from "react";
import { marked } from "marked";
import { CodeBlock } from "./CodeBlock";

marked.setOptions({ breaks: true, gfm: true });

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

interface Props {
  fileName: string;
  mimeType: string;
  fileSize: number;
  downloadUrl: string;
}

function formatSize(bytes: number): string {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function shortMime(mimeType: string): string {
  const [family, subtype] = mimeType.split("/");
  if (!subtype) return mimeType;
  return `${family}/${subtype.split(";")[0]}`;
}

function langFromMime(mime: string, fileName?: string): string {
  const ext = fileName?.split(".").pop()?.toLowerCase();
  const extMap: Record<string, string> = {
    py: "python", js: "javascript", ts: "typescript",
    tsx: "tsx", jsx: "jsx", html: "html", css: "css",
    json: "json", yaml: "yaml", yml: "yaml", md: "markdown",
    sql: "sql", sh: "bash", rs: "rust", go: "go",
  };
  if (ext && extMap[ext]) return extMap[ext];
  if (mime.includes("python")) return "python";
  if (mime.includes("javascript") || mime.includes("ecmascript")) return "javascript";
  if (mime.includes("typescript")) return "typescript";
  if (mime.includes("html")) return "html";
  if (mime.includes("css")) return "css";
  if (mime.includes("json")) return "json";
  if (mime.includes("yaml")) return "yaml";
  if (mime.includes("markdown")) return "markdown";
  if (mime.includes("sql")) return "sql";
  return ext ?? "text";
}

const isImage = (mime: string) => mime.startsWith("image/");
const isText = (mime: string) =>
  mime.startsWith("text/") ||
  ["application/json", "application/xml", "application/javascript", "application/typescript"].includes(mime);
const isMarkdown = (mime: string) =>
  mime === "text/markdown" || mime === "text/x-markdown";
const isCodeLike = (mime: string) =>
  mime.startsWith("text/x-") ||
  ["text/javascript", "text/typescript", "text/css", "text/html", "application/json", "text/yaml",
   "application/javascript", "application/typescript"].includes(mime);

const PREVIEW_CHAR_LIMIT = 1200;

function unescapeGeneratedText(text: string): string {
  return text
    .replace(/\\r\\n/g, "\n")
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'");
}

function extractWrappedContent(text: string): string {
  let trimmed = text.trim();
  if (trimmed.startsWith("```tool_call")) {
    trimmed = trimmed.replace(/^```tool_call\s*/, "").replace(/\s*```$/, "").trim();
  }
  if (!trimmed.startsWith("{")) return unescapeGeneratedText(text);

  try {
    const parsed = JSON.parse(trimmed);

    function dig(value: unknown): string | null {
      if (typeof value === "string") return value.trim() ? value : null;
      if (!value || typeof value !== "object") return null;
      const obj = value as Record<string, unknown>;
      for (const key of ["content", "text", "result"]) {
        if (typeof obj[key] === "string" && String(obj[key]).trim()) return String(obj[key]);
      }
      for (const key of ["arguments", "args", "parameters", "input", "data", "payload"]) {
        const inner = dig(obj[key]);
        if (inner) return inner;
      }
      return null;
    }

    return unescapeGeneratedText(dig(parsed) ?? text);
  } catch {
    return unescapeGeneratedText(text);
  }
}

export function FileCard({ fileName, mimeType, fileSize, downloadUrl }: Props) {
  const [imgError, setImgError] = useState(false);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textLoading, setTextLoading] = useState(false);
  const [textError, setTextError] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [viewMode, setViewMode] = useState<"preview" | "raw">("preview");

  useEffect(() => {
    if (!isText(mimeType)) return;
    let cancelled = false;
    setTextLoading(true);
    setTextError(false);
    fetch(downloadUrl)
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed");
        const data = await res.json();
        if (!cancelled) {
          const raw = typeof data.content === "string" ? data.content : String(data.content ?? "");
          setTextContent(extractWrappedContent(raw));
        }
      })
      .catch(() => {
        if (!cancelled) setTextError(true);
      })
      .finally(() => {
        if (!cancelled) setTextLoading(false);
      });
    return () => { cancelled = true; };
  }, [mimeType, downloadUrl]);

  const showExpand = textContent !== null && textContent.length > PREVIEW_CHAR_LIMIT;
  const displayText = showExpand && !expanded
    ? textContent.slice(0, PREVIEW_CHAR_LIMIT) + "\n…"
    : textContent ?? "";
  const lang = langFromMime(mimeType, fileName);

  const toggleExpand = useCallback(() => setExpanded((v) => !v), []);

  // File icon color
  const iconColor = isImage(mimeType)
    ? "bg-rose-500/10 border-rose-500/20 text-rose-400"
    : isMarkdown(mimeType)
      ? "bg-purple-500/10 border-purple-500/20 text-purple-400"
      : isCodeLike(mimeType)
        ? "bg-cyan-500/10 border-cyan-500/20 text-cyan-400"
        : "bg-accent/10 border-accent/20 text-accent";

  const fileIcon = isImage(mimeType) ? (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
    </svg>
  ) : isMarkdown(mimeType) ? (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
      <line x1="8" y1="7" x2="16" y2="7" /><line x1="8" y1="11" x2="14" y2="11" /><line x1="8" y1="15" x2="16" y2="15" />
    </svg>
  ) : isCodeLike(mimeType) ? (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
    </svg>
  ) : (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" />
    </svg>
  );

  return (
    <div className="rounded-xl border border-border bg-bg overflow-hidden my-2 shadow-[0_8px_24px_rgba(0,0,0,0.14)] group">
      {/* Image preview */}
      {isImage(mimeType) && !imgError && (
        <div className="border-b border-border bg-[#0d0d0d] p-2 flex items-center justify-center min-h-[80px] max-h-[360px] overflow-hidden">
          <img
            src={downloadUrl}
            alt={fileName}
            className="max-w-full max-h-[340px] rounded-lg object-contain cursor-pointer transition-transform hover:scale-[1.02]"
            onError={() => setImgError(true)}
            onClick={() => window.open(downloadUrl, "_blank")}
          />
        </div>
      )}

      {/* Text/code preview — enhanced with syntax highlighting */}
      {isText(mimeType) && (
        <div className="border-b border-border">
          {textLoading && (
            <div className="px-4 py-6 text-center text-xs text-muted animate-pulse">加载预览中...</div>
          )}
          {textError && (
            <div className="px-4 py-4 text-center text-xs text-rose-400/70">预览加载失败</div>
          )}
          {textContent !== null && !textError && (
            <div>
              {/* Mode toggle for markdown */}
              {isMarkdown(mimeType) && (
                <div className="flex items-center border-b border-border bg-bg/60 px-2">
                  <button
                    type="button"
                    onClick={() => setViewMode("preview")}
                    className={`px-2 py-1 text-[10px] ${viewMode === "preview" ? "text-accent" : "text-muted"}`}
                  >
                    预览
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("raw")}
                    className={`px-2 py-1 text-[10px] ${viewMode === "raw" ? "text-accent" : "text-muted"}`}
                  >
                    源码
                  </button>
                </div>
              )}

              {/* Markdown rendered preview */}
              {isMarkdown(mimeType) && viewMode === "preview" && (
                <div className="max-h-[420px] overflow-auto">
                  <div
                    className="px-4 py-3 text-[14px] leading-relaxed text-fg markdown-body"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(displayText) }}
                  />
                  {showExpand && (
                    <button type="button" onClick={toggleExpand}
                      className="w-full border-t border-border px-3 py-1.5 text-[11px] text-accent hover:bg-accent/5 transition-colors">
                      {expanded ? "收起预览" : `展开全部 (${formatSize(textContent.length)} 字符)`}
                    </button>
                  )}
                </div>
              )}

              {/* Code / raw text preview — use CodeBlock for syntax highlighting */}
              {(!isMarkdown(mimeType) || viewMode === "raw") && (
                <div className="max-h-[420px] overflow-auto">
                  {isCodeLike(mimeType) || isMarkdown(mimeType) ? (
                    <CodeBlock code={displayText} language={lang} title={fileName} mini maxHeight={420} />
                  ) : (
                    <pre className="!m-0 !bg-bg px-4 py-3 font-mono text-[12px] leading-relaxed text-fg/90 whitespace-pre">
                      <code>{displayText}</code>
                    </pre>
                  )}
                  {showExpand && (
                    <button type="button" onClick={toggleExpand}
                      className="w-full border-t border-border px-3 py-1.5 text-[11px] text-accent hover:bg-accent/5 transition-colors">
                      {expanded ? "收起预览" : `展开全部 (${formatSize(textContent.length)} 字符)`}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* File info bar */}
      <div className="flex items-center gap-3 p-3">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border ${iconColor}`}>
          {fileIcon}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">{fileName}</div>
          <div className="text-[10px] text-muted mt-0.5 flex items-center gap-2 min-w-0">
            <span className="truncate">{shortMime(mimeType)}</span>
            <span aria-hidden="true">·</span>
            <span className="shrink-0">{formatSize(fileSize)}</span>
            {textContent !== null && !textError && (
              <>
                <span aria-hidden="true">·</span>
                <span className="shrink-0">{formatSize(textContent.length)} 字符</span>
              </>
            )}
          </div>
        </div>
        <a
          href={downloadUrl}
          download={fileName}
          className="shrink-0 rounded-md border border-accent/30 px-2.5 py-1 text-[11px] text-accent hover:bg-accent/10 transition-colors"
        >
          下载
        </a>
      </div>
    </div>
  );
}
