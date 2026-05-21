import { useEffect } from "react";

import { Composer } from "./components/Composer";
import { ConversationListPanel } from "./components/ConversationListPanel";
import { Header } from "./components/Header";
import { MemberPanel } from "./components/MemberPanel";
import { MessagePanel } from "./components/MessagePanel";
import { useChatStore } from "./stores/useChatStore";

export default function App() {
  const init = useChatStore((s) => s.init);
  const currentConvId = useChatStore((s) => s.currentConvId);
  const conversations = useChatStore((s) => s.conversations);

  useEffect(() => {
    init();
  }, [init]);

  const currentConv = conversations.find((c) => c.id === currentConvId);
  const isGroupChat = currentConv?.type === "group";

  return (
    <div className="h-full flex flex-col bg-bg text-fg">
      <Header />
      <main className="flex-1 flex min-h-0">
        <ConversationListPanel />
        <section className="flex-1 flex flex-col min-h-0 bg-panel border-l border-border">
          <MessagePanel />
          <Composer />
        </section>
        {isGroupChat && <MemberPanel />}
      </main>
    </div>
  );
}
