import type { MessageContent } from "../../types";
import { CodeBlock } from "./CodeBlock";
import { DiffCard } from "./DiffCard";
import { FileCard } from "./FileCard";
import { PreviewCard } from "./PreviewCard";
import { TextBubble } from "./TextBubble";

interface Props {
  content: MessageContent;
  artifactId?: string | null;
}

export function ContentRenderer({ content, artifactId }: Props) {
  switch (content.type) {
    case "text":
      return <TextBubble text={content.text} />;

    case "code":
      return (
        <CodeBlock
          code={content.code}
          language={content.language}
          title={content.title}
        />
      );

    case "diff":
      return (
        <DiffCard
          before={content.before}
          after={content.after}
          fileName={content.fileName}
        />
      );

    case "preview":
      return (
        <PreviewCard
          artifactId={artifactId ?? ""}
          title={content.title}
          mimeType={content.mimeType}
          fileSize={content.fileSize ?? 0}
        />
      );

    case "file":
      return (
        <FileCard
          fileName={content.fileName}
          mimeType={content.mimeType}
          fileSize={content.fileSize ?? 0}
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
