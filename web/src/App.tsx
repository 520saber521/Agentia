import { useCallback, useEffect, useState } from "react";

import { fetchArtifact } from "./api/client";
import { ArtifactEditor } from "./components/ArtifactEditor";
import { Composer } from "./components/Composer";
import { ConversationListPanel } from "./components/ConversationListPanel";
import { Header } from "./components/Header";
import { MemberPanel } from "./components/MemberPanel";
import { MessagePanel } from "./components/MessagePanel";
import { W4TestPanel } from "./components/W4TestPanel";
import { useChatStore } from "./stores/useChatStore";
import type { Artifact } from "./types";

export default function App() {
  const init = useChatStore((s) => s.init);
  const currentConvId = useChatStore((s) => s.currentConvId);

  const [editingArtifact, setEditingArtifact] = useState<Artifact | null>(null);
  const [editingConvId, setEditingConvId] = useState<string | null>(null);

  useEffect(() => {
    init();
  }, [init]);

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

  return (
    <div className="h-full flex flex-col bg-bg text-fg">
      <Header />
      <main className="flex-1 grid grid-cols-[18rem_minmax(0,1fr)_16rem] min-h-0 overflow-hidden">
        <ConversationListPanel />
        <section className="min-w-0 flex flex-col min-h-0 bg-panel border-l border-border overflow-hidden">
          <W4TestPanel />
          <MessagePanel onEditArtifact={handleEditArtifact} />
          <Composer />
        </section>
        <MemberPanel />
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
