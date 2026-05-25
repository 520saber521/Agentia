import { useState } from "react";
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

interface HtmlPart {
  type: "html_preview";
  code: string;
}

type Part = TextPart | CodePart | HtmlPart;

const CODE_FENCE_RE = /```(\w*)\s*\n([\s\S]*?)```/g;
const HTML_LANG_RE = /^(html|htm)$/i;

function parseTextParts(text: string): Part[] {
  const parts: Part[] = [];
  let lastIndex = 0;
  CODE_FENCE_RE.lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = CODE_FENCE_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: "text", text: text.slice(lastIndex, match.index) });
    }
    const lang = (match[1] || "").trim();
    const code = match[2] || "";
    if (HTML_LANG_RE.test(lang)) {
      parts.push({ type: "html_preview", code });
    } else {
      parts.push({ type: "code", language: lang || undefined, code });
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ type: "text", text: text.slice(lastIndex) });
  }

  return parts.length > 0 ? parts : [{ type: "text", text }];
}

function InlineHtmlPreview({ code }: { code: string }) {
  const [showPreview, setShowPreview] = useState(true);

  return (
    <div className="my-2 rounded-xl border-2 border-orange-500 bg-panel overflow-hidden shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-bg/40">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs font-bold text-orange-400">🌐 HTML 实时预览</span>
          <span className="text-[10px] text-orange-300 bg-orange-500/10 px-2 py-0.5 rounded">{code.length} 字符</span>
        </div>
        <button
          type="button"
          onClick={() => setShowPreview(!showPreview)}
          className="rounded-full border border-accent/30 px-3 py-1 text-xs text-accent hover:bg-accent/10 transition-colors"
        >
          {showPreview ? "查看源码" : "预览"}
        </button>
      </div>

      {showPreview ? (
        <div className="relative w-full bg-white" style={{ height: "480px" }}>
          <iframe
            srcDoc={code}
            title="HTML Preview"
            className="w-full h-full border-0"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
          />
        </div>
      ) : (
        <div className="max-h-[480px] overflow-auto p-3 bg-[#1e1e2e] rounded-b-xl">
          <pre className="text-sm text-gray-300 whitespace-pre-wrap break-words font-mono leading-relaxed">
            <code>{code}</code>
          </pre>
        </div>
      )}
    </div>
  );
}

export function TextBubble({ text }: Props) {
  const parts = parseTextParts(text);

  return (
    <div className="text-sm leading-relaxed">
      {parts.map((part, index) => {
        switch (part.type) {
          case "code":
            return (
              <CodeBlock
                key={`code-${index}`}
                code={part.code}
                language={part.language}
              />
            );
          case "html_preview":
            return (
              <InlineHtmlPreview
                key={`html-${index}`}
                code={part.code}
              />
            );
          default:
            return (
              <div
                key={`text-${index}`}
                className="whitespace-pre-wrap break-words"
              >
                {part.text}
              </div>
            );
        }
      })}
    </div>
  );
}
