import type { Task } from "../types";

interface Props {
  task: Task;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  running: "bg-blue-500/20 text-blue-400 border-blue-500/30",
  done: "bg-green-500/20 text-green-400 border-green-500/30",
  failed: "bg-red-500/20 text-red-400 border-red-500/30",
  cancelled: "bg-gray-500/20 text-gray-400 border-gray-500/30",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  running: "进行中",
  done: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

export function TaskStatusCard({ task }: Props) {
  const colorClass = STATUS_COLORS[task.status] ?? STATUS_COLORS.pending;
  const label = STATUS_LABELS[task.status] ?? task.status;

  return (
    <div className="rounded-lg border border-border bg-panel p-3 my-2">
      <div className="flex items-start gap-3">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border ${colorClass} shrink-0 mt-0.5`}
        >
          {label}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">
            {task.title}
          </div>
          {task.domain && (
            <div className="text-xs text-muted mt-0.5 truncate">
              {task.domain}
            </div>
          )}
          {task.result_summary && (
            <div className="text-xs text-muted mt-1 line-clamp-2">
              {task.result_summary}
            </div>
          )}
        </div>
        {task.progress_pct > 0 && task.status === "running" && (
          <div className="shrink-0 text-right">
            <div className="text-xs font-medium text-fg">
              {task.progress_pct}%
            </div>
            <div className="w-16 h-1.5 bg-border rounded-full mt-1 overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all"
                style={{ width: `${task.progress_pct}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {task.description && task.description.length > 100 && (
        <details className="mt-2 group">
          <summary className="text-[10px] text-muted cursor-pointer hover:text-fg transition-colors">
            查看详情
          </summary>
          <p className="text-xs text-muted mt-1 whitespace-pre-wrap">
            {task.description}
          </p>
        </details>
      )}
    </div>
  );
}
