import { useCallback, useEffect, useMemo, useState } from "react";
import { CodeBlock } from "./CodeBlock";

// ── Types ──

export interface PreviewFile {
  name: string;
  path?: string;
  language?: string;
  mimeType?: string;
  content?: string;
  size?: number;
  /** URL to fetch content from */
  contentUrl?: string;
}

interface Props {
  files: PreviewFile[];
  /** Initial file index to show */
  activeIndex?: number;
  /** Show in compact mode (no split pane, just tabs + preview) */
  compact?: boolean;
}

// ── Helpers ──

function extLang(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    py: "python", js: "javascript", ts: "typescript",
    jsx: "jsx", tsx: "tsx", html: "html", css: "css",
    json: "json", yaml: "yaml", yml: "yaml", md: "markdown",
    sql: "sql", sh: "bash", bat: "bash", ps1: "bash",
    rs: "rust", go: "go", java: "java", c: "c", cpp: "cpp",
    h: "c", hpp: "cpp", txt: "text", xml: "xml", svg: "xml",
    toml: "toml", ini: "text", cfg: "text", env: "text",
  };
  return map[ext] ?? "text";
}

function isImage(mime?: string, name?: string): boolean {
  if (mime?.startsWith("image/")) return true;
  const ext = name?.split(".").pop()?.toLowerCase();
  return ext ? ["png", "jpg", "jpeg", "gif", "svg", "ico", "webp"].includes(ext) : false;
}

function isMarkdown(mime?: string, name?: string): boolean {
  if (mime === "text/markdown" || mime === "text/x-markdown") return true;
  return name?.endsWith(".md") ?? false;
}

function formatSize(bytes: number): string {
  if (!bytes || bytes === 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(name: string, mimeType?: string): string {
  if (isImage(mimeType, name)) return "img";
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const codeExts = new Set([
    "py", "js", "ts", "tsx", "jsx", "html", "css", "json", "md", "txt",
    "yaml", "yml", "xml", "sql", "sh", "bat", "ps1", "toml", "ini", "cfg",
    "env", "csv", "log", "rs", "go", "java", "c", "cpp", "h", "rb", "php",
    "swift", "kt", "scala", "r", "lua", "pl", "dart", "vue", "svelte",
  ]);
  if (codeExts.has(ext)) return "code";
  if (["md", "txt", "rst"].includes(ext)) return "doc";
  if (["zip", "tar", "gz", "rar", "7z"].includes(ext)) return "archive";
  return "file";
}

// ── File Icon Component ──

function FileIcon({ name, mimeType, size }: { name: string; mimeType?: string; size?: number }) {
  const kind = fileIcon(name, mimeType);

  const colors: Record<string, string> = {
    img: "bg-rose-500/10 border-rose-500/20 text-rose-400",
    code: "bg-cyan-500/10 border-cyan-500/20 text-cyan-400",
    doc: "bg-purple-500/10 border-purple-500/20 text-purple-400",
    archive: "bg-amber-500/10 border-amber-500/20 text-amber-400",
    file: "bg-accent/10 border-accent/20 text-accent",
  };

  const color = colors[kind] ?? colors.file;

  return (
    <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border ${color} text-xs font-bold`}>
      {kind === "img" && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
        </svg>
      )}
      {kind === "code" && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
        </svg>
      )}
      {kind === "doc" && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
          <line x1="8" y1="7" x2="16" y2="7" /><line x1="8" y1="11" x2="14" y2="11" />
        </svg>
      )}
      {kind === "archive" && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 8v13H3V8" /><path d="M1 3h22v5H1z" /><line x1="10" y1="12" x2="14" y2="12" />
        </svg>
      )}
      {kind === "file" && (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" />
        </svg>
      )}
    </div>
  );
}

// ── File Preview Content ──

function FilePreviewContent({ file }: { file: PreviewFile }) {
  const [fetchedContent, setFetchedContent] = useState<string | null>(null);
  const [fetchError, setFetchError] = useState(false);
  const [fetching, setFetching] = useState(false);

  const content = file.content ?? fetchedContent;
  const mime = file.mimeType ?? "";
  const lang = file.language ?? extLang(file.name);

  useEffect(() => {
    if (file.content !== undefined || !file.contentUrl) return;
    let cancelled = false;
    setFetching(true);
    setFetchError(false);
    fetch(file.contentUrl)
      .then(async (res) => {
        if (!res.ok) throw new Error("fetch failed");
        const data = await res.json();
        if (!cancelled) setFetchedContent(typeof data.content === "string" ? data.content : String(data.content ?? ""));
      })
      .catch(() => { if (!cancelled) setFetchError(true); })
      .finally(() => { if (!cancelled) setFetching(false); });
    return () => { cancelled = true; };
  }, [file.content, file.contentUrl]);

  // Image preview
  if (isImage(file.mimeType, file.name)) {
    const imgSrc = file.contentUrl ?? (content ?? "");
    return (
      <div className="grid h-full place-items-center p-4 bg-[#0d0d0d]">
        <img
          src={imgSrc}
          alt={file.name}
          className="max-h-full max-w-full rounded object-contain"
          onError={(e) => {
            (e.target as HTMLImageElement).style.display = "none";
          }}
        />
      </div>
    );
  }

  // Markdown preview
  if (isMarkdown(file.mimeType, file.name) && content) {
    return (
      <div className="h-full overflow-auto p-4">
        <div
          className="prose prose-sm prose-invert max-w-none text-[13px] leading-relaxed"
          dangerouslySetInnerHTML={{ __html: content }}
        />
      </div>
    );
  }

  // Loading / Error states for code
  if (fetching) {
    return <div className="grid h-full place-items-center text-xs text-muted animate-pulse">加载中...</div>;
  }
  if (fetchError) {
    return <div className="grid h-full place-items-center text-xs text-rose-400">加载失败</div>;
  }
  if (content === undefined || content === null) {
    return <div className="grid h-full place-items-center text-xs text-muted">无法预览此文件类型</div>;
  }

  // Code preview
  return (
    <div className="h-full overflow-auto">
      <CodeBlock code={content} language={lang} title={file.name} mini />
    </div>
  );
}

// ── Main Component ──

export function FilePreviewPane({ files, activeIndex = 0, compact }: Props) {
  const [active, setActive] = useState(activeIndex);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => { setActive(activeIndex); }, [activeIndex]);

  const current = files[active];
  if (!files.length) return null;

  if (compact && files.length === 1) {
    return (
      <div className="rounded-xl border border-border bg-bg overflow-hidden my-2 shadow-[0_10px_30px_rgba(0,0,0,0.18)]">
        <div className="flex items-center gap-2 px-3 py-2 bg-panel border-b border-border">
          <FileIcon name={files[0].name} mimeType={files[0].mimeType} />
          <span className="text-xs font-medium text-fg truncate">{files[0].name}</span>
          {files[0].size ? <span className="text-[10px] text-muted">{formatSize(files[0].size)}</span> : null}
        </div>
        <div className="h-[420px]">
          <FilePreviewContent file={files[0]} />
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-bg overflow-hidden my-2 shadow-[0_12px_34px_rgba(0,0,0,0.18)]">
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-3 border-b border-border bg-bg/40 px-3 py-2.5 text-left"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <FileIcon name={current.name} mimeType={current.mimeType} />
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-fg">{current.name}</div>
            <div className="mt-0.5 text-[10px] text-muted">
              {files.length} 个文件
              {current.language ? ` · ${current.language}` : ""}
              {current.size ? ` · ${formatSize(current.size)}` : ""}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <span className="rounded-md border border-border px-2 py-1 text-[11px] text-muted">
            {expanded ? "收起" : "展开"}
          </span>
        </div>
      </button>

      {expanded && (
        <>
          {/* File tabs */}
          {files.length > 1 && (
            <div className="flex items-center border-b border-border bg-bg/60 overflow-x-auto">
              {files.map((f, i) => (
                <button
                  key={f.path ?? f.name}
                  type="button"
                  onClick={() => setActive(i)}
                  className={`flex items-center gap-1.5 shrink-0 px-3 py-1.5 text-[11px] border-r border-border transition-colors ${
                    i === active
                      ? "bg-bg text-fg border-b-2 border-b-accent"
                      : "text-muted hover:text-fg hover:bg-bg/50"
                  }`}
                >
                  <FileIcon name={f.name} mimeType={f.mimeType} />
                  <span className="max-w-[120px] truncate">{f.name}</span>
                </button>
              ))}
            </div>
          )}

          {/* Preview area — split layout */}
          <div className="flex h-[480px]">
            {/* File list sidebar (only when multiple files) */}
            {files.length > 1 && (
              <div className="w-[180px] shrink-0 border-r border-border bg-bg/40 overflow-y-auto">
                {files.map((f, i) => (
                  <button
                    key={f.path ?? f.name}
                    type="button"
                    onClick={() => setActive(i)}
                    className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors ${
                      i === active
                        ? "bg-accent/10 text-fg border-l-2 border-l-accent"
                        : "text-muted hover:bg-bg/60 hover:text-fg border-l-2 border-l-transparent"
                    }`}
                  >
                    <span className="shrink-0 text-[10px] opacity-60">
                      {isImage(f.mimeType, f.name) ? "🖼" : isMarkdown(f.mimeType, f.name) ? "📝" : "📄"}
                    </span>
                    <span className="truncate">{f.name}</span>
                    {f.size ? <span className="ml-auto shrink-0 text-[10px] text-muted/60">{formatSize(f.size)}</span> : null}
                  </button>
                ))}
              </div>
            )}

            {/* Preview pane */}
            <div className="flex-1 min-w-0">
              <FilePreviewContent file={current} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// ── Builder: extract PreviewFile[] from agent text ──

/** Parse code fences from agent text into PreviewFile objects. */
export function extractFilesFromText(text: string): PreviewFile[] {
  const files: PreviewFile[] = [];
  const fenceRe = /```([\w.+-]*)\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;
  let unnamedIdx = 0;

  while ((match = fenceRe.exec(text)) !== null) {
    const lang = match[1]?.trim() || undefined;
    const code = match[2] ?? "";
    // Try to extract filename from first line comment
    const firstLine = code.split("\n")[0]?.trim() ?? "";
    const nameMatch = firstLine.match(/^(?:\/\/|#)\s*(.+\.\w+)\s*$/);
    const name = nameMatch
      ? nameMatch[1]
      : lang
        ? `untitled_${unnamedIdx++}.${lang}`
        : `untitled_${unnamedIdx++}.txt`;

    files.push({
      name,
      language: lang,
      content: code,
      mimeType: lang === "html" ? "text/html"
        : lang === "css" ? "text/css"
        : lang === "json" ? "application/json"
        : lang === "md" ? "text/markdown"
        : "text/plain",
    });
  }
  return files;
}
