import { useCallback, useEffect, useState } from "react";
import { fetchWorkspaceFile, fetchWorkspaceTree } from "../api/client";
import { useChatStore } from "../stores/useChatStore";
import type { FileTreeNode } from "../types";

function formatSize(bytes: number): string {
  if (bytes === 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIcon(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const codeExts = new Set([
    "py", "js", "ts", "tsx", "jsx", "html", "css", "json", "md", "txt",
    "yaml", "yml", "xml", "sql", "sh", "bat", "ps1", "toml", "ini", "cfg",
    "env", "csv", "log", "rs", "go", "java", "c", "cpp", "h", "rb", "php",
    "swift", "kt", "scala", "r", "lua", "pl", "dart",
  ]);
  const docExts = new Set(["md", "txt", "rst", "tex", "pdf"]);
  if (codeExts.has(ext)) return "◇";
  if (docExts.has(ext)) return "≡";
  if (["png", "jpg", "jpeg", "gif", "svg", "ico", "webp"].includes(ext)) return "▣";
  if (["zip", "tar", "gz", "rar", "7z"].includes(ext)) return "◉";
  return "○";
}

function FileTreeView({
  nodes,
  depth,
  expanded,
  onToggle,
  onFileClick,
  selectedFile,
}: {
  nodes: FileTreeNode[];
  depth: number;
  expanded: Set<string>;
  onToggle: (path: string) => void;
  onFileClick: (path: string) => void;
  selectedFile: string | null;
}) {
  return (
    <>
      {nodes.map((node) => {
        const isDir = node.type === "directory";
        const isOpen = expanded.has(node.path);
        const isSelected = node.path === selectedFile;
        const icon = isDir ? (isOpen ? "▼" : "▸") : getFileIcon(node.name);

        return (
          <div key={node.path}>
            <div
              className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs cursor-pointer
                hover:bg-accent/10 ${isSelected ? "bg-accent/20" : ""}`}
              style={{ paddingLeft: `${depth * 14 + 6}px` }}
              onClick={() => isDir ? onToggle(node.path) : onFileClick(node.path)}
            >
              <span className="w-3.5 text-center shrink-0 text-[10px] text-muted">
                {icon}
              </span>
              <span className="truncate text-fg/90">{node.name}</span>
              {!isDir && node.size > 0 && (
                <span className="ml-auto shrink-0 text-[10px] text-muted">
                  {formatSize(node.size)}
                </span>
              )}
            </div>
            {isDir && isOpen && node.children && node.children.length > 0 && (
              <FileTreeView
                nodes={node.children}
                depth={depth + 1}
                expanded={expanded}
                onToggle={onToggle}
                onFileClick={onFileClick}
                selectedFile={selectedFile}
              />
            )}
            {isDir && isOpen && (!node.children || node.children.length === 0) && (
              <div
                className="py-1 text-[10px] text-muted/60"
                style={{ paddingLeft: `${(depth + 1) * 14 + 22}px` }}
              >
                empty
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

export function WorkspacePanel() {
  const currentConvId = useChatStore((s) => s.currentConvId);
  const conversations = useChatStore((s) => s.conversations);
  const [tree, setTree] = useState<FileTreeNode[]>([]);
  const [rootPath, setRootPath] = useState<string>("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [fileMime, setFileMime] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentConv = conversations.find((c) => c.id === currentConvId);

  const loadTree = useCallback(async () => {
    if (!currentConvId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetchWorkspaceTree(currentConvId);
      setTree(res.tree);
      setRootPath(res.root_path);
    } catch (err) {
      setError("Failed to load workspace");
      setTree([]);
    } finally {
      setLoading(false);
    }
  }, [currentConvId]);

  useEffect(() => {
    // Reset all state when switching conversations
    setExpanded(new Set());
    setSelectedFile(null);
    setFileContent("");
    setFileMime("");
    loadTree();
  }, [loadTree]);

  // Listen for WS file change events to auto-refresh
  useEffect(() => {
    const store = useChatStore.getState;
    let timeout: ReturnType<typeof setTimeout>;
    const unsub = useChatStore.subscribe((state, prev) => {
      // Refresh tree when a new message arrives (agent may have written files)
      if (
        state.currentConvId === currentConvId &&
        state.messages.length > (prev as typeof state).messages.length
      ) {
        // Debounce — wait for any file writes to land
        clearTimeout(timeout);
        timeout = setTimeout(loadTree, 800);
      }
    });
    return () => {
      unsub();
      clearTimeout(timeout);
    };
  }, [currentConvId, loadTree]);

  const handleToggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const handleFileClick = async (path: string) => {
    if (!currentConvId) return;
    if (selectedFile === path) {
      setSelectedFile(null);
      setFileContent("");
      return;
    }
    setSelectedFile(path);
    setFileLoading(true);
    try {
      const res = await fetchWorkspaceFile(currentConvId, path);
      setFileContent(res.content);
      setFileMime(res.mime_type);
    } catch {
      setFileContent("[binary or unreadable file]");
      setFileMime("text/plain");
    } finally {
      setFileLoading(false);
    }
  };

  // Limit content preview
  const previewLines = fileContent.split("\n");
  const previewText = previewLines.length > 100
    ? previewLines.slice(0, 100).join("\n") + "\n... (truncated)"
    : fileContent;
  const lang = fileMime.split("/").pop()?.replace("x-", "") ?? "";

  return (
    <div className="flex flex-col min-h-0">
      {/* Tree section */}
      <div className="shrink-0 flex items-center justify-between px-2 py-1.5">
        <button
          type="button"
          onClick={loadTree}
          className="text-[10px] text-muted hover:text-fg transition-colors"
        >
          ↻ Refresh
        </button>
        {rootPath && (
          <span className="text-[10px] text-muted/60 truncate ml-2" title={rootPath}>
            {rootPath.split(/[/\\]/).slice(-2).join("/")}
          </span>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && (
          <div className="px-3 py-6 text-center text-[10px] text-muted">
            Loading workspace...
          </div>
        )}

        {error && !loading && (
          <div className="px-3 py-4 text-center">
            <div className="text-[10px] text-rose-400">{error}</div>
            <button
              type="button"
              onClick={loadTree}
              className="mt-2 text-[10px] text-accent hover:underline"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && !error && tree.length === 0 && (
          <div className="px-3 py-6 text-center text-[10px] text-muted">
            <div className="mb-1">No files yet</div>
            <div className="text-muted/60">
              Agents will create files here as they work.
            </div>
          </div>
        )}

        {!loading && tree.length > 0 && (
          <div className="py-1">
            <FileTreeView
              nodes={tree}
              depth={0}
              expanded={expanded}
              onToggle={handleToggle}
              onFileClick={handleFileClick}
              selectedFile={selectedFile}
            />
          </div>
        )}
      </div>

      {/* File preview section */}
      {selectedFile && (
        <div className="shrink-0 border-t border-border">
          <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-bg/60">
            <span className="truncate text-[10px] font-medium text-fg">
              {selectedFile.split("/").pop() ?? selectedFile}
            </span>
            <span className="shrink-0 text-[9px] text-muted ml-2">{lang}</span>
          </div>
          <div className="max-h-48 overflow-y-auto">
            {fileLoading ? (
              <div className="px-3 py-4 text-center text-[10px] text-muted">
                Loading...
              </div>
            ) : (
              <pre className="p-3 text-[10px] leading-relaxed text-fg/80 font-mono whitespace-pre-wrap break-all">
                {previewText || "(empty file)"}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
