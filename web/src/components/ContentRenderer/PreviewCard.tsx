import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchArtifactContent } from "../../api/client";
import { formatHtml } from "../../formatHtml";

interface Props {
  artifactId: string;
  title: string;
  mimeType: string;
  fileSize: number;
  url?: string;
  previewUrl?: string;
  onEdit?: (artifactId: string) => void;
}

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function safeTitle(title: string): string {
  return title.replace(/[<>&"']/g, "");
}

function fallbackHtml(title: string): string {
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${safeTitle(title)}</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#10131a;color:#eef2ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}.card{max-width:560px;padding:28px;border:1px solid rgba(255,255,255,.12);border-radius:16px;background:#171b24;box-shadow:0 24px 80px rgba(0,0,0,.35)}h1{margin:0 0 10px;font-size:22px}p{margin:0;color:#aab3c5;line-height:1.8}</style></head><body><main class="card"><h1>预览暂不可用</h1><p>该产物没有返回可直接渲染的完整 HTML。你仍可以打开编辑器查看和修复源码。</p></main></body></html>`;
}

function highlightHtml(code: string): string {
  return code
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/(&lt;!--[\s\S]*?--&gt;|&lt;\/?[a-zA-Z][\w:.-]*|\/?&gt;)/g, '<span class="syn-tag">$1</span>')
    .replace(/([\w:-]+)(\s*=\s*)(&quot;[^&]*&quot;|'[^']*'|[^\s&]+)/g, '<span class="syn-attr">$1</span>$2<span class="syn-string">$3</span>');
}

const CODE_STYLE = ".syn-tag{color:#f0abfc}.syn-attr{color:#93c5fd}.syn-string{color:#86efac}";

export function PreviewCard({ artifactId, title, mimeType, fileSize, url, previewUrl, onEdit }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [mode, setMode] = useState<"preview" | "code">("preview");
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const isHtml = mimeType.toLowerCase().includes("html");
  const isImage = mimeType.startsWith("image/");
  const resolvedPreviewUrl = previewUrl || (artifactId ? `/preview/${encodeURIComponent(artifactId)}` : "");
  const sourceUrl = url || (artifactId ? `/api/artifacts/${encodeURIComponent(artifactId)}/content` : "");
  const html = content || fallbackHtml(title);
  const highlighted = useMemo(() => highlightHtml(content || ""), [content]);

  const loadContent = useCallback(() => {
    if (!artifactId || !isHtml || content !== null || loading) return;
    setLoading(true);
    setError(null);
    fetchArtifactContent(artifactId)
      .then((value) => {
        const formatted = formatHtml(value.trim());
        setContent(formatted || fallbackHtml(title));
      })
      .catch((err) => {
        setContent(fallbackHtml(title));
        setError(err instanceof Error ? err.message : "预览内容加载失败");
      })
      .finally(() => setLoading(false));
  }, [artifactId, content, isHtml, loading, title]);

  useEffect(() => {
    if (expanded || fullscreen || mode === "code") loadContent();
  }, [expanded, fullscreen, mode, loadContent]);

  function copyCode() {
    if (!content) return;
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    }).catch(() => {});
  }

  function sendToChat() {
    if (!content) return;
    window.dispatchEvent(new CustomEvent("agenthub:code-to-chat", { detail: { code: content, title } }));
  }

  const previewFrame = (
    <div className="relative h-full min-h-[420px] bg-bg">
      {loading && (
        <div className="absolute inset-0 z-10 grid place-items-center bg-bg/80">
          <div className="rounded-full border border-border bg-panel px-4 py-2 text-xs text-muted">加载预览中...</div>
        </div>
      )}
      {isImage ? (
        <div className="grid h-full place-items-center p-4">
          <img src={sourceUrl} alt={title} className="max-h-full max-w-full rounded object-contain" />
        </div>
      ) : mode === "code" && isHtml ? (
        <pre
          className="h-full overflow-auto p-4 text-[11px] leading-relaxed text-fg"
          dangerouslySetInnerHTML={{ __html: highlighted || "暂无源码" }}
        />
      ) : (
        <iframe
          title={title}
          src={isHtml ? undefined : resolvedPreviewUrl || sourceUrl}
          srcDoc={isHtml ? html : undefined}
          className="h-full w-full border-0 bg-white"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
        />
      )}
    </div>
  );

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-border bg-panel shadow-[0_12px_34px_rgba(0,0,0,0.18)]">
      <style>{CODE_STYLE}</style>
      <button
        type="button"
        onClick={() => {
          setExpanded((v) => !v);
          setMode("preview");
        }}
        className="flex w-full items-center justify-between gap-3 border-b border-border bg-bg/40 px-3 py-2.5 text-left"
      >
        <div className="flex min-w-0 items-center gap-2.5">
          <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-accent/20 bg-accent/10 text-accent">HTML</div>
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-fg">{title}</div>
            <div className="mt-0.5 text-[10px] text-muted">
              {isHtml ? "网页预览" : mimeType} · {formatSize(fileSize)}
              {error ? ` · ${error}` : ""}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {onEdit && artifactId && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                onEdit(artifactId);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onEdit(artifactId);
                }
              }}
              className="rounded-md border border-border px-2 py-1 text-[11px] text-muted hover:text-accent"
            >
              编辑
            </span>
          )}
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation();
              setFullscreen(true);
              setMode("preview");
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                setFullscreen(true);
                setMode("preview");
              }
            }}
            className="rounded-md border border-accent/30 px-2 py-1 text-[11px] text-accent hover:bg-accent/10"
          >
            全屏
          </span>
          <span className="rounded-md border border-border px-2 py-1 text-[11px] text-muted">{expanded ? "收起" : "展开"}</span>
        </div>
      </button>

      {expanded && (
        <div>
          {isHtml && (
            <div className="flex items-center border-b border-border bg-bg/60">
              <button type="button" onClick={() => setMode("preview")} className={`px-3 py-1.5 text-[11px] ${mode === "preview" ? "text-accent" : "text-muted"}`}>
                预览
              </button>
              <button type="button" onClick={() => setMode("code")} className={`px-3 py-1.5 text-[11px] ${mode === "code" ? "text-accent" : "text-muted"}`}>
                源码
              </button>
              {mode === "code" && (
                <div className="ml-auto flex gap-1 pr-2">
                  <button type="button" onClick={sendToChat} className="rounded px-2 py-1 text-[10px] text-sky-300 hover:bg-sky-500/10">
                    在聊天中修改
                  </button>
                  <button type="button" onClick={copyCode} className="rounded px-2 py-1 text-[10px] text-muted hover:text-fg">
                    {copied ? "已复制" : "复制源码"}
                  </button>
                </div>
              )}
            </div>
          )}
          <div className="h-[520px]">{previewFrame}</div>
        </div>
      )}

      {fullscreen && (
        <div className="fixed inset-0 z-50 flex flex-col bg-bg">
          <div className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-panel px-4">
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-fg">{title}</div>
              <div className="text-[10px] text-muted">全屏预览 · {formatSize(fileSize)}</div>
            </div>
            <div className="flex items-center gap-2">
              {isHtml && (
                <>
                  <button type="button" onClick={() => setMode("preview")} className={`rounded border px-2 py-1 text-xs ${mode === "preview" ? "border-accent text-accent" : "border-border text-muted"}`}>
                    预览
                  </button>
                  <button type="button" onClick={() => setMode("code")} className={`rounded border px-2 py-1 text-xs ${mode === "code" ? "border-accent text-accent" : "border-border text-muted"}`}>
                    源码
                  </button>
                </>
              )}
              {onEdit && artifactId && (
                <button type="button" onClick={() => onEdit(artifactId)} className="rounded bg-accent px-3 py-1.5 text-xs text-white">
                  编辑代码
                </button>
              )}
              <button type="button" onClick={() => setFullscreen(false)} className="rounded border border-border px-3 py-1.5 text-xs text-muted hover:text-fg">
                关闭
              </button>
            </div>
          </div>
          <div className="min-h-0 flex-1">{previewFrame}</div>
        </div>
      )}
    </div>
  );
}
