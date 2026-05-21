import { useState } from "react";

interface Props {
  artifactId: string;
  title: string;
  mimeType: string;
  fileSize: number;
}

export function PreviewCard({ artifactId, title, mimeType, fileSize }: Props) {
  const [showIframe, setShowIframe] = useState(false);
  const [iframeError, setIframeError] = useState(false);
  const previewUrl = `//${window.location.host}/preview/${artifactId}`;

  function handleTogglePreview() {
    if (!showIframe) {
      setIframeError(false);
    }
    setShowIframe(!showIframe);
  }

  return (
    <div className="rounded-lg border border-border bg-panel overflow-hidden my-2">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-sm font-medium text-fg truncate">{title}</span>
          <span className="text-[10px] text-muted shrink-0">
            {mimeType}
          </span>
          {fileSize > 0 && (
            <span className="text-[10px] text-muted shrink-0">
              {(fileSize / 1024).toFixed(1)} KB
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={handleTogglePreview}
          className="text-xs text-accent hover:text-accent/80 transition-colors shrink-0 ml-2"
        >
          {showIframe ? "关闭预览" : "预览"}
        </button>
      </div>

      {showIframe && (
        <div className="relative w-full" style={{ height: "400px" }}>
          {iframeError ? (
            <div className="flex items-center justify-center h-full text-sm text-muted">
              <div className="text-center">
                <p>预览加载失败</p>
                <button
                  type="button"
                  onClick={() => setIframeError(false)}
                  className="text-accent hover:underline mt-1"
                >
                  重试
                </button>
              </div>
            </div>
          ) : (
            <iframe
              src={previewUrl}
              title={title}
              className="w-full h-full border-0"
              sandbox="allow-scripts allow-same-origin"
              onError={() => setIframeError(true)}
              onLoad={() => {
                // iframe load doesn't guarantee content success
              }}
            />
          )}
        </div>
      )}

      <a
        href={previewUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="block px-3 py-1.5 text-[10px] text-muted hover:text-fg transition-colors border-t border-border"
      >
        在新窗口打开 &rarr;
      </a>
    </div>
  );
}
