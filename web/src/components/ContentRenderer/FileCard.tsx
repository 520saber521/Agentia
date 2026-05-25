import { useState } from "react";

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
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function shortMime(mimeType: string): string {
  const [family, subtype] = mimeType.split("/");
  if (!subtype) return mimeType;
  return `${family}/${subtype.split(";")[0]}`;
}

const isImage = (mime: string) => mime.startsWith("image/");
const isCode = (mime: string) =>
  mime.startsWith("text/x-") || ["text/javascript", "text/typescript", "text/css", "text/html"].includes(mime);

export function FileCard({ fileName, mimeType, fileSize, downloadUrl }: Props) {
  const [imgError, setImgError] = useState(false);

  return (
    <div className="rounded-xl border border-border bg-panel overflow-hidden my-2 shadow-[0_8px_24px_rgba(0,0,0,0.14)]">
      {/* Image preview */}
      {isImage(mimeType) && !imgError && (
        <div className="border-b border-border bg-bg p-2 flex items-center justify-center min-h-[80px] max-h-[320px] overflow-hidden">
          <img
            src={downloadUrl}
            alt={fileName}
            className="max-w-full max-h-[300px] rounded-lg object-contain cursor-pointer transition-transform hover:scale-[1.02]"
            onError={() => setImgError(true)}
          />
        </div>
      )}

      {/* File info bar */}
      <div className="flex items-center gap-3 p-3">
        <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border ${
          isImage(mimeType)
            ? "bg-rose-500/10 border-rose-500/20 text-rose-400"
            : isCode(mimeType)
              ? "bg-cyan-500/10 border-cyan-500/20 text-cyan-400"
              : "bg-accent/10 border-accent/20 text-accent"
        }`}>
          {isImage(mimeType) ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
            </svg>
          ) : isCode(mimeType) ? (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
            </svg>
          ) : (
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">{fileName}</div>
          <div className="text-[10px] text-muted mt-0.5 flex items-center gap-2 min-w-0">
            <span className="truncate">{shortMime(mimeType)}</span>
            <span aria-hidden="true">•</span>
            <span className="shrink-0">{formatSize(fileSize)}</span>
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
