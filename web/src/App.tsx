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
  const conversations = useChatStore((s) => s.conversations);

  const [editingArtifact, setEditingArtifact] = useState<Artifact | null>(null);
  const [editingConvId, setEditingConvId] = useState<string | null>(null);

  useEffect(() => {
    init();
  }, [init]);

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const isGroupChat = currentConv?.type === "group";

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
      <main className="flex-1 flex min-h-0">
        <ConversationListPanel />
        <section className="flex-1 flex flex-col min-h-0 bg-panel border-l border-border">
          <W4TestPanel />
          <MessagePanel onEditArtifact={handleEditArtifact} />
          <Composer />
        </section>
        {isGroupChat && <MemberPanel />}
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
