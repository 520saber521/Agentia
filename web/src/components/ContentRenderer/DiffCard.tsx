import { useMemo, useState } from "react";

import { applyDiffArtifact, describeApiError } from "../../api/client";

interface Props {
  diff?: string;
  before: string;
  after: string;
  baseArtifactId?: string;
  appliedArtifactId?: string;
  summary?: string;
  fileName?: string;
  onApplied?: () => void;
}

type ApplyStatus = "idle" | "applying" | "applied" | "error";

/** Parse unified-diff format into structured hunks. */
interface HunkLine {
  type: "add" | "del" | "ctx" | "hdr";
  text: string;
  oldNum: number | "";
  newNum: number | "";
}

interface Hunk {
  header: string;
  lines: HunkLine[];
}

function parseDiff(diffText: string): Hunk[] {
  const hunks: Hunk[] = [];
  let current: Hunk | null = null;
  let oldLine = 0;
  let newLine = 0;

  for (const raw of diffText.split("\n")) {
    if (raw.startsWith("@@")) {
      current = { header: raw, lines: [] };
      hunks.push(current);
      const m = raw.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      oldLine = m ? parseInt(m[1], 10) : 0;
      newLine = m ? parseInt(m[2], 10) : 0;
      continue;
    }
    if (!current) continue;

    if (raw.startsWith("+")) {
      current.lines.push({ type: "add", text: raw.slice(1), newNum: newLine, oldNum: "" });
      newLine++;
    } else if (raw.startsWith("-")) {
      current.lines.push({ type: "del", text: raw.slice(1), oldNum: oldLine, newNum: "" });
      oldLine++;
    } else if (raw.startsWith("\\")) {
      // No-eol marker — skip
      continue;
    } else {
      // Context line (starts with space or is empty)
      const content = raw.startsWith(" ") ? raw.slice(1) : raw;
      current.lines.push({ type: "ctx", text: content, oldNum: oldLine, newNum: newLine });
      oldLine++;
      newLine++;
    }
  }
  return hunks;
}

function countChanges(hunks: Hunk[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const h of hunks) {
    for (const l of h.lines) {
      if (l.type === "add") added++;
      if (l.type === "del") removed++;
    }
  }
  return { added, removed };
}

/** Simplified side-by-side diff for short snippets. */
function SideBySideView({ before, after }: { before: string; after: string }) {
  const bLines = before.split("\n");
  const aLines = after.split("\n");
  const max = Math.max(bLines.length, aLines.length);
  const maxNumLen = String(max).length;

  const rows = [];
  for (let i = 0; i < max; i++) {
    const b = bLines[i] ?? "";
    const a = aLines[i] ?? "";
    if (b === a) {
      rows.push({ type: "ctx" as const, left: b, right: a, leftNum: i + 1, rightNum: i + 1, span: false });
    } else {
      if (b !== undefined) {
        rows.push({ type: "del" as const, left: b, right: "", leftNum: i + 1, rightNum: "", span: false });
      }
      if (a !== undefined) {
        rows.push({ type: "add" as const, left: "", right: a, leftNum: "", rightNum: i + 1, span: b === undefined });
      }
    }
  }

  return (
    <div className="flex text-[11px] font-mono leading-relaxed">
      {/* Before */}
      <div className="flex-1 min-w-0">
        <div className="sticky top-0 flex items-center gap-1 px-3 py-1.5 text-[10px] font-medium text-rose-400 bg-bg border-b border-border/50">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="5" y1="12" x2="19" y2="12" /></svg>
          原始
        </div>
        <table className="w-full border-collapse">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={r.type === "del" ? "bg-rose-500/8" : ""}>
                <td className={`text-right text-muted/30 select-none px-1.5 py-0 border-r border-border/30 w-[${maxNumLen + 1}ch]`}
                  style={{ minWidth: `${maxNumLen + 2}ch` }}>
                  {r.type === "del" || r.type === "ctx" ? r.leftNum : ""}
                </td>
                <td className="px-2 py-0 whitespace-pre">
                  {r.type === "del" ? (
                    <span className="text-rose-300/80">{r.left}</span>
                  ) : r.type === "add" ? (
                    <span className="text-muted/20">{r.right || " "}</span>
                  ) : (
                    <span className="text-fg/50">{r.left}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* After */}
      <div className="flex-1 min-w-0 border-l border-border/50">
        <div className="sticky top-0 flex items-center gap-1 px-3 py-1.5 text-[10px] font-medium text-emerald-400 bg-bg border-b border-border/50">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
          修改后
        </div>
        <table className="w-full border-collapse">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={r.type === "add" ? "bg-emerald-500/8" : ""}>
                <td className={`text-right text-muted/30 select-none px-1.5 py-0 border-r border-border/30 w-[${maxNumLen + 1}ch]`}
                  style={{ minWidth: `${maxNumLen + 2}ch` }}>
                  {r.type === "add" || r.type === "ctx" ? r.rightNum : ""}
                </td>
                <td className="px-2 py-0 whitespace-pre">
                  {r.type === "add" ? (
                    <span className="text-emerald-300/80">{r.right}</span>
                  ) : r.type === "del" ? (
                    <span className="text-muted/20">{r.left || " "}</span>
                  ) : (
                    <span className="text-fg/50">{r.right}</span>
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

/** Unified hunk-based diff view (Claude Code style). */
function UnifiedDiffView({ diff }: { diff: string }) {
  const hunks = useMemo(() => parseDiff(diff), [diff]);
  useMemo(() => countChanges(hunks), [hunks]);

  if (hunks.length === 0) {
    // Fall back to raw line-by-line if no @@ headers found
    return (
      <pre className="p-3 text-[11px] font-mono leading-relaxed whitespace-pre min-w-max">
        {diff.split("\n").map((line, i) => {
          const isAdd = line.startsWith("+") && !line.startsWith("+++");
          const isDel = line.startsWith("-") && !line.startsWith("---");
          const isHdr = line.startsWith("@@");
          return (
            <div key={i} className={
              isAdd ? "bg-emerald-500/8" : isDel ? "bg-rose-500/8" : isHdr ? "bg-sky-500/6" : ""
            }>
              <span className={`inline-block w-8 text-right select-none mr-2 ${
                isHdr ? "text-sky-400" : "text-muted/30"
              }`}>
                {isHdr ? "@@" : isAdd ? "+" : isDel ? "-" : " "}
              </span>
              <span className={isAdd ? "text-emerald-300/90" : isDel ? "text-rose-300/80" : isHdr ? "text-sky-300" : "text-fg/60"}>
                {line || " "}
              </span>
            </div>
          );
        })}
      </pre>
    );
  }

  return (
    <div className="text-[11px] font-mono leading-relaxed">
      {hunks.map((hunk, hi) => (
        <div key={hi}>
          {/* Hunk header */}
          <div className="sticky top-0 flex items-center gap-2 px-3 py-1.5 bg-sky-500/8 border-y border-sky-500/15 text-sky-300 text-[10px] font-medium">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M4 6h16M4 12h16M4 18h12" />
            </svg>
            <span className="truncate">{hunk.header}</span>
            <span className="ml-auto text-muted/60 shrink-0">
              +{hunk.lines.filter(l => l.type === "add").length}
              {" "}-{hunk.lines.filter(l => l.type === "del").length}
            </span>
          </div>

          {/* Hunk lines */}
          {hunk.lines.map((line, li) => (
            <div
              key={li}
              className={`flex hover:brightness-110 ${
                line.type === "add" ? "bg-emerald-500/8" :
                line.type === "del" ? "bg-rose-500/8" : ""
              }`}
            >
              {/* Old line number */}
              <span className="inline-block w-[3ch] text-right text-muted/25 select-none px-1 shrink-0 border-r border-border/30">
                {line.oldNum}
              </span>
              {/* New line number */}
              <span className="inline-block w-[3ch] text-right text-muted/25 select-none px-1 shrink-0 border-r border-border/30">
                {line.newNum}
              </span>
              {/* Diff marker and content */}
              <span className="w-[1.2ch] text-center select-none shrink-0 text-muted/30">
                {line.type === "add" ? (
                  <span className="text-emerald-500 font-bold">+</span>
                ) : line.type === "del" ? (
                  <span className="text-rose-500 font-bold">−</span>
                ) : (
                  <span className="text-muted/20"> </span>
                )}
              </span>
              <span className={`whitespace-pre px-1 flex-1 min-w-0 ${
                line.type === "add" ? "text-emerald-300/85" :
                line.type === "del" ? "text-rose-300/80" :
                "text-fg/55"
              }`}>
                {line.text || " "}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function DiffCard({
  diff,
  before,
  after,
  baseArtifactId,
  appliedArtifactId,
  summary,
  fileName,
  onApplied,
}: Props) {
  const [status, setStatus] = useState<ApplyStatus>(appliedArtifactId ? "applied" : "idle");
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"unified" | "split">(diff ? "unified" : "split");

  const hunks = useMemo(() => diff ? parseDiff(diff) : [], [diff]);
  const { added, removed } = useMemo(() => diff ? countChanges(hunks) : {
    added: after.split("\n").filter((l, i) => l !== (before.split("\n")[i] ?? "")).length,
    removed: before.split("\n").filter((l, i) => l !== (after.split("\n")[i] ?? "")).length,
  }, [diff, before, after, hunks]);

  const hasBaseArtifact = Boolean(baseArtifactId);
  const canApply = hasBaseArtifact && status === "idle";

  const handleApply = async () => {
    if (!canApply) return;
    setStatus("applying");
    setError(null);
    try {
      await applyDiffArtifact({
        base_artifact_id: baseArtifactId!,
        before,
        after,
        summary,
        file_name: fileName,
      });
      setStatus("applied");
      onApplied?.();
    } catch (err) {
      setStatus("error");
      setError(describeApiError(err));
    }
  };

  return (
    <div className="rounded-xl border border-border bg-panel overflow-hidden my-2 shadow-[0_10px_30px_rgba(0,0,0,0.18)]">
      {/* Header bar — Claude Code style */}
      <div className="flex items-center justify-between px-3.5 py-2.5 bg-bg/30 border-b border-border gap-3">
        {/* Left: file icon + name + version badge */}
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="h-7 w-7 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 shrink-0">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-fg truncate leading-tight">
                {fileName ?? "Diff 变更"}
              </span>
              <span className="shrink-0 rounded-md border border-border/60 px-1.5 py-0.5 text-[10px] text-muted">
                diff
              </span>
            </div>
            {summary && (
              <div className="text-[10px] text-muted mt-0.5 flex items-center gap-2">
                {summary}
                {added + removed > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <span className="text-emerald-400 font-medium">+{added}</span>
                    <span className="text-muted/40">/</span>
                    <span className="text-rose-400 font-medium">-{removed}</span>
                  </span>
                )}
              </div>
            )}
            {!summary && added + removed > 0 && (
              <div className="text-[10px] text-muted mt-0.5 flex items-center gap-1">
                <span className="text-emerald-400 font-medium">+{added}</span>
                <span className="text-muted/40">/</span>
                <span className="text-rose-400 font-medium">-{removed}</span>
              </div>
            )}
          </div>
        </div>

        {/* Right: actions */}
        <div className="flex items-center gap-1.5 shrink-0">
          {diff && (
            <button
              type="button"
              onClick={() => setViewMode(viewMode === "split" ? "unified" : "split")}
              className="rounded-md border border-border/60 px-2 py-1 text-[11px] text-muted hover:text-fg hover:bg-bg transition-colors"
              title={viewMode === "split" ? "统一视图" : "分栏视图"}
            >
              {viewMode === "split" ? "统一" : "分栏"}
            </button>
          )}

          {status === "applied" ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-emerald-500/12 border border-emerald-500/25 px-2.5 py-1 text-[11px] text-emerald-400 font-medium">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              已应用
            </span>
          ) : status === "error" ? (
            <button
              type="button"
              onClick={handleApply}
              className="rounded-md bg-accent px-2.5 py-1 text-[11px] text-white hover:bg-accent-hover transition-colors"
            >
              重试
            </button>
          ) : (
            <button
              type="button"
              disabled={!canApply}
              onClick={handleApply}
              title={!hasBaseArtifact ? "需要 base_artifact_id 才能应用" : undefined}
              className={`rounded-md px-3 py-1 text-[11px] font-medium transition-all flex items-center gap-1 ${
                status === "applying"
                  ? "bg-accent/60 text-white cursor-wait"
                  : hasBaseArtifact
                    ? "bg-accent text-white hover:bg-accent-hover active:scale-[0.97]"
                    : "bg-border/50 text-muted cursor-not-allowed"
              }`}
            >
              {status === "applying" ? (
                <>
                  <span className="w-3 h-3 rounded-full border-2 border-white/30 border-t-white animate-spin" />
                  应用中…
                </>
              ) : (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  应用
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Error message */}
      {status === "error" && error && (
        <div className="px-3.5 py-2 text-[11px] text-red-400 bg-red-500/6 border-b border-red-500/15 flex items-center gap-2">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0">
            <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
          </svg>
          <span>{error}</span>
        </div>
      )}

      {/* Diff body */}
      <div className="overflow-x-auto max-h-[480px] scrollbar-thin bg-bg/60">
        {diff && viewMode === "unified" ? (
          <UnifiedDiffView diff={diff} />
        ) : diff ? (
          <SideBySideView before={before} after={after} />
        ) : (
          <SideBySideView before={before} after={after} />
        )}

        {!diff && !before && !after && (
          <div className="p-6 text-center text-xs text-muted">无变更内容</div>
        )}
      </div>
    </div>
  );
}
