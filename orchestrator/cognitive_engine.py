"""
Cognitive Engine for Kairo.

Unified to use `dag_controller.py` as the canonical source of truth for DAG node execution.
Delegates tool selection, prerequisite evidence gating, dynamic argument resolution,
and execution dispatch to DAGController, while attaching Observer, Critic, and
Recovery narrative artifacts.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from pathlib import Path

from events.db import DEFAULT_DB_PATH
from orchestrator.observer import observer, ObservationResult
from orchestrator.critic import critic, CritiqueResult
from orchestrator.recovery_agent import recovery_agent, RecoveryPlan
from orchestrator.reporter import format_recovery_narrative
from orchestrator.dag_controller import dag_controller, EvidenceContext, DAGNodeExecution

logger = logging.getLogger("orchestrator.cognitive_engine")


class CognitiveEngine:
    """
    Cognitive evaluation facade that delegates node scheduling and execution to DAGController
    while providing Observer and Critic evaluation results.
    """

    def __init__(self, db_path: Optional[Path | str] = None, agent: Optional[Any] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.observer = observer
        self.critic = critic
        self.recovery = recovery_agent
        self.dag_controller = dag_controller

    def execute_node(
        self,
        plan_id: str,
        node: Dict[str, Any],
        plan: Dict[str, Any],
        contract: Optional[Dict[str, Any]] = None,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        """
        Executes a single DAG node using dag_controller.py as the single source of truth.
        Enforces prerequisite evidence gating, tool selection, argument resolution,
        and execution through the ExecutionGateway, then attaches Observer and Critic evaluations.
        """
        node_id = node.get("node_id", "node_0") if isinstance(node, dict) else getattr(node, "node_id", "node_0")
        capability = node.get("capability", "general_execution") if isinstance(node, dict) else getattr(node, "capability", "general_execution")
        plan_goal = plan.get("goal", "") if isinstance(plan, dict) else getattr(plan, "goal", "")
        session_id = plan.get("session_id", "plan_session") if isinstance(plan, dict) else getattr(plan, "session_id", "plan_session")
        target = plan.get("target") or (node.get("target") if isinstance(node, dict) else None) or "127.0.0.1"

        logger.info(f"[CognitiveEngine] Delegating execution for node #{node_id} ('{capability}') to DAGController")

        context = EvidenceContext(
            target=str(target),
            session_id=session_id,
            plan_id=plan_id,
        )

        # Delegate execution to DAGController as the single source of truth
        node_exec: DAGNodeExecution = self.dag_controller.execute_node(
            plan_id=plan_id,
            node=node,
            context=context,
            session_id=session_id,
            db_path=self.db_path,
        )

        # Observer converts raw telemetry into structured observation facts
        meta_ctx = {
            "inputs": node_exec.requested_args or {},
            "capability": capability,
            "timed_out": False,
            "attempt": len(node_exec.recovery_path) if node_exec.recovery_path else 1,
        }
        obs: ObservationResult = self.observer.observe(
            tool_id=node_exec.tool_id or "system_ping",
            stdout=node_exec.stdout or "",
            stderr=node_exec.stderr or "",
            exit_code=node_exec.exit_code or 0,
            meta=meta_ctx,
            duration_ms=node_exec.duration_ms,
        )
        obs_dict = obs.to_dict()

        # Critic evaluates progress toward the plan goal
        critique: CritiqueResult = self.critic.evaluate(
            node=node,
            plan_goal=plan_goal,
            observation=obs,
            attempt_number=len(node_exec.recovery_path) if node_exec.recovery_path else 1,
        )
        critique_dict = critique.to_dict()

        # Build human-readable recovery / progress narrative
        narrative = format_recovery_narrative(
            recovery_path=node_exec.recovery_path,
            node_label=node.get("label", capability) if isinstance(node, dict) else capability,
            succeeded=(node_exec.status == "success"),
            final_facts_count=obs.facts.total_facts_count(),
        )

        attempts_count = len(node_exec.recovery_path) if node_exec.recovery_path else 1
        exec_dict = node_exec.to_dict() if hasattr(node_exec, "to_dict") else asdict(node_exec)

        return {
            "node_id": node_id,
            "status": node_exec.status,
            "tool": node_exec.tool_id,
            "attempts": attempts_count,
            "observation": obs_dict,
            "critique": critique_dict,
            "recovery_narrative": narrative,
            "recovery_path": node_exec.recovery_path,
            "command_line": node_exec.command_line,
            "typed_invocation": node_exec.typed_invocation,
            "exit_code": node_exec.exit_code,
            "stdout": node_exec.stdout,
            "stderr": node_exec.stderr,
            "findings_count": node_exec.findings_count,
            "execution_result": exec_dict,
        }

    def _self_correct_arguments(
        self,
        tool_id: str,
        arguments: Dict[str, Any],
        schema_error: str,
        node: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Backward-compatibility helper for schema argument corrections."""
        return dict(arguments)


# Global singleton
cognitive_engine = CognitiveEngine()
