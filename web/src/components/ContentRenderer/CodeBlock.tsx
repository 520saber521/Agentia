import { useEffect, useMemo, useRef, useState } from "react";
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-yaml";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-css";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-go";
import "prismjs/components/prism-java";
import "prismjs/components/prism-c";
import "prismjs/components/prism-cpp";

interface Props {
  code?: string;
  language?: string;
  title?: string;
  artifactId?: string | null;
  onEdit?: (artifactId: string) => void;
  /** Show mini toolbar (copy, line numbers toggle, etc.) */
  mini?: boolean;
  /** Max height before scrolling; omit for no limit */
  maxHeight?: number;
}

const LANG_COLORS: Record<string, string> = {
  html: "bg-orange-500/15 text-orange-400 border-orange-500/25",
  css: "bg-sky-500/15 text-sky-400 border-sky-500/25",
  javascript: "bg-amber-500/15 text-amber-400 border-amber-500/25",
  typescript: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  python: "bg-emerald-500/15 text-emerald-400 border-emerald-500/25",
  jsx: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
  tsx: "bg-blue-500/15 text-blue-400 border-blue-500/25",
  json: "bg-violet-500/15 text-violet-400 border-violet-500/25",
  bash: "bg-neutral-500/15 text-neutral-400 border-neutral-500/25",
  sql: "bg-rose-500/15 text-rose-400 border-rose-500/25",
  yaml: "bg-pink-500/15 text-pink-400 border-pink-500/25",
  md: "bg-gray-500/15 text-gray-400 border-gray-500/25",
  rust: "bg-amber-500/15 text-amber-400 border-amber-500/25",
  go: "bg-cyan-500/15 text-cyan-400 border-cyan-500/25",
};

const PRISM_LANG_MAP: Record<string, string> = {
  js: "javascript",
  ts: "typescript",
  jsx: "jsx",
  tsx: "tsx",
  py: "python",
  sh: "bash",
  yml: "yaml",
  md: "markdown",
  rs: "rust",
  cpp: "cpp",
  h: "c",
};

function normalizeLang(language?: string): string {
  if (!language) return "plaintext";
  const lower = language.toLowerCase();
  return PRISM_LANG_MAP[lower] ?? lower;
}

function highlightCode(code: string, language?: string): string {
  const lang = normalizeLang(language);
  try {
    if (Prism.languages[lang]) {
      return Prism.highlight(code, Prism.languages[lang], lang);
    }
  } catch {
    // fall through
  }
  return code
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function langColor(language?: string): string {
  if (!language) return "bg-accent/10 text-accent border-accent/20";
  return LANG_COLORS[language.toLowerCase()] ?? "bg-accent/10 text-accent border-accent/20";
}

export function CodeBlock({ code, language, title, artifactId, onEdit, mini, maxHeight }: Props) {
  const [copied, setCopied] = useState(false);
  const [showLines, setShowLines] = useState(true);
  const [loadedCode, setLoadedCode] = useState(code ?? "");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const copyBtnRef = useRef<HTMLButtonElement>(null);

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

    return () => { cancelled = true; };
  }, [artifactId, code]);

  const highlighted = useMemo(
    () => highlightCode(loadedCode, language),
    [loadedCode, language],
  );

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(loadedCode);
      setCopied(true);
      if (copyBtnRef.current) {
        copyBtnRef.current.classList.add("text-emerald-400");
        setTimeout(() => copyBtnRef.current?.classList.remove("text-emerald-400"), 1200);
      }
      setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  const lines = loadedCode.split("\n");
  const styleMaxH = maxHeight ? { maxHeight: `${maxHeight}px` } : { maxHeight: "480px" };

  const toolbar = (
    <div className="flex items-center justify-between px-3 py-1.5 bg-panel border-b border-border">
      <span className="text-xs text-muted flex items-center gap-2 min-w-0">
        {language && (
          <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium border ${langColor(language)}`}>
            {language}
          </span>
        )}
        {title && <span className="truncate text-fg/80">{title}</span>}
      </span>
      <div className="flex items-center gap-1">
        {!mini && (
          <button
            type="button"
            onClick={() => setShowLines(!showLines)}
            className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${showLines ? "text-accent bg-accent/10" : "text-muted hover:text-fg"}`}
            title={showLines ? "隐藏行号" : "显示行号"}
          >
            {showLines ? "行号" : "行号"}
          </button>
        )}
        {!loading && !loadError && loadedCode && (
          <button
            type="button"
            onClick={() => {
              window.dispatchEvent(
                new CustomEvent("agenthub:code-to-chat", {
                  detail: { code: loadedCode, title: title || "代码" },
                })
              );
            }}
            className="text-[10px] text-sky-400 hover:text-sky-300 transition-colors px-1.5 py-0.5"
            title="在聊天中描述修改"
          >
            在聊天中修改
          </button>
        )}
        {artifactId && onEdit && (
          <button
            type="button"
            onClick={() => onEdit(artifactId)}
            className="text-[10px] text-muted hover:text-accent transition-colors px-1.5 py-0.5"
          >
            编辑
          </button>
        )}
        <button
          ref={copyBtnRef}
          type="button"
          onClick={handleCopy}
          disabled={loading || loadError}
          className="text-[10px] text-muted hover:text-fg disabled:opacity-40 transition-colors px-1.5 py-0.5"
        >
          {copied ? "已复制" : "复制"}
        </button>
      </div>
    </div>
  );

  if (mini) {
    return (
      <div className="rounded-lg border border-border bg-bg overflow-hidden my-1">
        {toolbar}
        {loadError ? (
          <div className="p-3 text-[10px] text-red-400 bg-red-500/5">代码加载失败</div>
        ) : loading ? (
          <div className="p-3 text-[10px] text-muted animate-pulse">加载中...</div>
        ) : (
          <pre className="overflow-auto text-[11px] leading-[1.6] whitespace-pre min-w-0 flex" style={styleMaxH}>
            {showLines && (
              <div className="select-none text-right pr-2 pl-2 py-2 text-muted/30 border-r border-border/50 shrink-0 sticky left-0 bg-bg">
                {lines.map((_, i) => (
                  <div key={i} className="leading-[1.6]">{i + 1}</div>
                ))}
              </div>
            )}
            <code
              className="block p-2 min-w-0 flex-1"
              dangerouslySetInnerHTML={{ __html: highlighted }}
            />
          </pre>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-bg overflow-hidden my-2 shadow-[0_10px_30px_rgba(0,0,0,0.18)] group">
      {toolbar}
      {loadError ? (
        <div className="p-4 text-xs text-red-400 bg-red-500/5">代码内容加载失败，请稍后重试。</div>
      ) : loading ? (
        <div className="p-4 text-xs text-muted animate-pulse">
          <div className="h-3 w-3/4 rounded bg-border mb-2" />
          <div className="h-3 w-1/2 rounded bg-border" />
        </div>
      ) : (
        <pre className="overflow-auto text-xs leading-[1.65] whitespace-pre min-w-0 flex" style={styleMaxH}>
          {showLines && (
            <div className="select-none text-right pr-3 pl-2 py-3 text-muted/40 border-r border-border/50 shrink-0 sticky left-0 bg-bg">
              {lines.map((_, i) => (
                <div key={i} className="leading-[1.65]">{i + 1}</div>
              ))}
            </div>
          )}
          <code
            className="block p-3 min-w-0 flex-1"
            dangerouslySetInnerHTML={{ __html: highlighted }}
          />
        </pre>
      )}
    </div>
  );
}
