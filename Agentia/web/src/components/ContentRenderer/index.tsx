import { useEffect, useState } from "react";

import { fetchArtifactContent } from "../../api/client";
import type { MessageContent } from "../../types";
import { CodeBlock } from "./CodeBlock";
import { DiffCard } from "./DiffCard";
import { FileCard } from "./FileCard";
import { PreviewCard } from "./PreviewCard";
import { DeployStatusCard, TaskStatusInlineCard } from "./StatusCards";
import { TextBubble } from "./TextBubble";

interface Props {
  content: MessageContent;
  artifactId?: string | null;
  onEditArtifact?: (artifactId: string) => void;
  fillHeight?: boolean;
  sourceAgentId?: string;
  sourceAgentName?: string;
  sourceMessageId?: string;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function shouldRenderCodeAsRichText(content: Extract<MessageContent, { type: "code" }>): boolean {
  const language = stringValue(content.language)?.toLowerCase() ?? "";
  const mimeType = stringValue(content.mimeType)?.toLowerCase() ?? "";
  const title = stringValue(content.title)?.toLowerCase() ?? "";
  return (
    language === "text" ||
    language === "plain" ||
    language === "plaintext" ||
    language === "markdown" ||
    language === "md" ||
    mimeType === "text/plain" ||
    mimeType === "text/markdown" ||
    title.includes("后端") ||
    title.includes("数据库") ||
    title.includes("backend") ||
    title.includes("database")
  );
}

function ArtifactRichText({ artifactId, fallbackText }: { artifactId?: string | null; fallbackText?: string }) {
  const [text, setText] = useState(fallbackText ?? "");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (fallbackText !== undefined) {
      setText(fallbackText);
      return;
    }
    if (!artifactId) {
      setText("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchArtifactContent(artifactId)
      .then((content) => {
        if (!cancelled) setText(content);
      })
      .catch(() => {
        if (!cancelled) setText("产物内容加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [artifactId, fallbackText]);

  if (loading && !text) {
    return <div className="text-xs text-muted">加载中...</div>;
  }
  return <TextBubble text={text} />;
}

export function ContentRenderer({ content, artifactId, onEditArtifact, fillHeight, sourceAgentId, sourceAgentName, sourceMessageId }: Props) {
  switch (content.type) {
    case "text":
      return <TextBubble text={stringValue(content.text) ?? ""} />;

    case "code":
      if (shouldRenderCodeAsRichText(content)) {
        return (
          <ArtifactRichText
            artifactId={artifactId ?? stringValue(content.artifact_id)}
            fallbackText={stringValue(content.code)}
          />
        );
      }
      return (
        <CodeBlock
          code={stringValue(content.artifact_id) ? undefined : stringValue(content.code)}
          language={stringValue(content.language)}
          title={stringValue(content.title)}
          artifactId={artifactId ?? stringValue(content.artifact_id)}
          sourceAgentId={sourceAgentId}
          sourceAgentName={sourceAgentName}
          sourceMessageId={sourceMessageId}
          onEdit={onEditArtifact}
        />
      );

    case "diff":
      return (
        <DiffCard
          diff={stringValue(content.diff)}
          before={stringValue(content.before) ?? ""}
          after={stringValue(content.after) ?? ""}
          baseArtifactId={
            stringValue(content.base_artifact_id) ??
            stringValue(content.baseArtifactId)
          }
          appliedArtifactId={stringValue(content.applied_artifact_id)}
          summary={stringValue(content.summary)}
          fileName={stringValue(content.fileName) ?? stringValue(content.file_name)}
          onApplied={(result) => {
            window.dispatchEvent(
              new CustomEvent("agenthub:artifact-applied", { detail: result }),
            );
          }}
        />
      );

    case "preview":
      return (
        <PreviewCard
          artifactId={artifactId ?? stringValue(content.artifact_id) ?? ""}
          title={stringValue(content.title) ?? "预览"}
          mimeType={stringValue(content.mimeType) ?? "text/plain"}
          fileSize={numberValue(content.fileSize) ?? 0}
          url={stringValue(content.url)}
          previewUrl={stringValue(content.previewUrl)}
          sourceAgentId={sourceAgentId}
          sourceAgentName={sourceAgentName}
          sourceMessageId={sourceMessageId}
          onEdit={onEditArtifact}
        />
      );

    case "file":
      return (
        <FileCard
          fileName={stringValue(content.fileName) ?? "untitled"}
          mimeType={stringValue(content.mimeType) ?? "application/octet-stream"}
          fileSize={numberValue(content.fileSize) ?? 0}
          downloadUrl={`/api/artifacts/${artifactId ?? stringValue(content.artifact_id)}/content`}
          fillHeight={fillHeight}
        />
      );

    case "task_status":
      return <TaskStatusInlineCard content={content} />;

    case "deploy_status":
      return <DeployStatusCard content={content} />;

    default:
      return (
        <div className="text-xs text-red-500/70 border border-red-500/20 rounded p-2 my-1">
          未知消息类型：{(content as { type: string }).type}
        </div>
      );
  }
}
