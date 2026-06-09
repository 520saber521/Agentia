import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchArtifact } from "./api/client";
import { ArtifactEditor } from "./components/ArtifactEditor";
import { AgentWorkspacePage } from "./components/AgentWorkspacePage";
import { Composer } from "./components/Composer";
import { ConversationListPanel } from "./components/ConversationListPanel";
import { Header } from "./components/Header";
import { MessagePanel } from "./components/MessagePanel";
import { ContextSidebar } from "./components/ContextSidebar";
import { TabBar } from "./components/TabBar";
import { useAnimationStream } from "./hooks/useAnimationStream";
import { useChatStore } from "./stores/useChatStore";
import type { Artifact } from "./types";

export default function App() {
  const init = useChatStore((s) => s.init);
  const currentConvId = useChatStore((s) => s.currentConvId);

  const [editingArtifact, setEditingArtifact] = useState<Artifact | null>(null);
  const [editingConvId, setEditingConvId] = useState<string | null>(null);
  const [showAgentWorkspace, setShowAgentWorkspace] = useState(false);
  const [leftPanelWidth, setLeftPanelWidth] = useState(288);
  const [rightPanelWidth, setRightPanelWidth] = useState(256);

  useEffect(() => {
    init();
  }, [init]);
  useAnimationStream(currentConvId);

  useEffect(() => {
    if (showAgentWorkspace) {
      setRightPanelWidth((width) => Math.max(width, 720));
    }
  }, [showAgentWorkspace]);

  const handleEditArtifact = useCallback(
    async (artifactId: string) => {
      setEditingArtifact(null);
      setEditingConvId(currentConvId);
      try {
        const artifact = await fetchArtifact(artifactId);
        setEditingArtifact(artifact);
      } catch {
        console.error("Failed to fetch artifact for editing");
      }
    },
    [currentConvId],
  );

  const handleEditorClose = useCallback(() => {
    setEditingArtifact(null);
    setEditingConvId(null);
  }, []);

  useEffect(() => {
    const handler = () => {
      if (currentConvId) void useChatStore.getState().selectConversation(currentConvId);
    };
    window.addEventListener("agenthub:artifact-applied", handler);
    return () => window.removeEventListener("agenthub:artifact-applied", handler);
  }, [currentConvId]);

  const handleEditorSaved = useCallback(
    (newArtifact: Artifact) => {
      setEditingArtifact(newArtifact);
      if (currentConvId) void useChatStore.getState().selectConversation(currentConvId);
    },
    [currentConvId],
  );

  const gridTemplateColumns = useMemo(
    () => `${leftPanelWidth}px 6px minmax(0,1fr) 6px ${rightPanelWidth}px`,
    [leftPanelWidth, rightPanelWidth],
  );

  const startResize = useCallback(
    (side: "left" | "right", event: React.PointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const startX = event.clientX;
      const startLeftWidth = leftPanelWidth;
      const startRightWidth = rightPanelWidth;

      function handleMove(moveEvent: PointerEvent) {
        if (side === "left") {
          const next = Math.min(420, Math.max(220, startLeftWidth + moveEvent.clientX - startX));
          setLeftPanelWidth(next);
        } else {
          const maxRightWidth = Math.max(420, window.innerWidth - leftPanelWidth - 360);
          const next = Math.min(maxRightWidth, Math.max(280, startRightWidth - (moveEvent.clientX - startX)));
          setRightPanelWidth(next);
        }
      }

      function handleUp() {
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        window.removeEventListener("pointermove", handleMove);
        window.removeEventListener("pointerup", handleUp);
      }

      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("pointermove", handleMove);
      window.addEventListener("pointerup", handleUp);
    },
    [leftPanelWidth, rightPanelWidth],
  );

  return (
    <div className="h-full flex flex-col bg-bg text-fg">
      <Header
        showAgentWorkspace={showAgentWorkspace}
        onToggleAgentWorkspace={() => setShowAgentWorkspace((v) => !v)}
      />
      <main
        className="flex-1 grid min-h-0 overflow-hidden"
        style={{ gridTemplateColumns }}
      >
        <ConversationListPanel />

        {/* Left resize handle */}
        <div
          onPointerDown={(e) => startResize("left", e)}
          className="relative z-10 w-[6px] cursor-col-resize transition-colors hover:bg-accent/60 active:bg-accent"
        >
          <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border" />
        </div>

        <section className="min-w-0 flex flex-col min-h-0 bg-panel overflow-hidden">
          <TabBar />
          <MessagePanel onEditArtifact={handleEditArtifact} />
          <Composer />
        </section>

        {/* Right resize handle */}
        <div
          onPointerDown={(e) => startResize("right", e)}
          className="relative z-10 w-[6px] cursor-col-resize transition-colors hover:bg-accent/60 active:bg-accent"
        >
          <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border" />
        </div>

        <aside className="min-w-0 overflow-hidden border-l border-border bg-panel">
          {showAgentWorkspace ? (
            <AgentWorkspacePage
              onClose={() => setShowAgentWorkspace(false)}
              onEditArtifact={handleEditArtifact}
            />
          ) : (
            <ContextSidebar />
          )}
        </aside>
      </main>

      {editingArtifact && editingConvId && (
        <ArtifactEditor
          artifact={editingArtifact}
          conversationId={editingConvId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}
    </div>
  );
}
