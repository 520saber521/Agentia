import { useState } from "react";

import { applyDiffArtifact, describeApiError } from "../../api/client";

interface Props {
  before: string;
  after: string;
  baseArtifactId?: string;
  summary?: string;
  fileName?: string;
}

type ApplyStatus = "idle" | "applying" | "applied" | "error";

export function DiffCard({
  before,
  after,
  baseArtifactId,
  summary,
  fileName,
}: Props) {
  const [status, setStatus] = useState<ApplyStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const beforeLines = before.split("\n");
  const afterLines = after.split("\n");
  const maxLines = Math.max(beforeLines.length, afterLines.length);

  const changes: Array<{
    lineNum: number;
    type: "same" | "added" | "removed";
    beforeText: string;
    afterText: string;
  }> = [];

  for (let i = 0; i < maxLines; i++) {
    const b = beforeLines[i] ?? "";
    const a = afterLines[i] ?? "";
    if (b === a) {
      changes.push({ lineNum: i + 1, type: "same", beforeText: b, afterText: a });
    } else {
      if (b !== undefined) {
        changes.push({ lineNum: i + 1, type: "removed", beforeText: b, afterText: "" });
      }
      if (a !== undefined && b !== undefined) {
        changes.push({ lineNum: i + 1, type: "added", beforeText: "", afterText: a });
      } else if (a !== undefined) {
        changes.push({ lineNum: i + 1, type: "added", beforeText: "", afterText: a });
      }
    }
  }

  const handleApply = async () => {
    if (!baseArtifactId || status === "applying" || status === "applied") return;
    setStatus("applying");
    setError(null);
    try {
      await applyDiffArtifact({
        base_artifact_id: baseArtifactId,
        before,
        after,
        summary,
        file_name: fileName,
      });
      setStatus("applied");
    } catch (err) {
      setStatus("error");
      setError(describeApiError(err));
    }
  };

  return (
    <div className="rounded-lg border border-border overflow-hidden my-2">
      <div className="px-3 py-2 bg-panel border-b border-border flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-medium text-fg truncate">
            {fileName ?? "Diff 变更"}
          </div>
          {summary && (
            <div className="text-[11px] text-muted truncate mt-0.5">
              {summary}
            </div>
          )}
        </div>
        <button
          type="button"
          onClick={handleApply}
          disabled={!baseArtifactId || status === "applying" || status === "applied"}
          className="shrink-0 px-2.5 py-1 text-[11px] rounded-md bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
          title={!baseArtifactId ? "缺少 base_artifact_id，无法应用" : undefined}
        >
          {status === "applying"
            ? "应用中…"
            : status === "applied"
              ? "已应用"
              : "应用"}
        </button>
      </div>
      {status === "error" && (
        <div className="px-3 py-2 text-[11px] text-red-500/80 border-b border-border bg-red-500/5">
          {error ?? "应用 Diff 失败"}
        </div>
      )}
      <div className="overflow-x-auto max-h-96 scrollbar-thin">
        <table className="w-full text-[11px] font-mono leading-relaxed">
          <tbody>
            {changes.map((c, i) => (
              <tr
                key={i}
                className={
                  c.type === "added"
                    ? "bg-green-500/5"
                    : c.type === "removed"
                      ? "bg-red-500/5"
                      : ""
                }
              >
                <td className="w-8 text-right text-muted select-none px-1 py-0 border-r border-border">
                  {c.lineNum}
                </td>
                <td className="w-4 text-center select-none px-1 py-0">
                  {c.type === "added" ? (
                    <span className="text-green-500">+</span>
                  ) : c.type === "removed" ? (
                    <span className="text-red-500">-</span>
                  ) : (
                    <span className="text-muted">&nbsp;</span>
                  )}
                </td>
                <td className="px-2 py-0 whitespace-pre">
                  {c.type === "removed" ? (
                    <span className="text-red-400/80">{c.beforeText}</span>
                  ) : c.type === "added" ? (
                    <span className="text-green-400/80">{c.afterText}</span>
                  ) : (
                    <span className="text-fg/60">{c.beforeText}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
