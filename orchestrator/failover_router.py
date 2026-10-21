"""
Failover Router for Kairo Autonomous Agent (Reliability Table).
Monitors tool-call output from the primary-custom model.
When the custom model's tool-call output repeatedly fails ToolSpec schema validation
(per the blueprint's Reliability table, threshold >= 2 consecutive failures),
it automatically fails over to the fallback model (e.g., Qwen2.5-0.5B / Qwen3-Coder),
emits an audited MODEL_FAILOVER event, and preserves task continuity.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from events.db import (
    DEFAULT_DB_PATH,
    Event,
    init_db,
    insert_event,
)
from orchestrator.model_center import ModelCenter, model_center
from training.schema_reward import ToolSpecSchemaValidator

logger = logging.getLogger("orchestrator.failover_router")


@dataclass
class FailoverEventRecord:
    timestamp: str
    from_model: str
    to_model: str
    consecutive_failures: int
    trigger_error: str
    session_id: str
    task_id: str


def build_self_correction_prompt(tool_id: str, arguments: Dict[str, Any], schema_error: str) -> str:
    """Builds a concise self-correction prompt instructing the model to fix invalid tool arguments."""
    return (
        f"CRITICAL: Your proposed tool call for '{tool_id}' failed ToolSpec schema validation:\n"
        f"Input Arguments: {json.dumps(arguments)}\n"
        f"Validation Error: {schema_error}\n\n"
        f"Please self-correct immediately and respond with valid JSON arguments adhering strictly to the ToolSpec schema for '{tool_id}'."
    )


class FailoverRouter:
    """
    Manages runtime schema validation and automatic fallback switching.
    """

    def __init__(
        self,
        failure_threshold: int = 2,
        primary_role: str = "primary-custom",
        fallback_role: str = "fallback",
        db_path: Optional[Path | str] = None,
        model_center_instance: Optional[ModelCenter] = None,
    ):
        self.failure_threshold = failure_threshold
        self.primary_role = primary_role
        self.fallback_role = fallback_role
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.model_center = model_center_instance or model_center
        self.validator = ToolSpecSchemaValidator()
        self.consecutive_schema_failures: int = 0
        self.failover_active: bool = False
        self.active_role: str = primary_role
        self.failover_history: List[FailoverEventRecord] = []

        init_db(self.db_path)

    def reset(self, restore_role: Optional[str] = None) -> None:
        """Resets failover state back to primary model."""
        target_role = restore_role or self.primary_role
        self.consecutive_schema_failures = 0
        self.failover_active = False
        self.active_role = target_role
        try:
            self.model_center.select_model(target_role)
        except Exception as e:
            logger.warning(f"Could not select {target_role} in ModelCenter: {e}")

    def reselect_primary(self, primary_role_or_id: Optional[str] = None) -> Dict[str, Any]:
        """Reselects the primary model in ModelCenter and cleanly resets the circuit-breaker."""
        target = primary_role_or_id or self.primary_role
        self.reset(restore_role=target)
        active = self.model_center.get_active_model()
        return {
            "reselected": True,
            "active_model_id": active.get("model_id"),
            "active_role": active.get("role"),
            "failover_active": self.failover_active,
            "consecutive_failures": self.consecutive_schema_failures,
        }

    def validate_tool_call(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Validates tool call against ToolSpec schema using the formal validator.
        Returns (is_valid, error_message).
        """
        payload = {"tool_id": tool_id, "arguments": arguments}
        res = self.validator.validate_tool_call(payload)
        err = "; ".join(res.errors) if res.errors else None
        return res.is_valid, err

    def attempt_self_correction(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
        error_msg: str,
        generator_fn: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Executes a fast self-correction attempt for invalid arguments.
        """
        prompt = build_self_correction_prompt(tool_id, arguments, error_msg)
        if callable(generator_fn):
            try:
                resp = generator_fn(prompt)
                if isinstance(resp, str):
                    try:
                        parsed = json.loads(resp)
                        if isinstance(parsed, dict):
                            valid, _ = self.validate_tool_call(tool_id, parsed)
                            if valid:
                                return parsed
                    except Exception:
                        pass
                elif isinstance(resp, dict):
                    valid, _ = self.validate_tool_call(tool_id, resp)
                    if valid:
                        return resp
            except Exception as e:
                logger.warning(f"attempt_self_correction failed: {e}")
        return None

    def handle_tool_call_output(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
        session_id: str = "default_session",
        task_id: str = "task_0",
        current_model_id: Optional[str] = None,
        self_correct_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Processes a tool call candidate from the active model.
        If the active model is primary-custom and fails schema validation repeatedly,
        triggers automatic failover to the fallback model.
        Supports fast self-correction callback prior to incrementing failover failure count.
        """
        active_model_meta = self.model_center.get_active_model()
        model_id = current_model_id or active_model_meta.get("model_id", "kairo-custom-model")
        current_role = active_model_meta.get("role", self.active_role)

        # If primary model is reselected while failover was active, auto-recover cleanly
        fallback_meta = self.model_center.get_model_by_role(self.fallback_role) or self.model_center.get_model_by_id(self.fallback_role)
        fallback_id = fallback_meta.get("model_id", self.fallback_role) if fallback_meta else self.fallback_role
        if self.failover_active and model_id != fallback_id and current_role != self.fallback_role:
            self.failover_active = False
            self.consecutive_schema_failures = 0
            self.active_role = current_role
            logger.info(f"Primary model '{model_id}' reselected; recovered cleanly from failover state.")

        # Validate against registered ToolSpec JSON schemas
        is_valid, error_msg = self.validate_tool_call(tool_id, arguments)

        # Fast self-correction attempt before incrementing failure count
        if not is_valid and callable(self_correct_callback):
            try:
                prompt = build_self_correction_prompt(tool_id, arguments, error_msg or "Invalid schema")
                corrected_args = self_correct_callback(tool_id, arguments, error_msg or "", prompt)
                if isinstance(corrected_args, dict):
                    corr_valid, corr_err = self.validate_tool_call(tool_id, corrected_args)
                    if corr_valid:
                        logger.info(
                            f"Fast self-correction succeeded for model '{model_id}' on tool '{tool_id}'."
                        )
                        self.consecutive_schema_failures = 0
                        return {
                            "valid": True,
                            "self_corrected": True,
                            "failover_triggered": False,
                            "failover_active": self.failover_active,
                            "model_id": model_id,
                            "role": current_role,
                            "tool_id": tool_id,
                            "arguments": corrected_args,
                            "error": None,
                            "consecutive_failures": 0,
                        }
                    else:
                        logger.warning(f"Self-corrected arguments still invalid: {corr_err}")
            except Exception as e:
                logger.warning(f"Self-correction callback encountered error: {e}")

        if is_valid:
            # Successful schema validation resets consecutive failure counter
            if self.consecutive_schema_failures > 0:
                logger.info(
                    f"Model {model_id} emitted valid schema. Resetting failure counter (was {self.consecutive_schema_failures})."
                )
            self.consecutive_schema_failures = 0
            return {
                "valid": True,
                "failover_triggered": False,
                "failover_active": self.failover_active,
                "model_id": model_id,
                "role": current_role,
                "tool_id": tool_id,
                "arguments": arguments,
                "error": None,
                "consecutive_failures": 0,
            }

        # Tool call output failed schema validation
        self.consecutive_schema_failures += 1
        logger.warning(
            f"Schema validation failure #{self.consecutive_schema_failures}/{self.failure_threshold} "
            f"for model '{model_id}': {error_msg}"
        )

        # Check if threshold reached
        if self.consecutive_schema_failures >= self.failure_threshold and not self.failover_active:
            # Trigger automatic failover!
            return self._trigger_failover(
                failed_model_id=model_id,
                error_msg=error_msg or "Repeated schema validation failure",
                session_id=session_id,
                task_id=task_id,
                tool_id=tool_id,
                arguments=arguments,
            )

        return {
            "valid": False,
            "failover_triggered": False,
            "failover_active": self.failover_active,
            "model_id": model_id,
            "role": current_role,
            "tool_id": tool_id,
            "arguments": arguments,
            "error": error_msg,
            "consecutive_failures": self.consecutive_schema_failures,
            "threshold": self.failure_threshold,
        }

    def _trigger_failover(
        self,
        failed_model_id: str,
        error_msg: str,
        session_id: str,
        task_id: str,
        tool_id: str,
        arguments: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Executes automatic failover to the fallback model."""
        self.failover_active = True
        self.active_role = self.fallback_role

        fallback_meta = self.model_center.get_model_by_role(self.fallback_role)
        if not fallback_meta:
            fallback_meta = self.model_center.get_model_by_id(self.fallback_role)
        fallback_id = (
            fallback_meta.get("model_id", self.fallback_role)
            if fallback_meta
            else self.fallback_role
        )

        # Switch active model in ModelCenter
        try:
            self.model_center.select_model(self.fallback_role)
        except Exception as e:
            logger.error(f"Failed to switch model in ModelCenter: {e}")

        now_iso = datetime.now(timezone.utc).isoformat()
        rec = FailoverEventRecord(
            timestamp=now_iso,
            from_model=failed_model_id,
            to_model=fallback_id,
            consecutive_failures=self.consecutive_schema_failures,
            trigger_error=error_msg,
            session_id=session_id,
            task_id=task_id,
        )
        self.failover_history.append(rec)

        # Log audited event to SQLite EventStore
        try:
            insert_event(
                Event.create(
                    session_id=session_id,
                    task_id=task_id,
                    actor="failover_router",
                    tool_id="circuit_breaker.failover",
                    exit_code=1,
                    result_summary=(
                        f"AUTOMATIC FAILOVER: Model '{failed_model_id}' failed schema validation "
                        f"{self.consecutive_schema_failures} consecutive times. "
                        f"Failing over to '{fallback_id}' (role={self.fallback_role})."
                    ),
                    network_context={
                        "event_type": "MODEL_FAILOVER",
                        "from_model": failed_model_id,
                        "to_model": fallback_id,
                        "consecutive_failures": self.consecutive_schema_failures,
                        "threshold": self.failure_threshold,
                        "trigger_tool": tool_id,
                        "trigger_error": error_msg,
                    },
                ),
                db_path=self.db_path,
            )
        except Exception as e:
            logger.warning(f"Could not log failover event to EventStore: {e}")

        logger.critical(
            f"🚨 AUTOMATIC FAILOVER TRIGGERED: Switched from {failed_model_id} -> {fallback_id}. "
            f"Cause: {self.consecutive_schema_failures} consecutive schema failures."
        )

        return {
            "valid": False,
            "failover_triggered": True,
            "failover_active": True,
            "failed_model": failed_model_id,
            "fallback_model": fallback_id,
            "fallback_role": self.fallback_role,
            "consecutive_failures": self.consecutive_schema_failures,
            "error": error_msg,
            "message": f"Automatically failed over to fallback model {fallback_id} due to repeated schema validation failures.",
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns the current failover status and health."""
        active_meta = self.model_center.get_active_model()
        return {
            "failover_active": self.failover_active,
            "active_role": active_meta.get("role", self.active_role),
            "active_model_id": active_meta.get("model_id"),
            "consecutive_schema_failures": self.consecutive_schema_failures,
            "failure_threshold": self.failure_threshold,
            "primary_role": self.primary_role,
            "fallback_role": self.fallback_role,
            "total_failovers": len(self.failover_history),
            "latest_failover": self.failover_history[-1].__dict__ if self.failover_history else None,
        }


# Global instance
failover_router = FailoverRouter()
