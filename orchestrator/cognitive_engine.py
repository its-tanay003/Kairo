"""
Cognitive Engine for Kairo.

Coordinates the autonomous cognitive loop:
1. Tool Selection (Hybrid 7-Factor utility scoring)
2. Scope Contract Authorization Gateway
3. Execution (Host or Kali VM sandbox)
4. Observer (reusing Task 1.3 parsers -> structured facts)
5. Critic (progress validation & no-progress flagging)
6. Recovery Agent (timeout / malformed args / missing tool / parser mismatch / 3-attempt capping)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional
from pathlib import Path

from events.db import (
    Event,
    insert_event,
    update_node_status,
    get_plan,
    get_tool_tier,
    validate_scope_request,
    DEFAULT_DB_PATH,
)
from orchestrator.observer import observer, ObservationResult
from orchestrator.critic import critic, CritiqueResult
from orchestrator.recovery_agent import recovery_agent, RecoveryPlan
from orchestrator.tool_selector import tool_selector
from orchestrator.agent import AgentLoop
from orchestrator.reporter import format_recovery_narrative

logger = logging.getLogger("orchestrator.cognitive_engine")


class CognitiveEngine:
    def __init__(self, db_path: Optional[Path | str] = None, agent: Optional[AgentLoop] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.agent = agent or AgentLoop(db_path=self.db_path)
        self.observer = observer
        self.critic = critic
        self.recovery = recovery_agent

    def execute_node(
        self,
        plan_id: str,
        node: Dict[str, Any],
        plan: Dict[str, Any],
        contract: Dict[str, Any],
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        """
        Executes a single DAG node through the full Observer -> Critic -> Recovery Agent cycle.
        Strictly caps recovery attempts at max_attempts (default 3) before failing and surfacing to user.
        Maintains an unbroken causal chain of events via parent_event.
        """
        node_id = node["node_id"]
        capability = node.get("capability", "general_execution")
        plan_goal = plan.get("goal", "")
        session_id = plan.get("session_id", "plan_session")

        logger.info(f"[CognitiveEngine] Starting execution for node #{node_id} ('{capability}') in plan {plan_id}")

        # Reset any prior attempts for this node execution session
        self.recovery.reset_node(plan_id, node_id)
        self.recovery.max_attempts = max_attempts

        # Initial tool selection
        sel = tool_selector.select(
            goal=f"Execute capability '{capability}': {node.get('label', '')} - {node.get('description', '')}",
            required_capability=capability,
            session_id=session_id,
            top_k=3,
        )
        current_tool = sel.selected_tool.tool_id
        current_args = dict(sel.selected_tool.inferred_args)
        failed_tools: List[str] = []

        execution_history: List[Dict[str, Any]] = []
        previous_observations: List[Dict[str, Any]] = []
        recovery_path: List[Dict[str, Any]] = []
        current_parent_event: Optional[str] = None

        update_node_status(
            plan_id=plan_id,
            node_id=node_id,
            status="running",
            assigned_tool=current_tool,
            db_path=self.db_path,
        )

        for attempt in range(1, max_attempts + 1):
            logger.info(
                f"[CognitiveEngine] Attempt {attempt}/{max_attempts} for node #{node_id} "
                f"using tool '{current_tool}' (parent_event={current_parent_event})"
            )

            # Step 1: Validate Tool Tier against Active Scope Contract
            tool_tier = get_tool_tier(current_tool)
            if tool_tier not in contract.get("allowed_tool_tiers", []):
                reason_msg = (
                    f"Blocked by Scope Contract: Tool '{current_tool}' is Tier {tool_tier}, "
                    f"outside authorized tiers {contract.get('allowed_tool_tiers')}"
                )
                update_node_status(
                    plan_id=plan_id,
                    node_id=node_id,
                    status="failed",
                    result=reason_msg,
                    assigned_tool=current_tool,
                    db_path=self.db_path,
                )
                rejection_event = Event.create(
                    session_id=session_id,
                    task_id=f"{plan_id}_{node_id}",
                    actor="gateway:scope_guard",
                    tool_id=current_tool,
                    exit_code=403,
                    result_summary=f"SCOPE_REJECTION: Node #{node_id} blocked. Tool tier {tool_tier} not permitted.",
                    confidence=0.0,
                    parent_event=current_parent_event,
                    network_context={"plan_id": plan_id, "node_id": node_id, "tool_tier": tool_tier, "authorized": False},
                )
                insert_event(rejection_event, self.db_path)
                return {
                    "node_id": node_id,
                    "status": "failed",
                    "tool": current_tool,
                    "error": reason_msg,
                    "attempts": attempt,
                    "surfaced_to_user": True,
                }

            # Step 2: Execute Tool via Agent / Sandbox (chained via parent_event)
            t0 = time.time()
            exec_res = self.agent.execute_task(
                session_id=session_id,
                message=f"Execute capability '{capability}' with {current_tool}",
                task_id=f"{plan_id}_{node_id}_try{attempt}",
                explicit_tool=current_tool,
                explicit_args=current_args,
                parent_event=current_parent_event,
            )
            duration_ms = round((time.time() - t0) * 1000, 2)
            exec_event_id = str(exec_res.get("event_id")) if exec_res.get("event_id") else None

            raw_details = exec_res.get("execution") or {}
            raw_stdout = raw_details.get("stdout", "") or exec_res.get("reply", "")
            raw_stderr = raw_details.get("stderr", "")
            exit_code = raw_details.get("exit_code", 0 if exec_res.get("status") != "rejected" else 1)
            timed_out = bool(raw_details.get("timed_out"))

            # Step 3: Observer Converts Raw Telemetry into Structured Observation Facts
            meta_ctx = {
                "inputs": current_args,
                "capability": capability,
                "timed_out": timed_out,
                "attempt": attempt,
            }
            obs: ObservationResult = self.observer.observe(
                tool_id=current_tool,
                stdout=raw_stdout,
                stderr=raw_stderr,
                exit_code=exit_code,
                meta=meta_ctx,
                duration_ms=duration_ms,
            )
            obs_dict = obs.to_dict()
            previous_observations.append(obs_dict)

            # Step 4: Critic Evaluates Progress
            critique: CritiqueResult = self.critic.evaluate(
                node=node,
                plan_goal=plan_goal,
                observation=obs,
                previous_observations=previous_observations[:-1],
                attempt_number=attempt,
            )
            critique_dict = critique.to_dict()

            attempt_record = {
                "attempt": attempt,
                "tool": current_tool,
                "args": current_args,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "observation_summary": obs.summary,
                "facts_count": obs.facts.total_facts_count(),
                "critique": critique.critique,
                "has_progress": critique.has_progress,
                "critic_status": critique.status,
                "event_id": exec_event_id,
                "parent_event": current_parent_event,
            }
            execution_history.append(attempt_record)

            # Step 5: Check if Progress Was Achieved
            if critique.has_progress:
                logger.info(f"[CognitiveEngine] Node #{node_id} succeeded on attempt {attempt}: {obs.summary}")

                # Build final resolution step for recovery path if recovery occurred
                if attempt > 1 or recovery_path:
                    facts_desc = []
                    if len(obs.facts.endpoints) > 0:
                        facts_desc.append(f"found {len(obs.facts.endpoints)} endpoints")
                    elif len(obs.facts.ports) > 0:
                        facts_desc.append(f"found {len(obs.facts.ports)} open ports")
                    elif len(obs.facts.vulnerabilities) > 0:
                        facts_desc.append(f"found {len(obs.facts.vulnerabilities)} vulnerabilities")
                    elif len(obs.facts.credentials) > 0:
                        facts_desc.append(f"found {len(obs.facts.credentials)} credentials")
                    else:
                        facts_desc.append(f"found {obs.facts.total_facts_count()} facts")

                    res_detail = f"succeeded, {', '.join(facts_desc)}"
                    recovery_path.append({
                        "attempt": attempt,
                        "action": f"Executed {current_tool}",
                        "tool": current_tool,
                        "args": current_args,
                        "status": "succeeded",
                        "details": res_detail,
                        "event_id": exec_event_id,
                        "parent_event": current_parent_event,
                    })

                narrative = format_recovery_narrative(
                    recovery_path=recovery_path,
                    node_label=node.get("label", capability),
                    succeeded=True,
                    final_facts_count=obs.facts.total_facts_count(),
                )

                final_result = {
                    "summary": obs.summary,
                    "facts": obs.facts.to_dict(),
                    "critique": critique_dict,
                    "attempts": attempt,
                    "tool": current_tool,
                    "duration_ms": duration_ms,
                    "recovery_narrative": narrative,
                    "recovery_path": recovery_path,
                    "history": execution_history,
                }
                update_node_status(
                    plan_id=plan_id,
                    node_id=node_id,
                    status="success",
                    result=final_result,
                    assigned_tool=current_tool,
                    db_path=self.db_path,
                )

                # Log success event linked to the execution event
                success_event = Event.create(
                    session_id=session_id,
                    task_id=f"{plan_id}_{node_id}",
                    actor="cognitive_engine:critic",
                    tool_id=current_tool,
                    exit_code=0,
                    result_summary=f"SUCCESS: Node #{node_id} confirmed progress ({obs.facts.total_facts_count()} facts discovered).",
                    confidence=critique.score,
                    parent_event=exec_event_id or current_parent_event,
                    network_context={
                        "node_id": node_id,
                        "facts": obs.facts.to_dict(),
                        "critique": critique.critique,
                        "recovery_narrative": narrative,
                    },
                )
                insert_event(success_event, self.db_path)

                return {
                    "node_id": node_id,
                    "status": "success",
                    "tool": current_tool,
                    "attempts": attempt,
                    "observation": obs_dict,
                    "critique": critique_dict,
                    "recovery_narrative": narrative,
                    "recovery_path": recovery_path,
                    "history": execution_history,
                }

            # Step 6: No-Progress or Failure -> Recovery Agent Intervenes
            logger.warning(
                f"[CognitiveEngine] Node #{node_id} flagged '{critique.status}' on attempt {attempt}. "
                f"Engaging Recovery Agent..."
            )

            rec_plan: RecoveryPlan = self.recovery.formulate_recovery(
                plan_id=plan_id,
                node=node,
                current_tool=current_tool,
                current_args=current_args,
                stdout=raw_stdout,
                stderr=raw_stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                parser_mismatch=obs.parser_mismatch,
                critic_status=critique.status,
                critique_msg=critique.critique,
                session_id=session_id,
            )

            # Determine diagnostics & transition for human-readable narrative
            if timed_out:
                fail_detail = f"timed out after {int(duration_ms/1000) or 30}s"
            elif obs.parser_mismatch:
                fail_detail = "parser schema mismatch on output"
            elif "malformed" in critique.status.lower() or "arg" in critique.critique.lower():
                fail_detail = "malformed arguments rejected by schema"
            elif exit_code != 0:
                fail_detail = f"exited with error code {exit_code}"
            else:
                fail_detail = "no progress detected (zero facts found)"

            if rec_plan.strategy == "switch_tool":
                transition = f"switched to {rec_plan.tool_id}"
                if rec_plan.repaired_args:
                    if "threads" in rec_plan.repaired_args:
                        transition += " with reduced thread count"
                    elif "wordlist" in rec_plan.repaired_args:
                        transition += " with common wordlist"
            elif rec_plan.strategy == "retry_timeout":
                transition = "retried with increased timeout & lighter flags"
            elif rec_plan.strategy == "repair_args":
                transition = "repaired arguments against tool schema"
            else:
                transition = f"strategy {rec_plan.strategy}"

            step_entry = {
                "attempt": attempt,
                "action": f"Attempted {current_tool}",
                "tool": current_tool,
                "args": current_args,
                "status": "failed",
                "error_type": rec_plan.error_type,
                "details": fail_detail,
                "recovery_strategy": rec_plan.strategy,
                "transition": transition,
                "event_id": exec_event_id,
                "parent_event": current_parent_event,
            }
            recovery_path.append(step_entry)

            # Check if Recovery Cap Exceeded
            if not rec_plan.can_recover or attempt >= max_attempts:
                logger.error(
                    f"[CognitiveEngine] RECOVERY EXHAUSTED for node #{node_id} after {attempt} attempts. "
                    f"Surfacing failure to user."
                )
                narrative = format_recovery_narrative(
                    recovery_path=recovery_path,
                    node_label=node.get("label", capability),
                    succeeded=False,
                )
                failure_payload = {
                    "error": "RECOVERY_EXHAUSTED",
                    "reason": rec_plan.reason,
                    "attempts": attempt,
                    "max_attempts": max_attempts,
                    "last_tool": current_tool,
                    "critique": critique_dict,
                    "last_observation": obs_dict,
                    "recovery_narrative": narrative,
                    "recovery_path": recovery_path,
                    "history": execution_history,
                    "surfaced_to_user": True,
                }
                update_node_status(
                    plan_id=plan_id,
                    node_id=node_id,
                    status="failed",
                    result=failure_payload,
                    assigned_tool=current_tool,
                    db_path=self.db_path,
                )
                return {
                    "node_id": node_id,
                    "status": "failed",
                    "error": "RECOVERY_EXHAUSTED",
                    "attempts": attempt,
                    "reason": rec_plan.reason,
                    "recovery_narrative": narrative,
                    "recovery_path": recovery_path,
                    "history": execution_history,
                    "surfaced_to_user": True,
                }

            # Apply Recovery Plan Strategy for Next Attempt
            if rec_plan.strategy == "switch_tool":
                failed_tools.append(current_tool)
                current_tool = rec_plan.tool_id
                current_args = rec_plan.repaired_args
            elif rec_plan.strategy in ("repair_args", "retry_timeout"):
                current_args = rec_plan.repaired_args

            # Log recovery intervention event linked to the failed execution event
            rec_event = Event.create(
                session_id=session_id,
                task_id=f"{plan_id}_{node_id}",
                actor=f"recovery_agent:strategy:{rec_plan.strategy}",
                tool_id=current_tool,
                exit_code=0,
                result_summary=f"RECOVERY_ATTEMPT {attempt+1}: {fail_detail} -> {transition}",
                confidence=0.8,
                parent_event=exec_event_id or current_parent_event,
                network_context={"strategy": rec_plan.strategy, "repaired_args": current_args, "step": step_entry},
            )
            rec_event_id = str(insert_event(rec_event, self.db_path))

            # The next attempt's causal parent is this recovery intervention!
            current_parent_event = rec_event_id

        # Fallthrough safety
        return {
            "node_id": node_id,
            "status": "failed",
            "error": "RECOVERY_EXHAUSTED",
            "attempts": max_attempts,
            "surfaced_to_user": True,
        }


# Global singleton
cognitive_engine = CognitiveEngine()
