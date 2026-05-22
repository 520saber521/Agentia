import { useCallback, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";

import { fetchArtifactContent, saveArtifactVersion } from "../api/client";
import type { Artifact } from "../types";

interface Props {
  artifact: Artifact;
  conversationId: string;
  onClose: () => void;
  onSaved: (newArtifact: Artifact) => void;
}

type SaveStatus = "idle" | "saving" | "success" | "error";

const LANGUAGE_MAP: Record<string, string> = {
  js: "javascript",
  ts: "typescript",
  tsx: "typescript",
  jsx: "javascript",
  py: "python",
  html: "html",
  css: "css",
  json: "json",
  md: "markdown",
  yaml: "yaml",
  yml: "yaml",
  xml: "xml",
  sql: "sql",
  sh: "shell",
  bash: "shell",
  rs: "rust",
  go: "go",
  java: "java",
  cpp: "cpp",
  c: "c",
};

function detectLanguage(artifact: Artifact): string {
  if (artifact.meta && typeof artifact.meta === "object") {
    const lang = (artifact.meta as Record<string, unknown>).language;
    if (typeof lang === "string") return lang;
  }
  return LANGUAGE_MAP[artifact.file_name?.split(".").pop() ?? ""] ?? "plaintext";
}

export function ArtifactEditor({ artifact, conversationId, onClose, onSaved }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);

    fetchArtifactContent(artifact.id)
      .then((c) => {
        if (!cancelled) {
          setContent(c);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "加载失败");
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  const handleSave = useCallback(async () => {
    if (!content || content === "") return;
    setSaveStatus("saving");
    setSaveError(null);

    try {
      const newArtifact = await saveArtifactVersion({
        conversation_id: conversationId,
        kind: artifact.kind,
        title: artifact.title,
        mime_type: artifact.mime_type,
        content,
        parent_id: artifact.id,
      });
      setSaveStatus("success");
      onSaved(newArtifact);
    } catch (err) {
      setSaveStatus("error");
      setSaveError(err instanceof Error ? err.message : "保存失败");
    }
  }, [content, conversationId, artifact, onSaved]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        void handleSave();
      }
    },
    [handleSave],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  const language = detectLanguage(artifact);

  return (
    <div
      ref={editorRef}
      className="fixed inset-0 z-50 flex flex-col bg-bg"
    >
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-panel shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-muted hover:text-fg transition-colors shrink-0"
          >
            ← 返回
          </button>
          <span className="w-px h-4 bg-border" />
          <span className="text-sm font-medium text-fg truncate">
            {artifact.title}
          </span>
          <span className="text-[10px] text-muted shrink-0">
            v{artifact.version}
          </span>
          <span className="text-[10px] text-muted shrink-0">
            {language}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {saveStatus === "success" && (
            <span className="text-xs text-green-500/80">已保存</span>
          )}
          {saveStatus === "error" && (
            <span className="text-xs text-red-500/80" title={saveError ?? ""}>
              保存失败
            </span>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={saveStatus === "saving" || content === null}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saveStatus === "saving" ? "保存中…" : "保存 (Ctrl+S)"}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        {loading && (
          <div className="flex items-center justify-center h-full text-sm text-muted">
            加载中…
          </div>
        )}
        {loadError && (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <div className="text-sm text-red-500/80">{loadError}</div>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="text-xs text-accent hover:underline"
            >
              重试
            </button>
          </div>
        )}
        {!loading && !loadError && content !== null && (
          <Editor
            height="100%"
            language={language}
            value={content}
            onChange={(v) => setContent(v ?? "")}
            theme="vs-dark"
            options={{
              fontSize: 13,
              fontFamily: "'JetBrains Mono', 'Cascadia Mono', 'Consolas', monospace",
              minimap: { enabled: true },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              wordWrap: "on",
              lineNumbers: "on",
              tabSize: 2,
              renderWhitespace: "selection",
              bracketPairColorization: { enabled: true },
              padding: { top: 12 },
            }}
          />
        )}
      </div>
    </div>
  );
}
