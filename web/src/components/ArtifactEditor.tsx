import { useCallback, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";

import { fetchArtifactContent, saveArtifactVersion, describeApiError } from "../api/client";
import type { Artifact } from "../types";
import { VersionHistoryPanel } from "./VersionHistoryPanel";
import { formatHtml } from "../formatHtml";

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
  const [originalContent, setOriginalContent] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [currentArtifact, setCurrentArtifact] = useState(artifact);
  const [showHistory, setShowHistory] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setCurrentArtifact(artifact);
  }, [artifact]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSaveStatus("idle");
    setSaveError(null);

    fetchArtifactContent(currentArtifact.id)
      .then((c) => {
        if (!cancelled) {
          const formatted = language === "html" ? formatHtml(c) : c;
          setContent(formatted);
          setOriginalContent(formatted);
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
  }, [currentArtifact.id]);

  const hasChanges = content !== null && content !== originalContent;

  const handleSave = useCallback(async () => {
    if (content === null) return;
    setSaveStatus("saving");
    setSaveError(null);

    try {
      const newArtifact = await saveArtifactVersion({
        conversation_id: conversationId,
        kind: currentArtifact.kind,
        title: currentArtifact.title,
        mime_type: currentArtifact.mime_type,
        file_name: currentArtifact.file_name ?? undefined,
        content,
        parent_id: currentArtifact.id,
        meta: currentArtifact.meta,
      });
      setCurrentArtifact(newArtifact);
      setOriginalContent(content);
      setSaveStatus("success");
      onSaved(newArtifact);
    } catch (err) {
      setSaveStatus("error");
      setSaveError(describeApiError(err));
    }
  }, [content, conversationId, currentArtifact, onSaved]);

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

  const language = detectLanguage(currentArtifact);

  const handleSelectVersion = useCallback(async (versionArtifactId: string, _versionNumber: number) => {
    try {
      setLoading(true);
      setLoadError(null);
      const c = await fetchArtifactContent(versionArtifactId);
      const formatted = language === "html" ? formatHtml(c) : c;
      setContent(formatted);
      setOriginalContent(formatted);
      setLoading(false);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "版本加载失败");
      setLoading(false);
    }
  }, [language]);

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
            {currentArtifact.title}
          </span>
          <span className="text-[10px] text-muted shrink-0">
            v{currentArtifact.version}
          </span>
          <span className="text-[10px] text-muted shrink-0">
            {language}
          </span>
          {hasChanges && (
            <span className="text-[10px] text-amber-400 bg-amber-500/10 px-1.5 py-0.5 rounded">
              未保存的修改
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {saveStatus === "success" && (
            <span className="text-xs text-emerald-400/80">已保存</span>
          )}
          {saveStatus === "error" && (
            <span className="text-xs text-red-500/80 max-w-64 truncate" title={saveError ?? ""}>
              保存失败：{saveError ?? "可重试"}
            </span>
          )}
          <button
            type="button"
            onClick={() => setShowHistory(!showHistory)}
            className={`px-2.5 py-1.5 text-[11px] font-medium rounded-md border transition-colors ${
              showHistory
                ? "border-accent/30 text-accent bg-accent/5"
                : "border-border text-muted hover:text-fg hover:bg-bg"
            }`}
          >
            版本历史
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveStatus === "saving" || content === null || !hasChanges}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saveStatus === "saving" ? "保存中…" : hasChanges ? "保存 (Ctrl+S)" : "已是最新"}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex">
        {/* Editor area */}
        <div className="flex-1 min-w-0">
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

        {/* Version history sidebar */}
        {showHistory && (
          <div className="w-72 border-l border-border bg-panel flex flex-col min-h-0">
            <VersionHistoryPanel
              artifactId={currentArtifact.id}
              currentVersion={currentArtifact.version || 1}
              onSelectVersion={handleSelectVersion}
            />
          </div>
        )}
      </div>
    </div>
  );
}
