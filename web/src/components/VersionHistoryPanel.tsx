import { useEffect, useMemo, useState } from "react";

import { fetchArtifactContent, fetchArtifactHistory } from "../api/client";
import type { Artifact } from "../types";

interface Props {
  artifactId: string;
  currentVersion: number;
  onSelectVersion?: (artifactId: string, version: number) => void;
}

function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleDateString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatSize(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function VersionHistoryPanel({ artifactId, currentVersion, onSelectVersion }: Props) {
  const [history, setHistory] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [diffContent, setDiffContent] = useState<{ before: string; after: string; vBefore: number; vAfter: number } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchArtifactHistory(artifactId)
      .then((list) => {
        if (!cancelled) {
          setHistory(list.sort((a, b) => (b.version || 0) - (a.version || 0)));
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "版本历史加载失败");
          setLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [artifactId]);

  const handleSelectVersion = useMemo(() => (version: Artifact) => {
    setSelectedId(version.id === selectedId ? null : version.id);
    if (onSelectVersion) {
      onSelectVersion(version.id, version.version || 0);
    }
  }, [selectedId, onSelectVersion]);

  // If two versions are selected, load and diff them
  useEffect(() => {
    if (!selectedId) { setDiffContent(null); return; }
    const selected = history.find((v) => v.id === selectedId);
    if (!selected) return;
    const older = history.find(
      (v) => v.version === (selected.version || 1) - 1
    );
    if (!older) { setDiffContent(null); return; }

    let cancelled = false;
    setDiffLoading(true);
    Promise.all([
      fetchArtifactContent(older.id),
      fetchArtifactContent(selected.id),
    ])
      .then(([before, after]) => {
        if (!cancelled) {
          setDiffContent({
            before,
            after,
            vBefore: older.version || 0,
            vAfter: selected.version || 0,
          });
          setDiffLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setDiffLoading(false);
      });
    return () => { cancelled = true; };
  }, [selectedId, history]);

  if (loading) {
    return (
      <div className="px-3 py-4 text-xs text-muted text-center animate-pulse">
        加载版本历史…
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-3 py-4 text-xs text-red-400 text-center">{error}</div>
    );
  }

  if (history.length === 0) {
    return (
      <div className="px-3 py-4 text-xs text-muted text-center">暂无版本历史</div>
    );
  }

  return (
    <div className="flex flex-col min-h-0">
      <div className="px-3 py-2 border-b border-border bg-bg/40">
        <div className="text-xs font-medium text-muted">
          版本历史 · {history.length} 个版本
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {history.map((v, i) => {
          const isCurrent = v.version === currentVersion;
          const isSelected = v.id === selectedId;
          const prevVersion = history[i + 1];
          return (
            <div key={v.id}>
              <button
                type="button"
                onClick={() => handleSelectVersion(v)}
                className={`w-full text-left px-3 py-2.5 border-b border-border/50 transition-colors hover:bg-bg/60 ${
                  isSelected ? "bg-accent/5" : ""
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`text-xs font-medium ${
                    isCurrent ? "text-accent" : "text-fg/80"
                  }`}>
                    v{v.version || 1}
                  </span>
                  {isCurrent && (
                    <span className="text-[9px] rounded-full bg-accent/15 text-accent px-1.5 py-0.5 border border-accent/20">
                      当前
                    </span>
                  )}
                  <span className="ml-auto text-[10px] text-muted">
                    {formatTime(v.created_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-muted/70 truncate">
                    {v.title || "untitled"}
                  </span>
                  <span className="text-[9px] text-muted/40 shrink-0">
                    {formatSize(v.file_size)}
                  </span>
                </div>
              </button>

              {/* Diff view between this version and previous */}
              {isSelected && diffContent && (
                <div className="border-b border-border bg-bg/40">
                  {diffLoading ? (
                    <div className="px-3 py-2 text-[10px] text-muted animate-pulse">
                      加载差异…
                    </div>
                  ) : diffContent.vAfter === v.version && prevVersion ? (
                    <div className="max-h-48 overflow-auto">
                      <div className="sticky top-0 flex items-center gap-2 px-3 py-1 bg-bg/80 border-b border-border/50">
                        <span className="text-[9px] text-muted font-medium">
                          v{diffContent.vBefore} → v{diffContent.vAfter}
                        </span>
                      </div>
                      <UnifiedInlineDiff
                        before={diffContent.before}
                        after={diffContent.after}
                      />
                    </div>
                  ) : (
                    <div className="px-3 py-2 text-[10px] text-muted">
                      {diffContent.vAfter === v.version
                        ? "无前一版本可比较"
                        : "选择版本以查看差异"}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Minimal inline unified diff for version comparison. */
function UnifiedInlineDiff({ before, after }: { before: string; after: string }) {
  const lines = useMemo(() => {
    const bLines = before.split("\n");
    const aLines = after.split("\n");
    const maxLen = Math.max(bLines.length, aLines.length);
    const result: { type: "add" | "del" | "ctx"; text: string }[] = [];
    for (let i = 0; i < maxLen; i++) {
      const b = bLines[i] ?? "";
      const a = aLines[i] ?? "";
      if (b === a) {
        result.push({ type: "ctx", text: b });
      } else {
        if (b !== undefined) result.push({ type: "del", text: b });
        if (a !== undefined) result.push({ type: "add", text: a });
      }
    }
    return result;
  }, [before, after]);

  return (
    <pre className="text-[10px] font-mono leading-relaxed p-2 overflow-auto whitespace-pre">
      {lines.map((line, i) => (
        <div
          key={i}
          className={
            line.type === "add"
              ? "bg-emerald-500/10 text-emerald-300/80"
              : line.type === "del"
                ? "bg-rose-500/10 text-rose-300/70"
                : "text-muted/40"
          }
        >
          <span className="inline-block w-3 select-none text-muted/20 shrink-0">
            {line.type === "add" ? "+" : line.type === "del" ? "-" : " "}
          </span>
          {line.text || " "}
        </div>
      ))}
    </pre>
  );
}
