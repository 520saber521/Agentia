import React, { Fragment, useMemo } from "react";
import { CodeBlock } from "./CodeBlock";

interface Props {
  text: string;
}

interface CodePart {
  type: "code";
  code: string;
  language?: string;
}

interface TextBlock {
  type: "text";
  text: string;
}

type Part = TextBlock | CodePart;

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

/** Split inline text into segments by simple markdown patterns. */
interface InlineSeg {
  type: "text" | "bold" | "italic" | "code" | "link";
  text: string;
  href?: string;
}

const INLINE_RE = /(\*\*(.+?)\*\*)|(\*(.+?)\*)|(`([^`]+)`)|(\[([^\]]+)\]\(([^)]+)\))/g;

function renderInline(text: string) {
  const segments: InlineSeg[] = [];
  let lastIndex = 0;
  let m: RegExpExecArray | null;

  while ((m = INLINE_RE.exec(text)) !== null) {
    if (m.index > lastIndex) {
      segments.push({ type: "text", text: text.slice(lastIndex, m.index) });
    }
    if (m[1]) segments.push({ type: "bold", text: m[2] });
    else if (m[3]) segments.push({ type: "italic", text: m[4] });
    else if (m[5]) segments.push({ type: "code", text: m[6] });
    else if (m[7]) segments.push({ type: "link", text: m[8], href: m[9] });
    lastIndex = m.index + m[0].length;
  }

  if (lastIndex < text.length) {
    segments.push({ type: "text", text: text.slice(lastIndex) });
  }

  if (segments.length === 0) {
    segments.push({ type: "text", text });
  }

  return segments.map((seg, i) => {
    switch (seg.type) {
      case "bold":
        return <strong key={i} className="font-semibold text-fg">{seg.text}</strong>;
      case "italic":
        return <em key={i} className="italic text-fg/90">{seg.text}</em>;
      case "code":
        return <code key={i} className="px-1 py-[1px] rounded bg-border/50 text-[12px] font-mono text-accent">{seg.text}</code>;
      case "link":
        return (
          <a key={i} href={seg.href} target="_blank" rel="noopener noreferrer"
            className="underline underline-offset-2 text-accent hover:text-accent-hover transition-colors">
            {seg.text}
          </a>
        );
      default:
        return <Fragment key={i}>{seg.text}</Fragment>;
    }
  });
}

/** Split text into paragraph-like blocks for list detection. */
interface ParaBlock {
  kind: "para" | "ul" | "ol";
  items?: string[];
  text?: string;
}

function parseParagraphs(text: string): ParaBlock[] {
  const blocks: ParaBlock[] = [];
  const rawLines = text.split("\n");
  let i = 0;

  while (i < rawLines.length) {
    const line = rawLines[i];

    // Unordered list
    const ulMatch = line.match(/^[*-]\s+(.*)$/);
    if (ulMatch) {
      const items: string[] = [ulMatch[1]];
      i++;
      while (i < rawLines.length) {
        const next = rawLines[i].match(/^[*-]\s+(.*)$/);
        if (!next) break;
        items.push(next[1]);
        i++;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }

    // Ordered list
    const olMatch = line.match(/^\d+[.)]\s+(.*)$/);
    if (olMatch) {
      const items: string[] = [olMatch[1]];
      i++;
      while (i < rawLines.length) {
        const next = rawLines[i].match(/^\d+[.)]\s+(.*)$/);
        if (!next) break;
        items.push(next[1]);
        i++;
      }
      blocks.push({ kind: "ol", items });
      continue;
    }

    // Horizontal rule
    if (/^---+\s*$/.test(line) || /^\*\*\*+\s*$/.test(line)) {
      blocks.push({ kind: "para", text: "---" });
      i++;
      continue;
    }

    // Empty line = paragraph break
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Regular paragraph — collect consecutive lines until blank
    const paraLines: string[] = [line];
    i++;
    while (i < rawLines.length && rawLines[i].trim() !== "") {
      paraLines.push(rawLines[i]);
      i++;
    }
    blocks.push({ kind: "para", text: paraLines.join("\n") });
  }

  return blocks;
}

export const TextBubble = React.memo(function TextBubble({ text }: Props) {
  const parts = useMemo(() => parseTextParts(text), [text]);

  return (
    <div className="text-sm leading-relaxed space-y-1">
      {parts.map((part, pi) =>
        part.type === "code" ? (
          <CodeBlock key={`code-${pi}`} code={part.code} language={part.language} />
        ) : (
          <div key={`text-${pi}`} className="whitespace-pre-wrap break-words">
            {parseParagraphs(part.text).map((block, bi) => {
              if (block.kind === "ul" && block.items) {
                return (
                  <ul key={bi} className="list-disc list-inside space-y-0.5 my-1">
                    {block.items.map((item, ii) => (
                      <li key={ii}>{renderInline(item)}</li>
                    ))}
                  </ul>
                );
              }
              if (block.kind === "ol" && block.items) {
                return (
                  <ol key={bi} className="list-decimal list-inside space-y-0.5 my-1">
                    {block.items.map((item, ii) => (
                      <li key={ii}>{renderInline(item)}</li>
                    ))}
                  </ol>
                );
              }
              if (block.text === "---") {
                return <hr key={bi} className="my-2 border-border/50" />;
              }
              return (
                <p key={bi} className="min-h-[1.2em]">
                  {renderInline(block.text ?? "")}
                </p>
              );
            })}
          </div>
        ),
      )}
    </div>
  );
});
