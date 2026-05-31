import React, { useMemo } from "react";
import type { Task } from "../types";
import {
  Target,
  Compass,
  Bot,
  CheckCircle2,
  Check,
  X,
  Circle,
  CircleDot,
  Play,
  Pause,
  Zap,
  CornerDownRight,
} from "./icons";

interface Props {
  tasks: Task[];
}

interface StatusConfig {
  label: string;
  cls: string;
  icon: React.ReactNode;
}

function statusConfig(status: string): StatusConfig {
  switch (status) {
    case "planning":
      return { label: "规划中", cls: "text-info border-info/40 bg-info/10", icon: <CircleDot className="h-3 w-3" /> };
    case "pending":
      return { label: "待处理", cls: "text-warning border-warning/40 bg-warning/10", icon: <Circle className="h-3 w-3" /> };
    case "running":
      return { label: "执行中", cls: "text-accent border-accent/40 bg-accent/10", icon: <Play className="h-3 w-3" /> };
    case "done":
      return { label: "已完成", cls: "text-success border-success/40 bg-success/10", icon: <CheckCircle2 className="h-3 w-3" /> };
    case "failed":
      return { label: "失败", cls: "text-danger border-danger/40 bg-danger/10", icon: <X className="h-3 w-3" /> };
    case "blocked":
      return { label: "阻塞", cls: "text-danger border-danger/40 bg-danger/10", icon: <Pause className="h-3 w-3" /> };
    case "conflict":
      return { label: "冲突", cls: "text-warning border-warning/40 bg-warning/10", icon: <Zap className="h-3 w-3" /> };
    default:
      return { label: status, cls: "text-muted border-border bg-bg", icon: <Circle className="h-3 w-3" /> };
  }
}

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
  const phaseCfg = statusConfig(phase);

  return (
    <div className="animate-fade-in my-3 rounded-xl border border-border bg-panel/80 shadow-card-sm backdrop-blur">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/15 text-accent">
          <Target className="h-4 w-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-fg truncate">
            多 Agent 协作调度
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-px text-3xs font-medium border ${phaseCfg.cls}`}>
              {phaseCfg.icon}
              <span className="ml-0.5">{phaseLabel}</span>
            </span>
            {subtasks.length > 0 && (
              <span className="text-3xs text-muted">
                {completedCount}/{subtasks.length} 子任务
              </span>
            )}
          </div>
        </div>
        {phase === "running" && (
          <div className="flex items-center gap-2 shrink-0">
            <div className="h-1.5 w-1.5 animate-blink rounded-full bg-accent" />
            <span className="text-3xs text-muted">调度中</span>
          </div>
        )}
        {phase === "planning" && (
          <div className="flex items-center gap-2 shrink-0">
            <div className="h-1.5 w-1.5 animate-blink rounded-full bg-info" />
            <span className="text-3xs text-muted">思考中</span>
          </div>
        )}
      </div>

      {/* Planning phase placeholder */}
      {phase === "planning" && subtasks.length === 0 && (
        <div className="px-4 py-4">
          <div className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-bg/50 px-3 py-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-info/15 text-info">
              <Compass className="h-3.5 w-3.5" />
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
            const cfg = statusConfig(task.status);
            const isRunning = task.status === "running";
            const isBlocked = task.status === "blocked";

            const blockingDeps = (task.depends_on ?? [])
              .map((depId) => taskMap.get(depId))
              .filter((dep): dep is Task => dep != null && dep.status !== "done");

            return (
              <div
                key={task.id}
                className={`flex items-start gap-3 rounded-lg px-2 py-2 transition-colors ${
                  isRunning ? "bg-accent/5" : ""
                }`}
              >
                {/* Step number */}
                <div
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-3xs font-medium ${
                    task.status === "done"
                      ? "border-success/40 bg-success/10 text-success"
                      : task.status === "running"
                        ? "border-accent/50 bg-accent/15 text-accent"
                        : task.status === "failed"
                          ? "border-danger/40 bg-danger/10 text-danger"
                          : task.status === "blocked"
                            ? "border-danger/40 bg-danger/10 text-danger"
                            : "border-border bg-bg text-muted"
                  }`}
                >
                  {task.status === "done" ? <Check className="h-3 w-3" /> : idx + 1}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-medium text-fg truncate max-w-[16rem]">
                      {task.title}
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-1.5 py-px text-3xs font-medium border ${cfg.cls}`}
                    >
                      {cfg.icon} {cfg.label}
                    </span>
                  </div>

                  {task.agent_name && (
                    <div className="mt-0.5 flex items-center gap-1 text-3xs text-muted">
                      <Bot className="h-3 w-3 text-accent" />
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
                    <div className="mt-1 flex items-center gap-1.5 rounded border border-danger/20 bg-danger/5 px-2 py-0.5 text-3xs text-danger/80">
                      <CornerDownRight className="h-3 w-3" />
                      <span>等待依赖完成：</span>
                      {blockingDeps.map((dep, di) => (
                        <span key={dep.id} className="font-medium text-danger/80">
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
                          className="h-full rounded-full bg-accent/60 transition-all duration-500"
                          style={{ width: `${task.progress_pct}%` }}
                        />
                      </div>
                      <span className="text-3xs text-muted tabular-nums">
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
          <div className="flex items-center justify-between text-3xs">
            <span className="text-muted">
              {completedCount === subtasks.length ? (
                <span className="inline-flex items-center gap-1">
                  <CheckCircle2 className="h-3 w-3 text-success" />
                  全部子任务已完成
                </span>
              ) : (
                `进度 ${completedCount}/${subtasks.length}`
              )}
            </span>
            {/* Mini progress bar */}
            <div className="flex items-center gap-2">
              <div className="flex gap-0.5">
                {subtasks.map((task) => {
                  const cfg = statusConfig(task.status);
                  return (
                    <div
                      key={task.id}
                      className={`h-1 w-3 rounded-sm ${
                        task.status === "done"
                          ? "bg-success/60"
                          : task.status === "running"
                            ? "bg-accent/60"
                            : task.status === "failed"
                              ? "bg-danger/60"
                              : task.status === "blocked"
                                ? "bg-danger/60"
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
