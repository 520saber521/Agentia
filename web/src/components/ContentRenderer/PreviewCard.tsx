import { useState } from "react";

interface Props {
  artifactId: string;
  title: string;
  mimeType: string;
  fileSize: number;
  onEdit?: (artifactId: string) => void;
}

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function PreviewCard({ artifactId, title, mimeType, fileSize, onEdit }: Props) {
  const [showIframe, setShowIframe] = useState(false);
  const [iframeError, setIframeError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const previewUrl = artifactId ? `/preview/${encodeURIComponent(artifactId)}` : "";

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
    setRetryKey((value) => value + 1);
  }

  return (
    <div className="rounded-xl border border-border bg-panel overflow-hidden my-2 shadow-[0_12px_34px_rgba(0,0,0,0.18)]">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-bg/40">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-8 w-8 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center text-accent shrink-0">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="4" width="18" height="16" rx="2" />
              <path d="M8 4v16" />
              <path d="M3 9h18" />
            </svg>
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-fg truncate">{title}</div>
            <div className="text-[10px] text-muted truncate">
              {mimeType} · {formatSize(fileSize)}
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
            {showIframe ? "关闭预览" : "预览"}
          </button>
          <a
            href={previewUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full border border-border px-3 py-1.5 text-xs text-muted hover:text-fg hover:bg-bg transition-colors"
          >
            全屏
          </a>
        </div>
      </div>

      {showIframe && (
        <div className="relative w-full bg-bg" style={{ height: "400px" }}>
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
              src={previewUrl}
              title={title}
              className="w-full h-full border-0 bg-white"
              sandbox="allow-scripts allow-same-origin"
              onError={() => setIframeError(true)}
            />
          )}
        </div>
      )}
    </div>
  );
}
