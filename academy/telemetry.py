from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

from academy.message import Message

try:
    from opentelemetry import context as otel_context
    from opentelemetry.propagate import extract
    from opentelemetry.propagate import inject
except ImportError:  # pragma: no cover
    otel_context = None
    extract = None
    inject = None


def inject_trace_context(message: Message[Any]) -> Message[Any]:
    """Return a copy of a message carrying the active trace context."""
    if inject is None:
        return message

    carrier: dict[str, str] = {}
    inject(carrier)
    if not carrier:
        return message

    return message.model_copy(
        update={
            'header': message.header.model_copy(
                update={'trace_context': carrier},
            ),
        },
    )


@contextlib.contextmanager
def use_message_trace_context(message: Message[Any]) -> Iterator[None]:
    """Attach a message's trace context while handling it."""
    if (
        otel_context is None
        or extract is None
        or not message.header.trace_context
    ):
        yield
        return

    context = extract(message.header.trace_context)
    token = otel_context.attach(context)
    try:
        yield
    finally:
        otel_context.detach(token)
