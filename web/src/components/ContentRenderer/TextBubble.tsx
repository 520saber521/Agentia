import { CodeBlock } from "./CodeBlock";

interface Props {
  text: string;
}

interface TextPart {
  type: "text";
  text: string;
}

interface CodePart {
  type: "code";
  code: string;
  language?: string;
}

type Part = TextPart | CodePart;

const CODE_FENCE_RE = /```([\w.+-]*)\n([\s\S]*?)```/g;

function parseTextParts(text: string): Part[] {
  const parts: Part[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = CODE_FENCE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", text: text.slice(lastIndex, match.index) });
    }
    parts.push({
      type: "code",
      language: match[1]?.trim() || undefined,
      code: match[2] ?? "",
    });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: "text", text: text.slice(lastIndex) });
  }

  return parts.length > 0 ? parts : [{ type: "text", text }];
}

export function TextBubble({ text }: Props) {
  const parts = parseTextParts(text);

  return (
    <div className="text-sm leading-relaxed">
      {parts.map((part, index) =>
        part.type === "code" ? (
          <CodeBlock
            key={`code-${index}`}
            code={part.code}
            language={part.language}
          />
        ) : (
          <div
            key={`text-${index}`}
            className="whitespace-pre-wrap break-words"
          >
            {part.text}
          </div>
        ),
      )}
    </div>
  );
}
