import { useState } from "react";

interface Props {
  code: string;
  language?: string;
  title?: string;
  artifactId?: string | null;
  onEdit?: (artifactId: string) => void;
}

export function CodeBlock({ code, language, title, artifactId, onEdit }: Props) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback
    }
  }

  return (
    <div className="rounded-lg border border-border bg-bg overflow-hidden my-2">
      <div className="flex items-center justify-between px-3 py-1.5 bg-panel border-b border-border">
        <span className="text-xs text-muted">
          {language && <span className="mr-2">{language}</span>}
          {title && <span>{title}</span>}
        </span>
        <div className="flex items-center gap-2">
          {artifactId && onEdit && (
            <button
              type="button"
              onClick={() => onEdit(artifactId)}
              className="text-xs text-muted hover:text-accent transition-colors"
            >
              编辑
            </button>
          )}
          <button
            type="button"
            onClick={handleCopy}
            className="text-xs text-muted hover:text-fg transition-colors"
          >
            {copied ? "已复制" : "复制"}
          </button>
        </div>
      </div>
      <pre className="p-3 overflow-x-auto text-xs leading-relaxed max-h-80 scrollbar-thin">
        <code>{code}</code>
      </pre>
    </div>
  );
}
