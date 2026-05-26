import { useState } from "react";

interface Props {
  code: string;
}

export function HtmlPreview({ code }: Props) {
  const [showPreview, setShowPreview] = useState(true);

  return (
    <div className="my-2 rounded-xl border border-border bg-panel overflow-hidden shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border bg-bg/40">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-6 w-6 rounded-md bg-orange-500/10 border border-orange-500/20 flex items-center justify-center text-orange-400 text-xs shrink-0">
            &lt;/&gt;
          </div>
          <span className="text-xs font-medium text-fg truncate">HTML 预览</span>
        </div>
        <button
          type="button"
          onClick={() => setShowPreview(!showPreview)}
          className="rounded-full border border-accent/30 px-3 py-1 text-xs text-accent hover:bg-accent/10 transition-colors"
        >
          {showPreview ? "查看代码" : "预览"}
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
