"""Validation utilities for message protocol."""

import base64
import binascii
import json

from protocol.enums import (
    ACTION_TYPES,
    BODY_ENCODINGS,
    CARD_TYPES,
    CATEGORY_TYPES,
    DEFAULT_BODY_ENCODING,
    MESSAGE_TYPES,
    SEVERITY_LEVELS,
)
from protocol.utils import normalize_to_list


class ValidationError(ValueError):
    """Raised when protocol validation fails."""

    def __init__(self, errors):
        super().__init__("; ".join(errors))
        self.errors = errors


def _is_int_like(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return value.isdigit()
    return False


def _is_non_empty_string(value):
    return isinstance(value, str) and value.strip() != ""


def _int_value(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _require_str_field(container, field, errors, context):
    if not _is_non_empty_string(container.get(field)):
        errors.append(f"{context}.{field} must be non-empty string")
        return None
    return container[field]


def _require_bool_field(container, field, errors, context):
    if field not in container:
        errors.append(f"{context}.{field} missing")
        return None
    if not isinstance(container[field], bool):
        errors.append(f"{context}.{field} must be boolean")
        return None
    return container[field]


def _require_int_field(container, field, errors, context):
    if field not in container:
        errors.append(f"{context}.{field} missing")
        return None
    if not _is_int_like(container[field]):
        errors.append(f"{context}.{field} must be int-like")
        return None
    return container[field]


def _require_list_of_strings(container, field, errors, context, *, allow_empty=False):
    if field not in container:
        errors.append(f"{context}.{field} missing")
        return None
    value = container[field]
    if not isinstance(value, list):
        errors.append(f"{context}.{field} must be list")
        return None
    if not value and not allow_empty:
        errors.append(f"{context}.{field} must be non-empty list")
        return None
    if any(not _is_non_empty_string(item) for item in value):
        errors.append(f"{context}.{field} must be list of non-empty strings")
        return None
    return value


def _optional_list_of_strings(container, field, errors, context):
    if field not in container:
        return None
    value = container[field]
    if not isinstance(value, list):
        errors.append(f"{context}.{field} must be list")
        return None
    if any(not _is_non_empty_string(item) for item in value):
        errors.append(f"{context}.{field} must be list of non-empty strings")
    return value


def _optional_str_field(container, field, errors, context):
    if field not in container:
        return None
    if not _is_non_empty_string(container[field]):
        errors.append(f"{context}.{field} must be non-empty string")
        return None
    return container[field]


def _require_json_body(action, body_encoding, parsed_body, errors):
    if body_encoding != "json":
        errors.append(f"{action} requires body_encoding json")
        return None
    if not isinstance(parsed_body, dict):
        errors.append(f"{action} requires json body")
        return None
    return parsed_body


def validate_message(message, *, allow_missing_generated=False):
    """Return a list of validation errors for a message dict."""
    errors = []
    if not isinstance(message, dict):
        return ["message must be a dict"]

    required = ["v", "session", "epoch", "agent_instance", "from", "to", "type"]
    if not allow_missing_generated:
        required.extend(["seq", "id", "ts"])

    for key in required:
        if key not in message:
            errors.append(f"missing field: {key}")

    if "v" in message and not _is_int_like(message["v"]):
        errors.append("v must be int-like")
    if "session" in message and not isinstance(message["session"], str):
        errors.append("session must be string")
    if "epoch" in message and not _is_int_like(message["epoch"]):
        errors.append("epoch must be int-like")
    if "seq" in message and not _is_int_like(message["seq"]):
        errors.append("seq must be int-like")
    if "ts" in message and not _is_int_like(message["ts"]):
        errors.append("ts must be int-like")
    if "agent_instance" in message and not isinstance(message["agent_instance"], str):
        errors.append("agent_instance must be string")
    if "from" in message and not isinstance(message["from"], str):
        errors.append("from must be string")

    to_list = None
    if "to" in message:
        try:
            to_list = normalize_to_list(message["to"])
        except (TypeError, ValueError) as exc:
            errors.append(f"to invalid: {exc}")

    msg_type = message.get("type")
    if msg_type is not None:
        if not isinstance(msg_type, str):
            errors.append("type must be string")
        elif msg_type not in MESSAGE_TYPES:
            errors.append(f"type invalid: {msg_type}")

    action = message.get("action")
    if action is not None:
        if not isinstance(action, str):
            errors.append("action must be string")
        elif action not in ACTION_TYPES:
            errors.append(f"action invalid: {action}")

    if "corr" in message and not isinstance(message["corr"], str):
        errors.append("corr must be string")

    if "deadline" in message and not _is_int_like(message["deadline"]):
        errors.append("deadline must be int-like")
    if "ttl_ms" in message and not _is_int_like(message["ttl_ms"]):
        errors.append("ttl_ms must be int-like")

    # W3/W4 optional fields (backward-compatible, no validation errors when present)
    if "conversation_id" in message and not isinstance(message["conversation_id"], str):
        errors.append("conversation_id must be string")
    if "card_type" in message:
        card_type = message["card_type"]
        if not isinstance(card_type, str) or card_type not in CARD_TYPES:
            errors.append(f"card_type invalid: {card_type}")
    if "artifact_id" in message and not isinstance(message["artifact_id"], str):
        errors.append("artifact_id must be string")

    has_body = "body" in message
    has_body_ref = "body_ref" in message
    body_encoding = message.get("body_encoding")
    if body_encoding is None and (has_body or has_body_ref):
        body_encoding = DEFAULT_BODY_ENCODING

    if body_encoding is not None and body_encoding not in BODY_ENCODINGS:
        errors.append(f"body_encoding invalid: {body_encoding}")

    body_value = message.get("body")
    if has_body:
        if not isinstance(body_value, str):
            errors.append("body must be string")
        elif "\n" in body_value or "\r" in body_value:
            errors.append("body must be single-line string")

    if has_body_ref and not isinstance(message["body_ref"], str):
        errors.append("body_ref must be string")

    parsed_body = None
    if body_encoding == "json":
        if has_body and isinstance(body_value, str):
            if body_value == "" and not has_body_ref:
                errors.append("body is empty for json encoding")
            elif body_value != "":
                try:
                    parsed_body = json.loads(body_value)
                    if not isinstance(parsed_body, dict):
                        errors.append("body must be JSON object")
                except json.JSONDecodeError as exc:
                    errors.append(f"body json invalid: {exc}")
        elif has_body_ref:
            pass
        elif body_encoding is not None:
            errors.append("body missing for json encoding")

    if body_encoding == "base64" and has_body and isinstance(body_value, str):
        try:
            base64.b64decode(body_value, validate=True)
        except (ValueError, binascii.Error):
            errors.append("body base64 invalid")

    if msg_type and msg_type != "ask":
        if not message.get("corr"):
            errors.append("corr required for non-ask messages")

    if action == "review":
        if msg_type is not None and msg_type != "ask":
            errors.append("review requires type ask")
        body = _require_json_body("review", body_encoding, parsed_body, errors)
        if body is not None:
            _require_str_field(body, "doc_path", errors, "review.body")
            _require_int_field(body, "review_deadline", errors, "review.body")
            reviewers = body.get("reviewers")
            if not isinstance(reviewers, list) or not reviewers:
                errors.append("review.body.reviewers must be non-empty list")
            elif not all(isinstance(item, str) and item for item in reviewers):
                errors.append("review.body.reviewers must be list of strings")
            elif to_list is not None and reviewers != to_list:
                errors.append("review.body.reviewers must match to")
            focus = body.get("focus")
            if focus is not None:
                if not isinstance(focus, list):
                    errors.append("review.body.focus must be list")
                elif any(not _is_non_empty_string(item) for item in focus):
                    errors.append("review.body.focus must be list of non-empty strings")

    if action == "assign":
        if msg_type is not None and msg_type != "ask":
            errors.append("assign requires type ask")
        _require_str_field(message, "task_id", errors, "message")
        _require_str_field(message, "owner", errors, "message")
        _require_int_field(message, "deadline", errors, "message")
        body = _require_json_body("assign", body_encoding, parsed_body, errors)
        if body is not None:
            _require_str_field(body, "task_type", errors, "assign.body")
            _require_list_of_strings(body, "files", errors, "assign.body")
            _require_list_of_strings(body, "success_criteria", errors, "assign.body")
            _optional_list_of_strings(body, "dependencies", errors, "assign.body")

    if action == "clarify":
        if msg_type is not None and msg_type != "ask":
            errors.append("clarify requires type ask")
        _require_str_field(message, "task_id", errors, "message")
        _require_str_field(message, "owner", errors, "message")
        body = _require_json_body("clarify", body_encoding, parsed_body, errors)
        if body is not None:
            _require_str_field(body, "code_path", errors, "clarify.body")
            _require_str_field(body, "question", errors, "clarify.body")
            _require_str_field(body, "context", errors, "clarify.body")
            _optional_str_field(body, "expected", errors, "clarify.body")
            _optional_str_field(body, "doc_path", errors, "clarify.body")

    if action == "verify":
        if msg_type is not None and msg_type != "ask":
            errors.append("verify requires type ask")
        _require_str_field(message, "task_id", errors, "message")
        _require_str_field(message, "owner", errors, "message")
        body = _require_json_body("verify", body_encoding, parsed_body, errors)
        if body is not None:
            _require_str_field(body, "doc_path", errors, "verify.body")
            _require_str_field(body, "question", errors, "verify.body")
            _optional_str_field(body, "changes_summary", errors, "verify.body")

    if action == "review_feedback":
        if msg_type is not None and msg_type != "report":
            errors.append("review_feedback requires type report")
        _require_str_field(message, "task_id", errors, "message")
        body = _require_json_body("review_feedback", body_encoding, parsed_body, errors)
        if body is not None:
            _require_str_field(body, "doc_path", errors, "review_feedback.body")
            has_issues = _require_bool_field(body, "has_issues", errors, "review_feedback.body")
            issue_count = _require_int_field(body, "issue_count", errors, "review_feedback.body")
            issues = body.get("issues")
            if has_issues is True:
                if _int_value(issue_count) is not None and _int_value(issue_count) <= 0:
                    errors.append("review_feedback.body.issue_count must be > 0 when has_issues=true")
                if not isinstance(issues, list) or not issues:
                    errors.append("review_feedback.body.issues must be non-empty list when has_issues=true")
            elif has_issues is False:
                if _int_value(issue_count) not in (None, 0):
                    errors.append("review_feedback.body.issue_count must be 0 when has_issues=false")
                if isinstance(issues, list) and issues:
                    errors.append("review_feedback.body.issues must be empty when has_issues=false")

            if isinstance(issues, list):
                if _int_value(issue_count) is not None and len(issues) != _int_value(issue_count):
                    errors.append("review_feedback.body.issue_count must match issues length")
                for idx, issue in enumerate(issues):
                    context = f"review_feedback.body.issues[{idx}]"
                    if not isinstance(issue, dict):
                        errors.append(f"{context} must be object")
                        continue
                    _require_str_field(issue, "doc_path", errors, context)
                    issue_text = issue.get("issue")
                    summary_text = issue.get("summary")
                    if not _is_non_empty_string(issue_text) and not _is_non_empty_string(summary_text):
                        errors.append(f"{context}.issue or {context}.summary required")
                    if issue_text is not None and not _is_non_empty_string(issue_text):
                        errors.append(f"{context}.issue must be non-empty string")
                    if summary_text is not None and not _is_non_empty_string(summary_text):
                        errors.append(f"{context}.summary must be non-empty string")
                    category = issue.get("category")
                    if not _is_non_empty_string(category):
                        errors.append(f"{context}.category must be non-empty string")
                    elif category not in CATEGORY_TYPES:
                        errors.append(f"{context}.category invalid: {category}")
                    severity = issue.get("severity")
                    if not _is_non_empty_string(severity):
                        errors.append(f"{context}.severity must be non-empty string")
                    elif severity not in SEVERITY_LEVELS:
                        errors.append(f"{context}.severity invalid: {severity}")
                    _optional_str_field(issue, "code_path", errors, context)
                    _optional_list_of_strings(issue, "code_paths", errors, context)
                    _optional_list_of_strings(issue, "doc_paths", errors, context)
                    _optional_str_field(issue, "issue_group", errors, context)
                    suggested_fix = issue.get("suggested_fix")
                    suggestion = issue.get("suggestion")
                    if suggested_fix is not None and not _is_non_empty_string(suggested_fix):
                        errors.append(f"{context}.suggested_fix must be non-empty string")
                    if suggestion is not None and not _is_non_empty_string(suggestion):
                        errors.append(f"{context}.suggestion must be non-empty string")

            _optional_str_field(body, "summary", errors, "review_feedback.body")
            questions = body.get("questions")
            if questions is not None:
                if not isinstance(questions, list):
                    errors.append("review_feedback.body.questions must be list")
                elif any(not _is_non_empty_string(item) for item in questions):
                    errors.append("review_feedback.body.questions must be list of non-empty strings")

    if action == "answer":
        if msg_type is not None and msg_type != "send":
            errors.append("answer requires type send")
        _require_str_field(message, "task_id", errors, "message")
        body = _require_json_body("answer", body_encoding, parsed_body, errors)
        if body is not None and not body:
            errors.append("answer.body must not be empty object")

    if msg_type == "done":
        _require_str_field(message, "task_id", errors, "message")
        if action == "verified":
            body = _require_json_body("verified", body_encoding, parsed_body, errors)
            if body is not None:
                has_new_issues = _require_bool_field(body, "has_new_issues", errors, "verified.body")
                if has_new_issues is True:
                    new_issue_count = _require_int_field(body, "new_issue_count", errors, "verified.body")
                    if _int_value(new_issue_count) is not None and _int_value(new_issue_count) <= 0:
                        errors.append("verified.body.new_issue_count must be > 0 when has_new_issues=true")
                elif has_new_issues is False and "new_issue_count" in body:
                    if not _is_int_like(body.get("new_issue_count")):
                        errors.append("verified.body.new_issue_count must be int-like")
        elif body_encoding == "json" and isinstance(parsed_body, dict):
            if "status" in parsed_body:
                _require_str_field(parsed_body, "status", errors, "done.body")

    if msg_type == "fail":
        _require_str_field(message, "task_id", errors, "message")
        body = _require_json_body("fail", body_encoding, parsed_body, errors)
        if body is not None:
            _require_str_field(body, "reason", errors, "fail.body")
            _optional_list_of_strings(body, "blocked_by", errors, "fail.body")

    return errors


def assert_valid_message(message, *, allow_missing_generated=False):
    """Raise ValidationError if message is invalid."""
    errors = validate_message(message, allow_missing_generated=allow_missing_generated)
    if errors:
        raise ValidationError(errors)
