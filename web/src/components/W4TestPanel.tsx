import { useMemo, useState } from "react";

import {
  createArtifactMessage,
  createInvalidContentProbe,
  describeApiError,
  fetchArtifactHistory,
  saveArtifactVersion,
} from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { Artifact } from "../types";

type TestStatus = "idle" | "running" | "success" | "error";

interface ActionState {
  status: TestStatus;
  message: string;
}

const INITIAL_STATE: ActionState = { status: "idle", message: "选择一个操作开始测试" };

function statusClass(status: TestStatus): string {
  if (status === "success") return "text-emerald-300 border-emerald-500/30 bg-emerald-500/10";
  if (status === "error") return "text-red-300 border-red-500/30 bg-red-500/10";
  if (status === "running") return "text-sky-300 border-sky-500/30 bg-sky-500/10";
  return "text-muted border-border bg-bg/60";
}

export function W4TestPanel() {
  const currentConvId = useChatStore((s) => s.currentConvId);
  const selectConversation = useChatStore((s) => s.selectConversation);
  const [state, setState] = useState<ActionState>(INITIAL_STATE);
  const [latestPreview, setLatestPreview] = useState<Artifact | null>(null);
  const [history, setHistory] = useState<Artifact[]>([]);

  const disabled = !currentConvId || state.status === "running";

  const currentLabel = useMemo(() => {
    if (!currentConvId) return "请先选择会话";
    return `当前会话：${currentConvId}`;
  }, [currentConvId]);

  async function runAction(label: string, action: () => Promise<string>) {
    setState({ status: "running", message: `${label} 执行中…` });
    try {
      const message = await action();
      setState({ status: "success", message });
      if (currentConvId) await selectConversation(currentConvId);
    } catch (err) {
      setState({ status: "error", message: describeApiError(err) });
    }
  }

  async function createCodeCard() {
    if (!currentConvId) return;
    await runAction("代码卡片", async () => {
      const result = await createArtifactMessage({
        conversation_id: currentConvId,
        kind: "code",
        title: "w4-demo.ts",
        mime_type: "text/typescript",
        file_name: "w4-demo.ts",
        content: "// 代码卡片测试\n// 请通过 @Orchestrator 触发真实 Agent 来生成实际代码。\nexport function placeholder() {\n  return \"等待模型输出\";\n}\n",
        meta: { language: "typescript" },
      });
      return `已生成代码卡片：${result.artifact.title}`;
    });
  }

  async function createPreviewCard() {
    if (!currentConvId) return;
    await runAction("网页预览", async () => {
      const result = await createArtifactMessage({
        conversation_id: currentConvId,
        kind: "preview",
        title: "模型生成预览",
        mime_type: "text/html",
        file_name: "index.html",
        content: "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>等待模型输出</title></head><body style=\"margin:0;min-height:100vh;display:grid;place-items:center;background:#101828;color:#f8fafc;font-family:system-ui,sans-serif\"><main style=\"text-align:center;padding:32px\"><p style=\"color:#cbd5e1\">此预览需要通过 @Orchestrator 触发真实模型生成。请在聊天中发送 @Orchestrator + 你的需求来获得动态生成的预览页面。</p></main></body></html>",
      });
      setLatestPreview(result.artifact);
      setHistory([]);
      return `已生成预览卡片：${result.artifact.title}`;
    });
  }

  async function createFileCard() {
    if (!currentConvId) return;
    await runAction("文件卡片", async () => {
      const result = await createArtifactMessage({
        conversation_id: currentConvId,
        kind: "file",
        title: "w4-report.txt",
        mime_type: "text/plain",
        file_name: "w4-report.txt",
        content: "文件卡片测试\n- 请通过 @Orchestrator 触发真实 Agent 来生成实际文件内容。\n",
      });
      return `已生成文件卡片：${result.artifact.file_name ?? result.artifact.title}`;
    });
  }

  async function createPreviewVersion() {
    if (!currentConvId || !latestPreview) return;
    setHistory([]);
    await runAction("版本链", async () => {
      const next = await saveArtifactVersion({
        conversation_id: currentConvId,
        kind: latestPreview.kind,
        title: latestPreview.title,
        mime_type: latestPreview.mime_type,
        file_name: latestPreview.file_name ?? "index.html",
        parent_id: latestPreview.id,
        content: "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>版本更新</title></head><body style=\"margin:0;min-height:100vh;display:grid;place-items:center;background:#101828;color:#f8fafc;font-family:system-ui,sans-serif\"><main style=\"text-align:center;padding:32px\"><p style=\"color:#cbd5e1\">预览版本已更新。请通过 @Orchestrator 触发真实模型生成来获得动态页面内容。</p></main></body></html>",
      });
      setLatestPreview(next);
      const versions = await fetchArtifactHistory(next.id);
      setHistory(versions);
      return `已保存 v${next.version}，版本链共 ${versions.length} 个版本`;
    });
  }

  async function testInvalidSchema() {
    await runAction("非法 schema", async () => {
      try {
        await createInvalidContentProbe();
      } catch (err) {
        return `服务端已拒绝非法内容：${describeApiError(err)}`;
      }
      throw new Error("非法内容没有被服务端拒绝");
    });
  }

  return (
    <div className="border-b border-border bg-bg/80 px-4 py-3 shadow-[0_10px_28px_rgba(0,0,0,0.16)]">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 mr-auto">
          <div className="text-xs uppercase tracking-[0.16em] text-accent font-semibold">
            W4 网页端验收面板
          </div>
          <div className="text-[11px] text-muted mt-0.5 truncate">
            {currentLabel} · 点击按钮后消息流会自动刷新，无需命令行
          </div>
        </div>
        <button
          type="button"
          disabled={disabled}
          onClick={() => void createCodeCard()}
          className="rounded-full border border-border px-3 py-1.5 text-xs text-fg hover:border-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          生成代码卡片
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => void createPreviewCard()}
          className="rounded-full border border-border px-3 py-1.5 text-xs text-fg hover:border-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          生成网页预览
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => void createFileCard()}
          className="rounded-full border border-border px-3 py-1.5 text-xs text-fg hover:border-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          生成文件卡片
        </button>
        <button
          type="button"
          disabled={disabled || !latestPreview}
          onClick={() => void createPreviewVersion()}
          className="rounded-full border border-border px-3 py-1.5 text-xs text-fg hover:border-accent hover:bg-accent/10 disabled:opacity-50 disabled:cursor-not-allowed transition"
          title={!latestPreview ? "请先生成网页预览" : undefined}
        >
          保存预览新版本
        </button>
        <button
          type="button"
          disabled={disabled}
          onClick={() => void testInvalidSchema()}
          className="rounded-full border border-red-500/30 px-3 py-1.5 text-xs text-red-200 hover:bg-red-500/10 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          测非法 schema
        </button>
      </div>
      <div className={`mt-3 rounded-lg border px-3 py-2 text-xs ${statusClass(state.status)}`}>
        {state.message}
        {history.length > 0 && (
          <span className="ml-2 text-muted">
            版本：{history.map((item) => `v${item.version}`).join(" → ")}
          </span>
        )}
      </div>
    </div>
  );
}
