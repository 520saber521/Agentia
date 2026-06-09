import type { DeployStatusContent, TaskStatusContent } from "../../types";

const STATUS_COLORS: Record<string, string> = {
  planning: "text-sky-400 border-sky-500/40 bg-sky-500/5",
  pending: "text-amber-400 border-amber-500/40 bg-amber-500/5",
  running: "text-blue-400 border-blue-500/40 bg-blue-500/5",
  done: "text-emerald-400 border-emerald-500/40 bg-emerald-500/5",
  failed: "text-red-400 border-red-500/40 bg-red-500/5",
  blocked: "text-rose-400 border-rose-500/40 bg-rose-500/5",
  conflict: "text-orange-400 border-orange-500/40 bg-orange-500/5",
  building: "text-blue-400 border-blue-500/40 bg-blue-500/5",
  deploying: "text-amber-400 border-amber-500/40 bg-amber-500/5",
  deployed: "text-emerald-400 border-emerald-500/40 bg-emerald-500/5",
};

interface TaskStatusProps {
  content: TaskStatusContent;
}

interface DeployStatusProps {
  content: DeployStatusContent;
}

function colorFor(status: string): string {
  return STATUS_COLORS[status] ?? "text-muted border-border bg-bg";
}

export function TaskStatusInlineCard({ content }: TaskStatusProps) {
  const progress = Math.max(0, Math.min(100, Number(content.progress ?? 0)));
  return (
    <div className="rounded-xl border border-border bg-panel p-3 my-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-fg truncate">
            {content.title ?? "任务状态"}
          </div>
          {content.summary && (
            <div className="text-xs text-muted mt-1 line-clamp-2">
              {content.summary}
            </div>
          )}
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${colorFor(content.status)}`}>
          {content.status}
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bg border border-border">
        <div
          className="h-full rounded-full bg-accent transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="mt-2 text-[10px] text-muted truncate">
        task · {content.task_id} · {progress}%
      </div>
    </div>
  );
}

export function DeployStatusCard({ content }: DeployStatusProps) {
  const progress = Math.max(0, Math.min(100, Number(content.progress ?? 0)));

  return (
    <div className="rounded-xl border border-border bg-panel p-3 my-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-medium text-fg truncate">
            {content.title ?? "部署状态"}
          </div>
          {content.summary && (
            <div className="text-xs text-muted mt-1 line-clamp-2">
              {content.summary}
            </div>
          )}
          {content.url && (
            <a
              href={content.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex mt-2 text-xs text-accent hover:underline"
            >
              打开部署地址
            </a>
          )}
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${colorFor(content.status)}`}>
          {content.status}
        </span>
      </div>
      {progress > 0 && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bg border border-border">
          <div
            className="h-full rounded-full bg-accent transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      )}
      <div className="mt-2 text-[10px] text-muted truncate">
        deploy · {content.deploy_id}{progress > 0 ? ` · ${progress}%` : ""}
      </div>
    </div>
  );
}
