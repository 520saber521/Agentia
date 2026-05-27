import { useCallback, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";

import { fetchArtifactContent, fetchArtifactHistory, saveArtifactVersion, describeApiError } from "../api/client";
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
  const [currentArtifact, setCurrentArtifact] = useState(artifact);
  const editorRef = useRef<HTMLDivElement>(null);

  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<Artifact[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [viewingVersion, setViewingVersion] = useState<Artifact | null>(null);
  const [isReadonly, setIsReadonly] = useState(false);

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
  }, [currentArtifact.id]);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const items = await fetchArtifactHistory(currentArtifact.id);
      setHistory(items);
    } catch (err) {
      setHistoryError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setHistoryLoading(false);
    }
  }, [currentArtifact.id]);

  const handleViewVersion = useCallback(async (version: Artifact) => {
    try {
      const c = await fetchArtifactContent(version.id);
      setContent(c);
      setViewingVersion(version);
      setIsReadonly(true);
    } catch {
      // ignore
    }
  }, []);

  const handleRestoreVersion = useCallback(async (version: Artifact) => {
    let c: string;
    try {
      c = await fetchArtifactContent(version.id);
    } catch {
      return;
    }
    setSaveStatus("saving");
    setSaveError(null);
    try {
      const newArtifact = await saveArtifactVersion({
        conversation_id: conversationId,
        kind: currentArtifact.kind,
        title: currentArtifact.title,
        mime_type: currentArtifact.mime_type,
        file_name: currentArtifact.file_name ?? undefined,
        content: c,
        parent_id: currentArtifact.id,
        meta: {
          ...(currentArtifact.meta as Record<string, unknown> || {}),
          restored_from_version: version.version,
        },
      });
      setCurrentArtifact(newArtifact);
      setContent(c);
      setViewingVersion(null);
      setIsReadonly(false);
      setSaveStatus("success");
      onSaved(newArtifact);
      loadHistory();
    } catch (err) {
      setSaveStatus("error");
      setSaveError(describeApiError(err));
    }
  }, [conversationId, currentArtifact, onSaved, loadHistory]);

  const handleShowCurrent = useCallback(() => {
    if (viewingVersion) {
      setViewingVersion(null);
      setIsReadonly(false);
      let cancelled = false;
      fetchArtifactContent(currentArtifact.id)
        .then((c) => { if (!cancelled) setContent(c); })
        .catch(() => {});
      return () => { cancelled = true; };
    }
  }, [currentArtifact.id, viewingVersion]);

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
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {isReadonly && viewingVersion && (
            <span className="text-xs text-amber-400/80">
              查看 v{viewingVersion.version}
            </span>
          )}
          {saveStatus === "success" && (
            <span className="text-xs text-green-500/80">已保存</span>
          )}
          {saveStatus === "error" && (
            <span className="text-xs text-red-500/80 max-w-64 truncate" title={saveError ?? ""}>
              保存失败：{saveError ?? "可重试"}
            </span>
          )}
          <button
            type="button"
            onClick={() => {
              const next = !showHistory;
              setShowHistory(next);
              if (next && history.length === 0) loadHistory();
            }}
            className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors ${
              showHistory
                ? "bg-accent/10 border-accent/30 text-accent"
                : "border-border text-muted hover:text-fg hover:bg-bg"
            }`}
          >
            版本历史
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveStatus === "saving" || content === null || isReadonly}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saveStatus === "saving" ? "保存中…" : "保存 (Ctrl+S)"}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex">
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
              onChange={(v) => { if (!isReadonly) setContent(v ?? ""); }}
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
                readOnly: isReadonly,
              }}
            />
          )}
        </div>

        {showHistory && (
          <div className="w-64 shrink-0 border-l border-border bg-panel/60 flex flex-col">
            <div className="px-3 py-2 border-b border-border text-xs font-medium text-fg flex items-center justify-between">
              <span>版本历史</span>
              <button
                type="button"
                onClick={() => setShowHistory(false)}
                className="text-muted hover:text-fg"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {historyLoading ? (
                <div className="p-3 text-xs text-muted">加载中…</div>
              ) : historyError ? (
                <div className="p-3 text-xs text-red-400">
                  {historyError}
                  <button type="button" onClick={loadHistory} className="ml-2 text-accent hover:underline">重试</button>
                </div>
              ) : history.length === 0 ? (
                <div className="p-3 text-xs text-muted">暂无历史版本</div>
              ) : (
                <div className="py-1">
                  {history.map((v) => (
                    <div
                      key={v.id}
                      className={`px-3 py-2 border-b border-border/40 text-xs transition-colors ${
                        viewingVersion?.id === v.id
                          ? "bg-accent/10"
                          : "hover:bg-bg"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <button
                          type="button"
                          onClick={() => {
                            if (viewingVersion?.id === v.id) {
                              handleShowCurrent();
                            } else {
                              void handleViewVersion(v);
                            }
                          }}
                          className="text-left flex-1 min-w-0"
                        >
                          <div className={`font-medium truncate ${
                            v.id === currentArtifact.id ? "text-accent" : "text-fg"
                          }`}>
                            v{v.version}
                            {v.id === currentArtifact.id && " (当前)"}
                          </div>
                          <div className="text-[10px] text-muted mt-0.5">
                            {new Date(v.created_at * 1000).toLocaleString("zh-CN")}
                          </div>
                        </button>
                        {v.id !== currentArtifact.id && (
                          <button
                            type="button"
                            onClick={() => {
                              void handleRestoreVersion(v);
                            }}
                            className="ml-2 text-[10px] text-muted hover:text-accent transition-colors shrink-0"
                            title="恢复到此版本"
                          >
                            恢复
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
