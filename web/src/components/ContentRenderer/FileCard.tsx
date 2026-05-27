interface Props {
  fileName: string;
  mimeType: string;
  fileSize: number;
  downloadUrl: string;
  artifactId?: string;
}

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
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

function canPreviewFile(fileName: string, mimeType: string): boolean {
  const ext = fileName.toLowerCase().split(".").pop() || "";
  const previewableExts = ["pptx", "ppt", "md", "markdown", "txt", "csv", "log"];
  if (previewableExts.includes(ext)) return true;
  const t = mimeType.toLowerCase();
  if (t.includes("presentation") || t.includes("powerpoint")) return true;
  if (t.includes("markdown") || t === "text/plain" || t === "text/csv") return true;
  return false;
}

export function FileCard({ fileName, mimeType, fileSize, downloadUrl, artifactId }: Props) {
  const previewable = canPreviewFile(fileName, mimeType);
  const viewerUrl = artifactId ? `/preview/${encodeURIComponent(artifactId)}/viewer` : "";

  return (
    <div className="rounded-xl border border-border bg-panel p-3 my-2 shadow-[0_8px_24px_rgba(0,0,0,0.14)]">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center text-accent shrink-0 border border-accent/20">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">{fileName}</div>
          <div className="text-[10px] text-muted mt-1 flex items-center gap-2 min-w-0">
            <span className="truncate">{shortMime(mimeType)}</span>
            <span aria-hidden="true">•</span>
            <span className="shrink-0">{formatSize(fileSize)}</span>
            {previewable && <span className="text-accent shrink-0">可预览</span>}
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {previewable && viewerUrl && (
            <a
              href={viewerUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full border border-border px-3 py-1.5 text-xs text-muted hover:text-accent hover:bg-bg transition-colors"
            >
              预览
            </a>
          )}
          <a
            href={downloadUrl}
            download={fileName}
            className="rounded-full border border-accent/30 px-3 py-1.5 text-xs text-accent hover:bg-accent/10 transition-colors"
          >
            下载
          </a>
        </div>
      </div>
    </div>
  );
}
