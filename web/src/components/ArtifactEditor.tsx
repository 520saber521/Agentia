import { useCallback, useEffect, useRef, useState } from "react";
import Editor, { DiffEditor } from "@monaco-editor/react";

import { fetchArtifactContent, saveArtifactVersion, describeApiError } from "../api/client";
import type { Artifact } from "../types";
import { VersionHistoryPanel } from "./VersionHistoryPanel";

interface Props {
  artifact: Artifact;
  conversationId: string;
  onClose: () => void;
  onSaved: (newArtifact: Artifact) => void;
}

type SaveStatus = "idle" | "saving" | "success" | "error";

interface DiffSelection {
  version: Artifact;
  previousVersion: Artifact;
  before: string;
  after: string;
}

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
  const [diffSelection, setDiffSelection] = useState<DiffSelection | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const editorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setCurrentArtifact(artifact);
    setDiffSelection(null);
  }, [artifact]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setSaveStatus("idle");
    setSaveError(null);
    setDiffSelection(null);

    fetchArtifactContent(currentArtifact.id)
      .then((c) => {
        if (!cancelled) {
          setContent(c);
          setOriginalContent(c);
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
  const language = detectLanguage(currentArtifact);
  const isDiffMode = diffSelection !== null || diffLoading;

  const handleSave = useCallback(async () => {
    if (content === null || isDiffMode) return;
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
  }, [content, conversationId, currentArtifact, isDiffMode, onSaved]);

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

  const handleCompareVersion = useCallback(
    async (version: Artifact, previousVersion: Artifact | null) => {
      if (!previousVersion) {
        setDiffSelection(null);
        setLoading(true);
        setLoadError(null);
        try {
          const c = await fetchArtifactContent(version.id);
          setContent(c);
          setOriginalContent(c);
        } catch (err) {
          setLoadError(err instanceof Error ? err.message : "版本加载失败");
        } finally {
          setLoading(false);
        }
        return;
      }

      setDiffLoading(true);
      setDiffSelection(null);
      setLoadError(null);
      try {
        const [before, after] = await Promise.all([
          fetchArtifactContent(previousVersion.id),
          fetchArtifactContent(version.id),
        ]);
        setDiffSelection({ version, previousVersion, before, after });
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : "Diff 加载失败");
      } finally {
        setDiffLoading(false);
      }
    },
    [],
  );

  return (
    <div ref={editorRef} className="fixed inset-0 z-50 flex flex-col bg-[#05080d]">
      <div className="flex items-center justify-between px-4 py-2 border-b border-[#1d2633] bg-[#070b11] shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-[#9aa7b8] hover:text-[#e5eefc] transition-colors shrink-0"
          >
            ← 返回
          </button>
          <span className="w-px h-4 bg-[#1d2633]" />
          <span className="text-sm font-medium text-[#e5eefc] truncate">
            {currentArtifact.title}
          </span>
          <span className="text-[10px] text-[#7f8a9b] shrink-0">
            v{currentArtifact.version}
          </span>
          <span className="text-[10px] text-[#7f8a9b] shrink-0">{language}</span>
          {isDiffMode && (
            <span className="text-[10px] text-[#75d6ff] bg-[#12384b] px-1.5 py-0.5 rounded border border-[#23627d]">
              Diff 视图
            </span>
          )}
          {hasChanges && !isDiffMode && (
            <span className="text-[10px] text-amber-300 bg-amber-500/10 px-1.5 py-0.5 rounded">
              未保存的修改
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {diffSelection && (
            <button
              type="button"
              onClick={() => setDiffSelection(null)}
              className="px-2.5 py-1.5 text-[11px] font-medium rounded-md border border-[#263242] text-[#b8c7df] hover:text-[#e5eefc] hover:bg-[#101a27] transition-colors"
            >
              编辑最新版本
            </button>
          )}
          {saveStatus === "success" && !isDiffMode && (
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
                ? "border-[#23627d] text-[#75d6ff] bg-[#12384b]"
                : "border-[#263242] text-[#9aa7b8] hover:text-[#e5eefc] hover:bg-[#101a27]"
            }`}
          >
            版本历史
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saveStatus === "saving" || content === null || !hasChanges || isDiffMode}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-[#2388ff] text-white hover:bg-[#3c98ff] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saveStatus === "saving" ? "保存中..." : hasChanges ? "保存 (Ctrl+S)" : "已是最新"}
          </button>
        </div>
      </div>

      {diffSelection && (
        <div className="flex items-center gap-3 px-4 py-2 border-b border-[#1d2633] bg-[#080d14] text-xs text-[#8d99aa]">
          <span className="font-mono text-[#b8c7df]">
            v{diffSelection.previousVersion.version || 1} → v{diffSelection.version.version || 1}
          </span>
          <span className="truncate">{diffSelection.version.title}</span>
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        <div className="flex-1 min-w-0">
          {(loading || diffLoading) && (
            <div className="flex items-center justify-center h-full text-sm text-[#8d99aa]">
              {diffLoading ? "加载 Diff..." : "加载中..."}
            </div>
          )}
          {loadError && !loading && !diffLoading && (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <div className="text-sm text-red-500/80">{loadError}</div>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="text-xs text-[#75d6ff] hover:underline"
              >
                重试
              </button>
            </div>
          )}
          {!loading && !diffLoading && !loadError && diffSelection && (
            <DiffEditor
              height="100%"
              language={language}
              original={diffSelection.before}
              modified={diffSelection.after}
              theme="vs-dark"
              options={{
                readOnly: true,
                renderSideBySide: false,
                fontSize: 13,
                fontFamily: "'JetBrains Mono', 'Cascadia Mono', 'Consolas', monospace",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                automaticLayout: true,
                wordWrap: "on",
                lineNumbers: "on",
                renderWhitespace: "selection",
                padding: { top: 12 },
                originalEditable: false,
              }}
            />
          )}
          {!loading && !diffLoading && !loadError && !diffSelection && content !== null && (
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

        {showHistory && (
          <div className="w-80 border-l border-[#1d2633] bg-[#080d14] flex flex-col min-h-0">
            <VersionHistoryPanel
              artifactId={currentArtifact.id}
              currentVersion={currentArtifact.version || 1}
              selectedVersionId={diffSelection?.version.id ?? null}
              onCompareVersion={handleCompareVersion}
            />
          </div>
        )}
      </div>
    </div>
  );
}
