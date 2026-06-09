import { useEffect, useMemo, useState } from "react";

import { fetchArtifactHistory } from "../api/client";
import type { Artifact } from "../types";

interface Props {
  artifactId: string;
  currentVersion: number;
  selectedVersionId?: string | null;
  onCompareVersion?: (version: Artifact, previousVersion: Artifact | null) => void;
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

export function VersionHistoryPanel({
  artifactId,
  currentVersion,
  selectedVersionId,
  onCompareVersion,
}: Props) {
  const [history, setHistory] = useState<Artifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    return () => {
      cancelled = true;
    };
  }, [artifactId]);

  const handleSelectVersion = useMemo(
    () => (version: Artifact, index: number) => {
      onCompareVersion?.(version, history[index + 1] ?? null);
    },
    [history, onCompareVersion],
  );

  if (loading) {
    return (
      <div className="px-3 py-4 text-xs text-muted text-center animate-pulse">
        加载版本历史...
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
      <div className="px-3 py-3 border-b border-[#1d2633] bg-[#070b11]">
        <div className="text-sm font-medium text-[#b8c7df]">
          版本历史 · {history.length} 个版本
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {history.map((v, i) => {
          const isCurrent = v.version === currentVersion;
          const isSelected = v.id === selectedVersionId;
          const prevVersion = history[i + 1];

          return (
            <div key={v.id}>
              <button
                type="button"
                onClick={() => handleSelectVersion(v, i)}
                className={`w-full text-left px-3 py-3 border-b border-[#1d2633] transition-colors hover:bg-[#101a27] ${
                  isSelected ? "bg-[#0b1b28]" : "bg-[#080d14]"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`text-xs font-medium ${
                      isCurrent ? "text-[#36c2ff]" : "text-[#c7d2e1]"
                    }`}
                  >
                    v{v.version || 1}
                  </span>
                  {isCurrent && (
                    <span className="text-[9px] rounded-full bg-[#12384b] text-[#75d6ff] px-1.5 py-0.5 border border-[#23627d]">
                      当前
                    </span>
                  )}
                  <span className="ml-auto text-[10px] text-[#8d99aa]">
                    {formatTime(v.created_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-[#7f8a9b] truncate">
                    {v.title || "untitled"}
                  </span>
                  <span className="text-[9px] text-[#566172] shrink-0">
                    {formatSize(v.file_size)}
                  </span>
                </div>
              </button>

              {isSelected && prevVersion && (
                <div className="px-3 py-2 border-b border-[#1d2633] bg-[#080d14] font-mono text-[11px] text-[#788396]">
                  v{prevVersion.version || 1} → v{v.version || 1}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
