interface Props {
  fileName: string;
  mimeType: string;
  fileSize: number;
  downloadUrl: string;
}

function formatSize(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export function FileCard({ fileName, mimeType, fileSize, downloadUrl }: Props) {
  return (
    <div className="rounded-lg border border-border bg-panel p-3 my-2">
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded bg-accent/10 flex items-center justify-center text-accent shrink-0">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <line x1="16" y1="13" x2="8" y2="13" />
            <line x1="16" y1="17" x2="8" y2="17" />
            <polyline points="10 9 9 9 8 9" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">{fileName}</div>
          <div className="text-[10px] text-muted mt-0.5">
            {mimeType} &middot; {formatSize(fileSize)}
          </div>
        </div>
        <a
          href={downloadUrl}
          download={fileName}
          className="shrink-0 text-xs text-accent hover:text-accent/80 transition-colors"
        >
          下载
        </a>
      </div>
    </div>
  );
}
