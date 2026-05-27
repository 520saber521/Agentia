import { useEffect, useMemo, useState } from "react";

import { fetchArtifactContent } from "../../api/client";

interface Props {
  artifactId: string;
  title: string;
  mimeType: string;
  fileSize: number;
  url?: string;
  previewUrl?: string;
  onEdit?: (artifactId: string) => void;
  onFullscreen?: (type: "code" | "preview", artifactId: string) => void;
}

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function detectPreviewType(mimeType: string, title: string): "html" | "ppt" | "document" | "unknown" {
  const t = mimeType.toLowerCase();
  if (t.includes("html")) return "html";
  if (t.includes("presentation") || t.includes("powerpoint") || title.toLowerCase().endsWith(".pptx") || title.toLowerCase().endsWith(".ppt"))
    return "ppt";
  if (t.includes("markdown") || t.includes("text/") || title.match(/\.(md|markdown|txt|csv|log)$/i))
    return "document";
  return "unknown";
}

function PreviewIcon({ type }: { type: "html" | "ppt" | "document" | "unknown" }) {
  switch (type) {
    case "html":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M8 4v16" /><path d="M3 9h18" />
        </svg>
      );
    case "ppt":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="10" cy="12" r="2" /><path d="M15 10l4 4-4 4" />
        </svg>
      );
    case "document":
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M6 22h12a2 2 0 002-2V8l-6-6H6a2 2 0 00-2 2v16a2 2 0 002 2z" />
          <path d="M14 2v6h6" /><path d="M8 13h8" /><path d="M8 17h5" />
        </svg>
      );
    default:
      return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="4" width="18" height="16" rx="2" /><path d="M8 4v16" /><path d="M3 9h18" />
        </svg>
      );
  }
}

export function PreviewCard({ artifactId, title, mimeType, fileSize, url, previewUrl, onEdit, onFullscreen }: Props) {
  const [showIframe, setShowIframe] = useState(false);
  const [iframeError, setIframeError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const [inlineHtml, setInlineHtml] = useState<string | null>(null);
  const [loadingInlineHtml, setLoadingInlineHtml] = useState(false);
  const [inlineHtmlError, setInlineHtmlError] = useState<string | null>(null);

  const previewType = detectPreviewType(mimeType, title);
  const viewerUrl = artifactId ? `/preview/${encodeURIComponent(artifactId)}/viewer` : "";
  const resolvedPreviewUrl = previewUrl || (artifactId ? `/preview/${encodeURIComponent(artifactId)}` : "");
  const sourceUrl = url || (artifactId ? `/api/artifacts/${encodeURIComponent(artifactId)}/content` : "");
  const isViewerSupported = previewType !== "unknown";

  const fallbackHtml = useMemo(
    () => {
      const safeTitle = title.replace(/[<>&"']/g, "");
      return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${safeTitle}</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f7f7;color:#222;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}.card{max-width:520px;padding:28px;border-radius:22px;background:white;box-shadow:0 20px 60px rgba(0,0,0,.12)}h1{margin:0 0 10px;font-size:24px}p{margin:0;color:#666;line-height:1.7}</style></head><body><main class="card"><h1>预览暂不可用</h1><p>当前产物没有返回可直接渲染的 HTML，已保留编辑和全屏入口。</p></main></body></html>`;
    },
    [title],
  );
  const iframeHtml = inlineHtml || fallbackHtml;

  const iframeSrc = previewType === "html"
    ? undefined
    : isViewerSupported
      ? viewerUrl
      : resolvedPreviewUrl || sourceUrl;

  const iframeSrcDoc = previewType === "html" ? iframeHtml : undefined;

  useEffect(() => {
    if (!showIframe || !artifactId) return;
    // Only fetch inline content for HTML previews
    if (previewType !== "html") return;

    let cancelled = false;
    setLoadingInlineHtml(true);
    setInlineHtmlError(null);
    fetchArtifactContent(artifactId)
      .then((content) => {
        if (cancelled) return;
        setInlineHtml(content.trim() || fallbackHtml);
        setIframeError(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setInlineHtmlError(err instanceof Error ? err.message : "预览内容加载失败");
        setInlineHtml(fallbackHtml);
      })
      .finally(() => {
        if (!cancelled) setLoadingInlineHtml(false);
      });
    return () => {
      cancelled = true;
    };
  }, [artifactId, fallbackHtml, previewType, retryKey, showIframe]);

  function handleTogglePreview() {
    if (!artifactId) {
      setIframeError(true);
      return;
    }
    if (!showIframe) {
      setIframeError(false);
    }
    setShowIframe(!showIframe);
  }

  function handleRetry() {
    setIframeError(false);
    setInlineHtmlError(null);
    setInlineHtml(null);
    setRetryKey((value) => value + 1);
  }

  function handleFullscreen() {
    if (onFullscreen) {
      onFullscreen("preview", artifactId);
    } else {
      window.open(viewerUrl || resolvedPreviewUrl || sourceUrl, "_blank", "noopener noreferrer");
    }
  }

  const labelMap: Record<string, string> = {
    html: "网页预览",
    ppt: "PPT 预览",
    document: "文档预览",
    unknown: "预览",
  };

  return (
    <div className="rounded-xl border border-border bg-panel overflow-hidden my-2 shadow-[0_12px_34px_rgba(0,0,0,0.18)]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-bg/40">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-8 w-8 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center text-accent shrink-0">
            <PreviewIcon type={previewType} />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-fg truncate">{title}</div>
            <div className="text-[10px] text-muted truncate">
              {labelMap[previewType]} · {mimeType} · {formatSize(fileSize)}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0 ml-3">
          {onEdit && artifactId && (
            <button
              type="button"
              onClick={() => onEdit(artifactId)}
              className="rounded-full border border-border px-3 py-1.5 text-xs text-muted hover:text-accent hover:bg-bg transition-colors"
            >
              编辑
            </button>
          )}
          <button
            type="button"
            onClick={handleTogglePreview}
            className="rounded-full border border-accent/30 px-3 py-1.5 text-xs text-accent hover:bg-accent/10 transition-colors"
          >
            {showIframe ? "关闭预览" : labelMap[previewType]}
          </button>
          <button
            type="button"
            onClick={handleFullscreen}
            className="rounded-full border border-border px-3 py-1.5 text-xs text-muted hover:text-fg hover:bg-bg transition-colors"
          >
            全屏
          </button>
        </div>
      </div>

      {showIframe && (
        <div className="relative w-full bg-bg" style={{ height: previewType === "ppt" ? "600px" : "520px" }}>
          {loadingInlineHtml && previewType === "html" && (
            <div className="absolute left-3 top-3 z-10 rounded-full border border-border bg-panel/90 px-3 py-1.5 text-xs text-muted shadow-lg">
              正在加载预览内容…
            </div>
          )}
          {inlineHtmlError && !loadingInlineHtml && previewType === "html" && (
            <div className="absolute left-3 top-3 z-10 rounded-full border border-amber-400/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-100 shadow-lg">
              已启用本地兜底预览
            </div>
          )}
          {iframeError ? (
            <div className="flex items-center justify-center h-full text-sm text-muted">
              <div className="text-center rounded-xl border border-red-500/20 bg-red-500/5 px-6 py-5">
                <p className="text-red-300">预览加载失败</p>
                <button
                  type="button"
                  onClick={handleRetry}
                  className="mt-3 rounded-full border border-red-400/30 px-3 py-1.5 text-xs text-red-200 hover:bg-red-500/10 transition-colors"
                >
                  重试
                </button>
              </div>
            </div>
          ) : (
            <iframe
              key={retryKey}
              src={iframeSrc}
              srcDoc={iframeSrcDoc}
              title={title}
              className="w-full h-full border-0 bg-white"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              onLoad={() => setIframeError(false)}
              onError={() => setIframeError(true)}
            />
          )}
        </div>
      )}
    </div>
  );
}
