import type { MessageContent } from "../../types";
import { CodeBlock } from "./CodeBlock";
import { DiffCard } from "./DiffCard";
import { FileCard } from "./FileCard";
import { PreviewCard } from "./PreviewCard";
import { TextBubble } from "./TextBubble";

interface Props {
  content: MessageContent;
  artifactId?: string | null;
  onEditArtifact?: (artifactId: string) => void;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

export function ContentRenderer({ content, artifactId, onEditArtifact }: Props) {
  switch (content.type) {
    case "text":
      return <TextBubble text={stringValue(content.text) ?? ""} />;

    case "code":
      return (
        <CodeBlock
          code={stringValue(content.code) ?? ""}
          language={stringValue(content.language)}
          title={stringValue(content.title)}
          artifactId={artifactId}
          onEdit={onEditArtifact}
        />
      );

    case "diff":
      return (
        <DiffCard
          before={stringValue(content.before) ?? ""}
          after={stringValue(content.after) ?? ""}
          baseArtifactId={
            stringValue(content.base_artifact_id) ??
            stringValue(content.baseArtifactId)
          }
          summary={stringValue(content.summary)}
          fileName={stringValue(content.fileName) ?? stringValue(content.file_name)}
        />
      );

    case "preview":
      return (
        <PreviewCard
          artifactId={artifactId ?? ""}
          title={stringValue(content.title) ?? "预览"}
          mimeType={stringValue(content.mimeType) ?? "text/plain"}
          fileSize={numberValue(content.fileSize) ?? 0}
        />
      );

    case "file":
      return (
        <FileCard
          fileName={stringValue(content.fileName) ?? "untitled"}
          mimeType={stringValue(content.mimeType) ?? "application/octet-stream"}
          fileSize={numberValue(content.fileSize) ?? 0}
          downloadUrl={`/api/artifacts/${artifactId}/content`}
        />
      );

    default:
      return (
        <div className="text-xs text-red-500/70 border border-red-500/20 rounded p-2 my-1">
          未知消息类型：{(content as { type: string }).type}
        </div>
      );
  }
}
