# Debug Session: HTML Preview Truncation

Status: [OPEN]

## Problem
Frontend agent generates HTML that cannot be previewed correctly. Preview page shows leading prose / markdown instead of rendered HTML, and the generated code appears incomplete/truncated.

## Initial Hypotheses
1. H1: The model output is incomplete or truncated before the closing HTML tags arrive, so the saved artifact is partial CSS/HTML.
2. H2: The HTML extraction function fails when the message contains prose before ```html fences or malformed markdown, causing raw mixed text to be saved as preview content.
3. H3: The artifact content is saved correctly, but preview endpoint returns escaped or incorrect mime/content due to artifact metadata/content mismatch.
4. H4: The code editor/content renderer displays only part of the artifact due to frontend truncation or virtualized rendering, while backend stores full content.
5. H5: The Orchestrator preview synthesis consumes subtask output that is itself malformed and does not sanitize/extract HTML before creating the final preview artifact.

## Evidence Plan
- Instrument backend artifact creation and preview serving to record content length, mime type, first/last snippets, and whether content looks like complete HTML.
- Instrument HTML extraction paths to record which extraction branch is used and whether markdown/prose wrappers are removed.
- Reproduce by generating/opening a preview artifact and compare logs.

## Pre-fix Evidence
- `preview_served` for `art_b8b666dcbec2`: `mime_type=text/html`, `kind=preview`, so the preview endpoint is returning the configured HTML artifact.
- The saved content starts with `<!doctype html>\n我来帮你生成...```html\n<!DOCTYPE html>`, proving prose and Markdown fence were persisted inside the HTML artifact.
- `closing_html_pos=-1`, proving the artifact content has no complete `</html>` closing tag.
- The tail ends in the middle of CSS: `.message.user .bubble .msg-footer { justify-content`, proving the generated code itself is incomplete/truncated.

## Confirmed Root Cause
H1 and H2 are confirmed. The extraction/normalization path allowed partial HTML-like text to become a preview artifact. The preview endpoint is not the root cause; it correctly returns the malformed artifact.

## Post-fix Verification
- Bad mixed/prose/truncated sample now returns `None` from `_extract_html_from_text`, so it cannot be saved as a new preview artifact.
- Complete fenced HTML still extracts successfully and remains previewable.
- Existing broken artifact `art_b8b666dcbec2` is now blocked by `/preview/{id}` and replaced with a friendly "预览内容不完整" HTML page.
- Debug log `preview_blocked_incomplete_html` confirms the historical artifact is incomplete: `closing_html_pos=-1`, `has_fence=true`, and content tail stops mid-CSS.

## Fix Applied
- Tightened `_extract_html_from_text()` to reject incomplete `<html>`/doctype documents and incomplete fenced HTML.
- Raised preview synthesis adapter `max_tokens` to at least 12000 only for final HTML preview generation.
- Added `/preview/{artifact_id}` guard for historical malformed HTML artifacts.
