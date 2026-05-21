"""Protocol enums and constants."""

MESSAGE_TYPES = (
    "ask",
    "report",
    "send",
    "done",
    "fail",
    "ack",
    "nack",
)

ACTION_TYPES = (
    "review",
    "review_feedback",
    "assign",
    "clarify",
    "answer",
    "verify",
    "verified",
)

CATEGORY_TYPES = (
    "func",
    "perf",
    "ux",
    "security",
    "docs",
)

SEVERITY_LEVELS = (
    "high",
    "medium",
    "low",
)

REASON_CODES = (
    "queue_full",
    "invalid_format",
    "not_authorized",
    "task_cancelled",
    "deadline_exceeded",
    "missing_dependency",
)

ACK_STAGES = (
    "delivered",
    "accepted",
)

BODY_ENCODINGS = (
    "json",
    "base64",
)

DEFAULT_BODY_ENCODING = "json"

CARD_TYPES = (
    "text",
    "code",
    "diff",
    "preview",
    "file",
    "task_status",
)
