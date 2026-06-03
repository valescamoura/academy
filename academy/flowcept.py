from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _safe_repr(value: Any) -> str:
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


@dataclass
class _RuntimeState:
    enabled: bool
    workflow_id: str | None = None
    campaign_id: str | None = None


class AcademyFlowceptProvenance:
    """Optional native Flowcept provenance support for Academy runtimes.

    The integration is intentionally lazy: Academy can be imported and used
    without Flowcept installed. Capture is enabled when either Flowcept is
    already running in the process or a `FLOWCEPT_CAMPAIGN_ID` is present in
    the environment. `ACADEMY_FLOWCEPT_ENABLED=0` disables it explicitly.
    """

    _flowcept = None
    _ref_count = 0
    _workflow_id: str | None = None
    _campaign_id: str | None = None

    @classmethod
    def start_runtime(cls, runtime: Any) -> _RuntimeState:
        if not _env_flag("ACADEMY_FLOWCEPT_ENABLED", True):
            return _RuntimeState(enabled=False)

        try:
            from flowcept import Flowcept
        except Exception:
            return _RuntimeState(enabled=False)

        campaign_id = os.environ.get("FLOWCEPT_CAMPAIGN_ID") or Flowcept.campaign_id
        if not campaign_id and not _env_flag("ACADEMY_FLOWCEPT_AUTOSTART", False):
            return _RuntimeState(enabled=False)

        if cls._flowcept is None or not Flowcept.is_started:
            workflow_name = (
                f"academy_native_{type(runtime.agent).__name__}_{os.getpid()}"
            )
            flowcept = Flowcept(
                workflow_name=workflow_name,
                workflow_subtype="academy_native_runtime",
                workflow_args={
                    "academy_agent": type(runtime.agent).__name__,
                    "academy_agent_id": str(runtime.agent_id),
                    "academy_pid": os.getpid(),
                },
                campaign_id=campaign_id,
                agent_id=str(runtime.agent_id),
                check_safe_stops=False,
                delete_buffer_file=False,
            )
            flowcept.start()
            cls._flowcept = flowcept
            cls._workflow_id = flowcept.current_workflow_id
            cls._campaign_id = flowcept.campaign_id
        else:
            cls._workflow_id = Flowcept.current_workflow_id
            cls._campaign_id = Flowcept.campaign_id

        cls._ref_count += 1
        return _RuntimeState(
            enabled=True,
            workflow_id=cls._workflow_id,
            campaign_id=cls._campaign_id,
        )

    @classmethod
    def stop_runtime(cls, state: _RuntimeState) -> None:
        if not state.enabled:
            return

        cls._ref_count = max(0, cls._ref_count - 1)
        if cls._ref_count > 0 or cls._flowcept is None:
            return

        try:
            cls._flowcept.stop()
        finally:
            cls._flowcept = None
            cls._workflow_id = None
            cls._campaign_id = None

    @classmethod
    def start_action(
        cls,
        *,
        state: _RuntimeState,
        task_id: str,
        action: str,
        source_agent_id: Any,
        agent_id: Any,
        args: Any,
        kwargs: Any,
        request: Any,
    ) -> Any | None:
        if not state.enabled:
            return None

        try:
            from flowcept import FlowceptTask
        except Exception:
            return None

        custom_metadata = {
            "semantic_record_type": "academy_action",
            "instrumentation_layer": "academy_native",
            "academy": {
                "message_tag": str(request.tag),
                "message_label": str(request.label) if request.label is not None else None,
                "request_kind": request.header.kind,
                "action": action,
                "pid": os.getpid(),
            },
        }

        try:
            return FlowceptTask(
                task_id=task_id,
                workflow_id=state.workflow_id,
                campaign_id=state.campaign_id,
                activity_id=action,
                agent_id=str(agent_id),
                source_agent_id=str(source_agent_id),
                used={"args": args, "kwargs": kwargs},
                subtype="academy_action",
                adapter_id="academy_native",
                tags=["academy", "native", "action"],
                custom_metadata=custom_metadata,
                started_at=time.time(),
            )
        except Exception:
            return None

    @classmethod
    def end_action(
        cls,
        task: Any | None,
        *,
        generated: dict[str, Any] | None = None,
        exception: BaseException | None = None,
        custom_metadata: dict[str, Any] | None = None,
    ) -> None:
        if task is None:
            return

        try:
            from flowcept.commons.vocabulary import Status
        except Exception:
            return

        try:
            if exception is None:
                task.end(
                    generated=generated,
                    status=Status.FINISHED,
                    custom_metadata=custom_metadata,
                )
            else:
                task.end(
                    generated={
                        "exception_type": type(exception).__name__,
                        "exception": str(exception),
                    },
                    stderr=_safe_repr(exception),
                    status=Status.ERROR,
                    custom_metadata=custom_metadata,
                )
        except Exception:
            return

    @classmethod
    def emit_lifecycle(
        cls,
        *,
        state: _RuntimeState,
        activity_id: str,
        agent_id: Any,
        status: str = "FINISHED",
        custom_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not state.enabled:
            return

        try:
            from flowcept import FlowceptTask
            from flowcept.commons.vocabulary import Status
        except Exception:
            return

        started_at = time.time()
        try:
            metadata = custom_metadata or {}
            academy_metadata = {
                "pid": os.getpid(),
                **metadata.get("academy", {}),
            }
            task = FlowceptTask(
                workflow_id=state.workflow_id,
                campaign_id=state.campaign_id,
                activity_id=activity_id,
                agent_id=str(agent_id),
                subtype="academy_lifecycle",
                adapter_id="academy_native",
                tags=["academy", "native", "lifecycle"],
                used={"agent_id": str(agent_id)},
                custom_metadata={
                    "semantic_record_type": "academy_lifecycle",
                    "instrumentation_layer": "academy_native",
                    **{key: value for key, value in metadata.items() if key != "academy"},
                    "academy": academy_metadata,
                },
                started_at=started_at,
            )
            task.end(status=Status(status))
        except Exception:
            return

    @classmethod
    def start_loop(
        cls,
        *,
        state: _RuntimeState,
        loop_name: str,
        agent_id: Any,
    ) -> Any | None:
        if not state.enabled:
            return None

        try:
            from flowcept import FlowceptTask
        except Exception:
            return None

        try:
            return FlowceptTask(
                workflow_id=state.workflow_id,
                campaign_id=state.campaign_id,
                activity_id=loop_name,
                agent_id=str(agent_id),
                used={"loop_name": loop_name},
                subtype="academy_loop",
                adapter_id="academy_native",
                tags=["academy", "native", "loop"],
                custom_metadata={
                    "semantic_record_type": "academy_loop",
                    "instrumentation_layer": "academy_native",
                    "academy": {
                        "loop_name": loop_name,
                        "pid": os.getpid(),
                    },
                },
                started_at=time.time(),
            )
        except Exception:
            return None
