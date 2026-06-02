import { useEffect, useRef } from "react";

import { useChatStore } from "../stores/useChatStore";
import type { ServerEvent } from "../types";

export function useAnimationStream(conversationId: string | null) {
  const lastEventId = useRef("");

  useEffect(() => {
    if (!conversationId) return;
    lastEventId.current = "";

    const params = new URLSearchParams({ conversation_id: conversationId });
    if (lastEventId.current) params.set("after_id", lastEventId.current);

    const source = new EventSource(`/api/animation-stream?${params.toString()}`);

    const handle = (evt: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(evt.data) as ServerEvent & { event_id?: string };
        if (parsed.event_id) lastEventId.current = parsed.event_id;
        useChatStore.getState().applyServerEvent(parsed);
      } catch (err) {
        console.error("animation stream parse failed", err);
      }
    };

    source.addEventListener("anim_agent_created", handle);
    source.addEventListener("anim_agent_status", handle);
    source.addEventListener("anim_beam", handle);
    source.addEventListener("anim_event", handle);
    source.onerror = () => undefined;

    return () => {
      source.close();
    };
  }, [conversationId]);
}
