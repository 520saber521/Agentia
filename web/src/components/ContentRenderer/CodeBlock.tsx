import { useEffect, useState } from "react";

interface Props {
  code?: string;
  language?: string;
  title?: string;
  artifactId?: string | null;
  onEdit?: (artifactId: string) => void;
}

export function CodeBlock({ code, language, title, artifactId, onEdit }: Props) {
  const [copied, setCopied] = useState(false);
  const [loadedCode, setLoadedCode] = useState(code ?? "");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (code !== undefined) {
      setLoadedCode(code);
      return;
    }
    if (!artifactId) {
      setLoadedCode("");
      return;
    }

    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    fetch(`/api/artifacts/${artifactId}/content`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (!cancelled) setLoadedCode(typeof data.content === "string" ? data.content : "");
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [artifactId, code]);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(loadedCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-bg overflow-hidden my-2 shadow-[0_10px_30px_rgba(0,0,0,0.18)]">
      <div className="flex items-center justify-between px-3 py-2 bg-panel border-b border-border">
        <span className="text-xs text-muted flex items-center gap-2 min-w-0">
          <span className="inline-flex h-2 w-2 rounded-full bg-accent shadow-[0_0_10px_var(--accent)]" />
          {language && <span className="uppercase tracking-[0.2em]">{language}</span>}
          {title && <span className="truncate text-fg/80">{title}</span>}
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
            disabled={loading || loadError}
            className="text-xs text-muted hover:text-fg disabled:opacity-40 transition-colors"
          >
            {copied ? "已复制" : "复制"}
          </button>
        </div>
      </div>
      {loadError ? (
        <div className="p-4 text-xs text-red-400 bg-red-500/5">代码内容加载失败，请稍后重试。</div>
      ) : loading ? (
        <div className="p-4 text-xs text-muted">正在加载代码内容…</div>
      ) : (
        <pre className="p-3 overflow-auto text-xs leading-relaxed max-h-80 scrollbar-thin whitespace-pre min-w-0">
          <code>{loadedCode}</code>
        </pre>
      )}
    </div>
  );
}
