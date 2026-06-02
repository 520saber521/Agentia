import type { Task } from "../types";
import { Bot } from "./icons";

interface Props {
  task: Task;
}

const STATUS_COLORS: Record<string, string> = {
  pending: "text-warning border-warning/40",
  planning: "text-info border-info/40",
  running: "text-accent border-accent/40",
  done: "text-success border-success/40",
  failed: "text-danger border-danger/40",
  blocked: "text-danger border-danger/40",
  conflict: "text-warning border-warning/40",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  planning: "规划中",
  running: "执行中",
  done: "已完成",
  failed: "失败",
  blocked: "阻塞",
  conflict: "冲突",
};

export function TaskStatusCard({ task }: Props) {
  const colorClass = STATUS_COLORS[task.status] ?? STATUS_COLORS.pending;
  const label = STATUS_LABELS[task.status] ?? task.status;

  return (
    <div className="rounded-lg border border-border bg-panel p-3 my-2">
      <div className="flex items-start gap-3">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded-full text-3xs font-medium border shrink-0 mt-0.5 ${colorClass}`}
        >
          {label}
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-fg truncate">
            {task.title}
          </div>
          {task.agent_name && (
            <div className="text-xs text-accent mt-0.5 truncate font-medium inline-flex items-center gap-1">
              <Bot className="h-3 w-3" />
              {task.agent_name}
            </div>
          )}
          {!task.agent_name && task.domain && (
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

      {task.status === "done" && task.result_summary && (
        <details className="mt-2 group">
          <summary className="text-3xs text-muted cursor-pointer hover:text-fg">
            查看详情
          </summary>
          <p className="text-xs text-muted mt-1 whitespace-pre-wrap">
            {task.result_summary}
          </p>
        </details>
      )}
    </div>
  );
}
