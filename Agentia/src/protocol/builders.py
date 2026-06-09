"""Message builder functions for CLI/Router usage."""

from .enums import DEFAULT_BODY_ENCODING
from .utils import encode_body, normalize_to_list


def build_message(
    *,
    v=1,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    msg_type,
    action=None,
    task_id=None,
    owner=None,
    deadline=None,
    corr=None,
    ttl_ms=None,
    body=None,
    body_encoding=DEFAULT_BODY_ENCODING,
    body_ref=None,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build a message dict without forcing seq/id/ts."""
    message = {
        "v": v,
        "session": session,
        "epoch": epoch,
        "agent_instance": agent_instance,
        "from": from_role,
        "to": normalize_to_list(to),
        "type": msg_type,
    }

    if action is not None:
        message["action"] = action
    if task_id is not None:
        message["task_id"] = task_id
    if owner is not None:
        message["owner"] = owner
    if deadline is not None:
        message["deadline"] = deadline
    if corr is not None:
        message["corr"] = corr
    if ttl_ms is not None:
        message["ttl_ms"] = ttl_ms

    if seq is not None:
        message["seq"] = seq
    if message_id is not None:
        message["id"] = message_id
    if ts is not None:
        message["ts"] = ts

    if body is None and body_ref is not None:
        body = ""

    if body is not None or body_ref is not None:
        message["body_encoding"] = body_encoding
        message["body"] = encode_body(body)
        if body_ref is not None:
            message["body_ref"] = body_ref

    # W3/W4 optional fields (backward-compatible, default None)
    if "conversation_id" in locals() and conversation_id is not None:
        message["conversation_id"] = conversation_id
    if "card_type" in locals() and card_type is not None:
        message["card_type"] = card_type
    if "artifact_id" in locals() and artifact_id is not None:
        message["artifact_id"] = artifact_id

    return message


def build_review(
    *,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    task_id,
    owner,
    doc_path,
    focus,
    review_deadline,
    reviewers=None,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build a review request message."""
    to_list = normalize_to_list(to)
    body = {
        "doc_path": doc_path,
        "focus": list(focus) if focus is not None else [],
        "reviewers": list(reviewers) if reviewers is not None else to_list,
        "review_deadline": review_deadline,
    }
    return build_message(
        session=session,
        epoch=epoch,
        agent_instance=agent_instance,
        from_role=from_role,
        to=to_list,
        msg_type="ask",
        action="review",
        task_id=task_id,
        owner=owner,
        body=body,
        seq=seq,
        message_id=message_id,
        ts=ts,
    )


def build_assign(
    *,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    task_id,
    owner,
    deadline,
    task_type,
    files,
    success_criteria,
    dependencies=None,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build an assignment request message."""
    body = {
        "task_type": task_type,
        "files": list(files),
        "success_criteria": list(success_criteria),
        "dependencies": list(dependencies) if dependencies is not None else [],
    }
    return build_message(
        session=session,
        epoch=epoch,
        agent_instance=agent_instance,
        from_role=from_role,
        to=to,
        msg_type="ask",
        action="assign",
        task_id=task_id,
        owner=owner,
        deadline=deadline,
        body=body,
        seq=seq,
        message_id=message_id,
        ts=ts,
    )


def build_ask(
    *,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    action,
    task_id,
    owner,
    body,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build a clarify/verify ask message."""
    return build_message(
        session=session,
        epoch=epoch,
        agent_instance=agent_instance,
        from_role=from_role,
        to=to,
        msg_type="ask",
        action=action,
        task_id=task_id,
        owner=owner,
        body=body,
        seq=seq,
        message_id=message_id,
        ts=ts,
    )


def build_send(
    *,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    task_id,
    corr,
    body,
    action="answer",
    owner=None,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build a send/answer message."""
    return build_message(
        session=session,
        epoch=epoch,
        agent_instance=agent_instance,
        from_role=from_role,
        to=to,
        msg_type="send",
        action=action,
        task_id=task_id,
        owner=owner,
        corr=corr,
        body=body,
        seq=seq,
        message_id=message_id,
        ts=ts,
    )


def build_done(
    *,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    task_id,
    corr,
    body,
    action=None,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build a done/verified message."""
    return build_message(
        session=session,
        epoch=epoch,
        agent_instance=agent_instance,
        from_role=from_role,
        to=to,
        msg_type="done",
        action=action,
        task_id=task_id,
        corr=corr,
        body=body,
        seq=seq,
        message_id=message_id,
        ts=ts,
    )


def build_fail(
    *,
    session,
    epoch,
    agent_instance,
    from_role,
    to,
    task_id,
    corr,
    reason,
    blocked_by=None,
    seq=None,
    message_id=None,
    ts=None,
):
    """Build a failure message."""
    body = {
        "reason": reason,
        "blocked_by": list(blocked_by) if blocked_by is not None else [],
    }
    return build_message(
        session=session,
        epoch=epoch,
        agent_instance=agent_instance,
        from_role=from_role,
        to=to,
        msg_type="fail",
        task_id=task_id,
        corr=corr,
        body=body,
        seq=seq,
        message_id=message_id,
        ts=ts,
    )
