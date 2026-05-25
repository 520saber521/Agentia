import { useMemo } from "react";
import type { Task } from "../types";

interface Props {
  tasks: Task[];
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  planning: { label: "规划中", color: "text-sky-400 border-sky-500/40 bg-sky-500/10", icon: "●" },
  pending: { label: "待处理", color: "text-amber-400 border-amber-500/40 bg-amber-500/10", icon: "○" },
  running: { label: "执行中", color: "text-blue-400 border-blue-500/40 bg-blue-500/10", icon: "◉" },
  done: { label: "已完成", color: "text-emerald-400 border-emerald-500/40 bg-emerald-500/10", icon: "●" },
  failed: { label: "失败", color: "text-red-400 border-red-500/40 bg-red-500/10", icon: "✕" },
  blocked: { label: "阻塞", color: "text-rose-400 border-rose-500/40 bg-rose-500/10", icon: "⏸" },
  conflict: { label: "冲突", color: "text-orange-400 border-orange-500/40 bg-orange-500/10", icon: "⚡" },
};

const PHASE_LABELS: Record<string, string> = {
  planning: "正在拆解任务",
  pending: "任务已创建",
  running: "多 Agent 协作中",
  done: "全部完成",
  failed: "部分失败",
  blocked: "存在阻塞",
};

export function CollaborationProgressCard({ tasks }: Props) {
  const {
    parentTask,
    subtasks,
    planningTask,
    taskMap,
    completedCount,
    phase,
  } = useMemo(() => {
    const taskMap = new Map<string, Task>();
    for (const t of tasks) {
      taskMap.set(t.id, t);
    }

    const planningTask = tasks.find((t) => t.id === "planning" && t.status === "planning");

    const parentTask = tasks.find(
      (t) => t.id !== "planning" && (t.parent_task_id === null || !t.parent_task_id)
    );

    const subtasks = parentTask
      ? tasks.filter((t) => t.parent_task_id === parentTask.id)
      : [];

    subtasks.sort((a, b) => a.created_at - b.created_at);

    const completedCount = subtasks.filter((t) => t.status === "done").length;

    let phase: string;
    if (planningTask && subtasks.length === 0) {
      phase = "planning";
    } else if (parentTask) {
      phase = parentTask.status;
    } else {
      phase = "pending";
    }

    return {
      parentTask,
      subtasks,
      planningTask,
      taskMap,
      completedCount,
      phase,
    };
  }, [tasks]);

  if (!parentTask && !planningTask) return null;

  if (subtasks.length === 0 && !planningTask) return null;

  const phaseLabel = PHASE_LABELS[phase] ?? phase;
  const phaseCfg = STATUS_CONFIG[phase] ?? STATUS_CONFIG.pending;

  return (
    <div className="animate-fade-in my-3 rounded-xl border border-border bg-panel/80 shadow-sm backdrop-blur">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-sm">
          🎯
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-fg truncate">
            多 Agent 协作调度
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-px text-[10px] font-medium border ${phaseCfg.color}`}>
              <span className="text-[8px]">{phaseCfg.icon}</span>
              {phaseLabel}
            </span>
            {subtasks.length > 0 && (
              <span className="text-[10px] text-muted">
                {completedCount}/{subtasks.length} 子任务
              </span>
            )}
          </div>
        </div>
        {phase === "running" && (
          <div className="flex items-center gap-2 shrink-0">
            <div className="h-1.5 w-1.5 animate-blink rounded-full bg-blue-400" />
            <span className="text-[10px] text-muted">调度中</span>
          </div>
        )}
        {phase === "planning" && (
          <div className="flex items-center gap-2 shrink-0">
            <div className="h-1.5 w-1.5 animate-blink rounded-full bg-sky-400" />
            <span className="text-[10px] text-muted">思考中</span>
          </div>
        )}
      </div>

      {/* Planning phase placeholder */}
      {phase === "planning" && subtasks.length === 0 && (
        <div className="px-4 py-4">
          <div className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-bg/50 px-3 py-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-sky-500/15 text-[10px] text-sky-400">
              🧭
            </div>
            <div className="text-xs text-muted">
              Orchestrator 正在分析需求、拆解子任务并分配 Agent…
            </div>
          </div>
        </div>
      )}

      {/* Subtask list */}
      {subtasks.length > 0 && (
        <div className="px-3 py-2">
          {subtasks.map((task, idx) => {
            const cfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.pending;
            const isRunning = task.status === "running";
            const isBlocked = task.status === "blocked";

            const blockingDeps = (task.depends_on ?? [])
              .map((depId) => taskMap.get(depId))
              .filter((dep): dep is Task => dep != null && dep.status !== "done");

            return (
              <div
                key={task.id}
                className={`flex items-start gap-3 rounded-lg px-2 py-2 transition-colors ${
                  isRunning ? "bg-blue-500/5" : ""
                }`}
              >
                {/* Step number */}
                <div
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-medium ${
                    task.status === "done"
                      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
                      : task.status === "running"
                        ? "border-blue-500/50 bg-blue-500/15 text-blue-400"
                        : task.status === "failed"
                          ? "border-red-500/40 bg-red-500/10 text-red-400"
                          : task.status === "blocked"
                            ? "border-rose-500/40 bg-rose-500/10 text-rose-400"
                            : "border-border bg-bg text-muted"
                  }`}
                >
                  {task.status === "done" ? "✓" : idx + 1}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium text-fg truncate max-w-[16rem]">
                      {task.title}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[10px] font-medium border ${cfg.color}`}
                    >
                      {cfg.icon} {cfg.label}
                    </span>
                  </div>

                  {task.agent_name && (
                    <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted">
                      <span className="text-accent">🤖</span>
                      <span>{task.agent_name}</span>
                      {task.domain && (
                        <>
                          <span className="text-border">·</span>
                          <span className="text-muted/70">{task.domain}</span>
                        </>
                      )}
                    </div>
                  )}

                  {/* Blocked dependency hint */}
                  {isBlocked && blockingDeps.length > 0 && (
                    <div className="mt-1 flex items-center gap-1.5 rounded border border-rose-500/20 bg-rose-500/5 px-2 py-0.5 text-[10px] text-rose-400/80">
                      <span>↳</span>
                      <span>等待依赖完成：</span>
                      {blockingDeps.map((dep, di) => (
                        <span key={dep.id} className="font-medium text-rose-300">
                          {dep.title.length > 20
                            ? dep.title.slice(0, 18) + "…"
                            : dep.title}
                          {di < blockingDeps.length - 1 ? "," : ""}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Running progress */}
                  {isRunning && task.progress_pct > 0 && (
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="h-1 flex-1 rounded-full bg-border overflow-hidden">
                        <div
                          className="h-full rounded-full bg-blue-500/60 transition-all duration-500"
                          style={{ width: `${task.progress_pct}%` }}
                        />
                      </div>
                      <span className="text-[10px] text-muted tabular-nums">
                        {task.progress_pct}%
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Footer summary */}
      {subtasks.length > 0 && (
        <div className="border-t border-border px-4 py-2">
          <div className="flex items-center justify-between text-[10px]">
            <span className="text-muted">
              {completedCount === subtasks.length
                ? "✅ 全部子任务已完成"
                : `进度 ${completedCount}/${subtasks.length}`}
            </span>
            {/* Mini progress bar */}
            <div className="flex items-center gap-2">
              <div className="flex gap-0.5">
                {subtasks.map((task) => {
                  const cfg = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.pending;
                  return (
                    <div
                      key={task.id}
                      className={`h-1 w-3 rounded-sm ${
                        task.status === "done"
                          ? "bg-emerald-500/60"
                          : task.status === "running"
                            ? "bg-blue-500/60"
                            : task.status === "failed"
                              ? "bg-red-500/60"
                              : task.status === "blocked"
                                ? "bg-rose-500/60"
                                : "bg-border"
                      }`}
                      title={`${task.title}: ${cfg.label}`}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
