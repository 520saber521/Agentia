import { describe, expect, it } from "vitest";

import type { Message, ServerEvent } from "../types";
import { emptySlice, reduceEvent, type ChatSlice } from "./reducer";

/**
 * `reduceEvent` 是整个 IM 客户端的"消息流→状态"的单一真源。
 * 这里覆盖 W1 已开通的 7 种事件，每个事件都包含至少一个"边界场景"。
 */

function withConv(id: string): ChatSlice {
  return { ...emptySlice(), currentConvId: id };
}

function makeMessage(over: Partial<Message> = {}): Message {
  return {
    id: "msg_1",
    conversation_id: "conv_demo",
    sender_id: "user_demo",
    sender_type: "user",
    content_type: "text",
    content: { type: "text", text: "hello" },
    reply_to: null,
    mentions: [],
    pinned: false,
    artifact_id: null,
    agenthub_msg_id: null,
    created_at: 1_700_000_000_000,
    ...over,
  };
}

describe("reduceEvent — hello / 兜底", () => {
  it("hello 写入 serverInfo", () => {
    const evt: ServerEvent = {
      type: "hello",
      ts: 1,
      conn_id: "abc",
      server: "agenthub-bff/0.1",
    };
    const { next, effects } = reduceEvent(emptySlice(), evt);
    expect(next.serverInfo).toBe("agenthub-bff/0.1");
    expect(effects).toEqual([]);
  });

  it("未识别事件保持引用相等，不产生副作用", () => {
    const before = emptySlice();
    const evt = { type: "pong", ts: 0 } as unknown as ServerEvent;
    const { next, effects } = reduceEvent(before, evt);
    expect(next).toBe(before);
    expect(effects).toEqual([]);
  });
});

describe("reduceEvent — history", () => {
  it("只对当前会话生效", () => {
    const state = withConv("conv_demo");
    const msg = makeMessage();
    const { next } = reduceEvent(state, {
      type: "history",
      ts: 0,
      conversation_id: "conv_demo",
      messages: [msg],
      count: 1,
    });
    expect(next.messages).toEqual([msg]);
  });

  it("非当前会话的 history 被忽略", () => {
    const state = withConv("conv_demo");
    const { next } = reduceEvent(state, {
      type: "history",
      ts: 0,
      conversation_id: "conv_other",
      messages: [makeMessage({ conversation_id: "conv_other" })],
      count: 1,
    });
    expect(next).toBe(state);
  });
});

describe("reduceEvent — message_created", () => {
  it.each([
    ["text", { type: "text", text: "hello" }],
    ["code", { type: "code", code: "print(1)", language: "python" }],
    ["diff", { type: "diff", before: "a", after: "b", summary: "change" }],
    ["preview", { type: "preview", artifact_id: "art_1", title: "index.html", mimeType: "text/html" }],
    ["file", { type: "file", artifact_id: "art_2", fileName: "a.txt", mimeType: "text/plain" }],
    ["task_status", { type: "task_status", task_id: "task_1", status: "running", progress: 50 }],
    ["deploy_status", { type: "deploy_status", deploy_id: "dep_1", status: "done", url: "https://example.test" }],
  ] as const)("当前会话：追加 %s 内容消息", (_type, content) => {
    const state = withConv("conv_demo");
    const msg = makeMessage({ content, content_type: content.type });
    const { next } = reduceEvent(state, {
      type: "message_created",
      ts: 0,
      message: msg,
    });
    expect(next.messages[0].content).toEqual(content);
  });

  it("当前会话：追加用户消息，不改 streaming 标志", () => {
    const state = withConv("conv_demo");
    const msg = makeMessage();
    const { next, effects } = reduceEvent(state, {
      type: "message_created",
      ts: 0,
      message: msg,
    });
    expect(next.messages).toEqual([msg]);
    expect(next.streamingMessageIds).toEqual([]);
    expect(next.agentTyping).toBe(false);
    expect(effects).toEqual([]);
  });

  it("当前会话：agent 消息进来时 streamingMessageIds 追加并清掉 typing", () => {
    const state: ChatSlice = { ...withConv("conv_demo"), agentTyping: true };
    const msg = makeMessage({
      id: "msg_agent",
      sender_id: "agent_mock",
      sender_type: "agent",
      content: { type: "text", text: "" },
    });
    const { next } = reduceEvent(state, {
      type: "message_created",
      ts: 0,
      message: msg,
    });
    expect(next.streamingMessageIds).toEqual(["msg_agent"]);
    expect(next.agentTyping).toBe(false);
  });

  it("W2 fan-out：N 条 agent 占位消息时 streamingMessageIds 累加而非覆盖", () => {
    const state = withConv("conv_demo");
    const a = makeMessage({
      id: "msg_a",
      sender_id: "agent_claude",
      sender_type: "agent",
      content: { type: "text", text: "" },
    });
    const b = makeMessage({
      id: "msg_b",
      sender_id: "agent_codex",
      sender_type: "agent",
      content: { type: "text", text: "" },
    });
    const r1 = reduceEvent(state, {
      type: "message_created",
      ts: 0,
      message: a,
    });
    const r2 = reduceEvent(r1.next, {
      type: "message_created",
      ts: 1,
      message: b,
    });
    expect(r2.next.streamingMessageIds).toEqual(["msg_a", "msg_b"]);
    expect(r2.next.messages.map((m) => m.id)).toEqual(["msg_a", "msg_b"]);
  });

  it("非当前会话：状态不变，但产生 refresh 副作用", () => {
    const state = withConv("conv_demo");
    const msg = makeMessage({ conversation_id: "conv_other" });
    const { next, effects } = reduceEvent(state, {
      type: "message_created",
      ts: 0,
      message: msg,
    });
    expect(next).toBe(state);
    expect(effects).toEqual(["refresh_conversations"]);
  });

  it("重复 message_id 不会被追加（防止 history + message_created 双写）", () => {
    const msg = makeMessage();
    const state: ChatSlice = { ...withConv("conv_demo"), messages: [msg] };
    const { next } = reduceEvent(state, {
      type: "message_created",
      ts: 0,
      message: msg,
    });
    expect(next).toBe(state);
  });
});

describe("reduceEvent — agent_typing & stream_chunk", () => {
  it("agent_typing 命中当前会话时翻开 typing 标志", () => {
    const state = withConv("conv_demo");
    const { next } = reduceEvent(state, {
      type: "agent_typing",
      ts: 0,
      agent_id: "agent_mock",
      conversation_id: "conv_demo",
    });
    expect(next.agentTyping).toBe(true);
  });

  it("stream_chunk 拼到目标消息上", () => {
    const placeholder = makeMessage({
      id: "msg_agent",
      sender_type: "agent",
      sender_id: "agent_mock",
      content: { type: "text", text: "Hi" },
    });
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      messages: [placeholder],
      streamingMessageIds: ["msg_agent"],
    };
    const { next } = reduceEvent(state, {
      type: "stream_chunk",
      ts: 0,
      message_id: "msg_agent",
      conversation_id: "conv_demo",
      seq: 1,
      delta: ", world",
    });
    expect(next.messages[0].content).toEqual({
      type: "text",
      text: "Hi, world",
    });
    // 没动到流式状态
    expect(next.streamingMessageIds).toEqual(["msg_agent"]);
  });

  it("W2 fan-out：stream_chunk 只影响目标气泡，兄弟流式状态保留", () => {
    const a = makeMessage({
      id: "msg_a",
      sender_type: "agent",
      sender_id: "agent_claude",
      content: { type: "text", text: "" },
    });
    const b = makeMessage({
      id: "msg_b",
      sender_type: "agent",
      sender_id: "agent_codex",
      content: { type: "text", text: "" },
    });
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      messages: [a, b],
      streamingMessageIds: ["msg_a", "msg_b"],
    };
    const { next } = reduceEvent(state, {
      type: "stream_chunk",
      ts: 0,
      message_id: "msg_a",
      sender_id: "agent_claude",
      conversation_id: "conv_demo",
      seq: 1,
      delta: "hello",
    });
    expect((next.messages[0].content as { text: string }).text).toBe("hello");
    expect((next.messages[1].content as { text: string }).text).toBe("");
    expect(next.streamingMessageIds).toEqual(["msg_a", "msg_b"]);
  });

  it("stream_chunk 找不到对应 message 时静默忽略", () => {
    const state = withConv("conv_demo");
    const { next } = reduceEvent(state, {
      type: "stream_chunk",
      ts: 0,
      message_id: "nope",
      conversation_id: "conv_demo",
      seq: 1,
      delta: "x",
    });
    expect(next).toBe(state);
  });
});

describe("reduceEvent — message_done / cancelled / error", () => {
  it.each([
    ["text", { type: "text", text: "final reply" }],
    ["code", { type: "code", code: "print(1)", language: "python" }],
    ["diff", { type: "diff", before: "a", after: "b" }],
    ["preview", { type: "preview", artifact_id: "art_1", title: "index.html", mimeType: "text/html" }],
    ["file", { type: "file", artifact_id: "art_2", fileName: "a.txt", mimeType: "text/plain" }],
    ["task_status", { type: "task_status", task_id: "task_1", status: "done", progress: 100 }],
    ["deploy_status", { type: "deploy_status", deploy_id: "dep_1", status: "done" }],
  ] as const)("message_done 覆盖为 %s content", (_type, final_content) => {
    const placeholder = makeMessage({
      id: "msg_agent",
      sender_type: "agent",
      content: { type: "text", text: "partial" },
    });
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      messages: [placeholder],
      streamingMessageIds: ["msg_agent"],
      agentTyping: true,
    };
    const { next } = reduceEvent(state, {
      type: "message_done",
      ts: 0,
      message_id: "msg_agent",
      conversation_id: "conv_demo",
      final_content,
    });
    expect(next.messages[0].content).toEqual(final_content);
    expect(next.streamingMessageIds).toEqual([]);
  });

  it("message_done 用 final_content 覆盖，并从 streamingMessageIds 移除、触发 refresh", () => {
    const placeholder = makeMessage({
      id: "msg_agent",
      sender_type: "agent",
      content: { type: "text", text: "partial" },
    });
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      messages: [placeholder],
      streamingMessageIds: ["msg_agent"],
      agentTyping: true,
    };
    const { next, effects } = reduceEvent(state, {
      type: "message_done",
      ts: 0,
      message_id: "msg_agent",
      conversation_id: "conv_demo",
      final_content: { type: "text", text: "final reply" },
    });
    expect(next.messages[0].content).toEqual({
      type: "text",
      text: "final reply",
    });
    expect(next.streamingMessageIds).toEqual([]);
    expect(next.agentTyping).toBe(false);
    expect(effects).toEqual(["refresh_conversations"]);
  });

  it("W2 fan-out：单条 done 只移除自己，兄弟仍在流", () => {
    const a = makeMessage({
      id: "msg_a",
      sender_type: "agent",
      content: { type: "text", text: "a partial" },
    });
    const b = makeMessage({
      id: "msg_b",
      sender_type: "agent",
      content: { type: "text", text: "b partial" },
    });
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      messages: [a, b],
      streamingMessageIds: ["msg_a", "msg_b"],
      agentTyping: true,
    };
    const { next } = reduceEvent(state, {
      type: "message_done",
      ts: 0,
      message_id: "msg_a",
      conversation_id: "conv_demo",
      final_content: { type: "text", text: "a final" },
    });
    expect(next.streamingMessageIds).toEqual(["msg_b"]);
    // 兄弟还在流时不能清 typing
    expect(next.agentTyping).toBe(true);
    expect((next.messages[0].content as { text: string }).text).toBe("a final");
    expect((next.messages[1].content as { text: string }).text).toBe(
      "b partial",
    );
  });

  it("message_cancelled 行为与 done 一致（也从 streamingMessageIds 移除）", () => {
    const placeholder = makeMessage({
      id: "msg_agent",
      sender_type: "agent",
      content: { type: "text", text: "half" },
    });
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      messages: [placeholder],
      streamingMessageIds: ["msg_agent"],
    };
    const { next } = reduceEvent(state, {
      type: "message_cancelled",
      ts: 0,
      message_id: "msg_agent",
      conversation_id: "conv_demo",
      final_content: { type: "text", text: "half[cancelled]" },
    });
    expect(next.messages[0].content).toEqual({
      type: "text",
      text: "half[cancelled]",
    });
    expect(next.streamingMessageIds).toEqual([]);
  });

  it("error 命中流式列表时只移除该条；兄弟仍在流", () => {
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      streamingMessageIds: ["msg_a", "msg_b"],
      agentTyping: true,
    };
    const { next } = reduceEvent(state, {
      type: "error",
      ts: 0,
      code: "adapter_crash",
      message: "...",
      message_id: "msg_a",
    });
    expect(next.streamingMessageIds).toEqual(["msg_b"]);
    expect(next.agentTyping).toBe(true);
  });

  it("error 命中唯一流式消息时清 typing", () => {
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      streamingMessageIds: ["msg_agent"],
      agentTyping: true,
    };
    const { next } = reduceEvent(state, {
      type: "error",
      ts: 0,
      code: "bad_json",
      message: "...",
      message_id: "msg_agent",
    });
    expect(next.streamingMessageIds).toEqual([]);
    expect(next.agentTyping).toBe(false);
  });

  it("无关 error 不动状态", () => {
    const state: ChatSlice = {
      ...withConv("conv_demo"),
      streamingMessageIds: ["msg_agent"],
    };
    const { next } = reduceEvent(state, {
      type: "error",
      ts: 0,
      code: "x",
      message: "x",
    });
    expect(next).toBe(state);
  });
});
