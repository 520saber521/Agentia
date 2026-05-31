import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { fetchArtifact } from "./api/client";
import { ArtifactEditor } from "./components/ArtifactEditor";
import { Composer } from "./components/Composer";
import { ToastContainer } from "./components/ToastContainer";
import { ConversationListPanel } from "./components/ConversationListPanel";
import { Header } from "./components/Header";
import { MessagePanel } from "./components/MessagePanel";
import { ContextSidebar } from "./components/ContextSidebar";
import { TabBar } from "./components/TabBar";
import { useAnimationStream } from "./hooks/useAnimationStream";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useChatStore } from "./stores/useChatStore";
import type { Artifact } from "./types";

export default function App() {
  const init = useChatStore((s) => s.init);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const sidebarOpen = useChatStore((s) => s.sidebarOpen);
  const rightSidebarOpen = useChatStore((s) => s.rightSidebarOpen);
  const toggleSidebar = useChatStore((s) => s.toggleSidebar);
  const toggleRightSidebar = useChatStore((s) => s.toggleRightSidebar);

  const isDesktop = useMediaQuery("(min-width: 1024px)");

  const [editingArtifact, setEditingArtifact] = useState<Artifact | null>(null);
  const [editingConvId, setEditingConvId] = useState<string | null>(null);

  useEffect(() => {
    init();
  }, [init]);
  useAnimationStream(currentConvId);

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

  const showLeftSidebar = isDesktop || sidebarOpen;
  const showRightSidebar = isDesktop || rightSidebarOpen;

  return (
    <div className="h-full flex flex-col bg-bg text-fg">
      <Header />
      <main className="flex-1 grid grid-cols-1 min-h-0 overflow-hidden md:grid-cols-[18rem_minmax(0,1fr)] lg:grid-cols-[18rem_minmax(0,1fr)_16rem]">
        {/* Left sidebar — overlay on mobile/tablet */}
        <AnimatePresence>
          {showLeftSidebar && !isDesktop && (
            <>
              <motion.div
                className="fixed inset-0 z-20 bg-black/50 lg:hidden"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={toggleSidebar}
              />
              <motion.div
                className="fixed left-0 top-12 bottom-0 z-30 w-80 lg:hidden"
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ type: "tween", duration: 0.2 }}
              >
                <ConversationListPanel />
              </motion.div>
            </>
          )}
        </AnimatePresence>

        {/* Left sidebar — always visible on desktop */}
        {isDesktop && <ConversationListPanel />}

        {/* Main chat area */}
        <section className="min-w-0 flex flex-col min-h-0 bg-panel border-l border-border overflow-hidden">
          <TabBar />
          <MessagePanel onEditArtifact={handleEditArtifact} />
          <Composer />
        </section>

        {/* Right sidebar — render on desktop, overlay on tablet/mobile */}
        {showRightSidebar && (
          <AnimatePresence>
            {!isDesktop && (
              <>
                <motion.div
                  className="fixed inset-0 z-20 bg-black/50 lg:hidden"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  onClick={toggleRightSidebar}
                />
                <motion.div
                  className="fixed right-0 top-12 bottom-0 z-30 w-72 lg:hidden"
                  initial={{ x: "100%" }}
                  animate={{ x: 0 }}
                  exit={{ x: "100%" }}
                  transition={{ type: "tween", duration: 0.2 }}
                >
                  <ContextSidebar />
                </motion.div>
              </>
            )}
          </AnimatePresence>
        )}
        {isDesktop && <ContextSidebar />}
      </main>

      {editingArtifact && editingConvId && (
        <ArtifactEditor
          artifact={editingArtifact}
          conversationId={editingConvId}
          onClose={handleEditorClose}
          onSaved={handleEditorSaved}
        />
      )}

      <ToastContainer />
    </div>
  );
}
