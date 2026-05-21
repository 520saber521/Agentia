interface Props {
  before: string;
  after: string;
  fileName?: string;
}

export function DiffCard({ before, after, fileName }: Props) {
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

  return (
    <div className="rounded-lg border border-border overflow-hidden my-2">
      {fileName && (
        <div className="px-3 py-1.5 bg-panel border-b border-border text-xs text-muted">
          {fileName}
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
