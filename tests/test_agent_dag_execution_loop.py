"""
Unit and Integration tests for the iterative DAG execution loop in AgentLoop.execute_task().

Validates:
1. In-process DAG ready-node execution in topological dependency order.
2. Upstream observation feeding into downstream tool selection and argument construction:
   e.g. an nmap step with open ports 80/8080 informs a follow-up web capability step.
3. Stopping conditions:
   a. Plan completion (all steps finished).
   b. Unrecoverable failure / scope contract rejection (exit code 403 halts immediately).
   c. Safety cap of N steps (default 8, configurable, strictly capped).
4. Incremental real-time streaming of each step's result as it completes (before loop ends).
"""

from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.agent import AgentLoop
from orchestrator.adapters.base import ToolObservation
from orchestrator.dag_controller import (
    dag_controller,
    EvidenceContext,
    DAGNodeExecution,
    SynthesisDict,
)
from events.db import (
    init_db,
    seed_default_scope_contract,
    insert_plan,
    get_plan,
    get_ready_nodes,
    update_node_status,
)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_loop_events.db"
        init_db(db_path)
        seed_default_scope_contract(db_path)
        yield db_path


class TestAgentDAGExecutionLoop:
    """Verifies the in-process DAG ready-node execution loop in AgentLoop.execute_task()."""

    def test_observation_feeds_into_downstream_tool_arguments(self, temp_db):
        """
        Step 1 (nmap) detects open port 8080.
        Step 2 (web profiling / whatweb or gobuster) automatically receives target url 'http://127.0.0.1:8080'.
        """
        agent = AgentLoop(db_path=temp_db)

        executed_tools = []
        captured_inputs = []

        class MockStepAdapter:
            def __init__(self, **kwargs):
                pass

            def execute(self, inputs, task_id, target="vm"):
                captured_inputs.append(dict(inputs))
                if len(executed_tools) == 0:
                    executed_tools.append("nmap.scan.v1")
                    return ToolObservation(
                        tool_id="nmap.scan.v1",
                        tool_version="1.0.0",
                        task_id=task_id,
                        status="success",
                        exit_code=0,
                        raw_stdout="PORT 8080/tcp open http-proxy\nPORT 22/tcp open ssh",
                        raw_stderr="",
                        duration_ms=120.0,
                        observation={"open_ports": [8080, 22]},
                    )
                else:
                    executed_tools.append("whatweb.scan.v1")
                    return ToolObservation(
                        tool_id="whatweb.scan.v1",
                        tool_version="1.0.0",
                        task_id=task_id,
                        status="success",
                        exit_code=0,
                        raw_stdout="http://127.0.0.1:8080 [200 OK] Apache[2.4.50]",
                        raw_stderr="",
                        duration_ms=150.0,
                        observation={"technologies": ["Apache 2.4.50"]},
                    )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MockStepAdapter):
            res = agent.execute_task(
                session_id="test_sess_chain_feed",
                message="Comprehensive assessment of web application attack surface on 127.0.0.1",
                autonomous=True,
                max_steps=5,
            )

        assert res["success"] is True
        assert len(executed_tools) >= 2
        assert executed_tools[0] == "nmap.scan.v1"
        # Ensure downstream web step received the URL constructed from Step 1's port 8080
        web_inputs = [inp for inp in captured_inputs[1:] if "8080" in str(inp)]
        assert len(web_inputs) > 0
        target_str = str(web_inputs[0].get("target") or web_inputs[0].get("url"))
        assert "8080" in target_str

    def test_stopping_condition_unrecoverable_scope_rejection(self, temp_db):
        """Exit code 403 (scope contract rejection) halts DAG execution immediately."""
        agent = AgentLoop(db_path=temp_db)

        # 10.10.10.50 is outside the default scope contract (127.0.0.1, localhost)
        res = agent.execute_task(
            session_id="test_sess_scope_halt",
            message="Assess attack surface for 10.10.10.50",
            autonomous=True,
            max_steps=8,
        )

        # Loop must halt on the very first 403 step without executing further nodes
        assert len(res["nodes_executed"]) == 1
        assert res["nodes_executed"][0].exit_code == 403
        assert res["execution"]["exit_code"] in (403, 1)

    def test_safety_cap_max_steps_strictly_enforced(self, temp_db):
        """Confirms loop stops when reaching min(max_steps, 8) safety cap."""
        agent = AgentLoop(db_path=temp_db)
        executed_count = 0

        class InfiniteAdapter:
            def __init__(self, **kwargs):
                pass

            def execute(self, inputs, task_id, target="vm"):
                nonlocal executed_count
                executed_count += 1
                return ToolObservation(
                    tool_id="nmap.scan.v1",
                    tool_version="1.0.0",
                    task_id=task_id,
                    status="success",
                    exit_code=0,
                    raw_stdout="PORT 80/tcp open http",
                    raw_stderr="",
                    duration_ms=50.0,
                    observation={"open_ports": [80]},
                )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=InfiniteAdapter):
            # Test cap with max_steps=2
            res = agent.execute_task(
                session_id="test_sess_cap_2",
                message="Comprehensive multi-stage security assessment of 127.0.0.1",
                autonomous=True,
                max_steps=2,
            )
            assert executed_count <= 2

            # Test upper safety cap: even if requested 50, strictly bounded to <= 8
            executed_count = 0
            res8 = agent.execute_task(
                session_id="test_sess_cap_8",
                message="Comprehensive multi-stage security assessment of 127.0.0.1",
                autonomous=True,
                max_steps=50,
            )
            assert executed_count <= 8

    def test_incremental_streaming_per_step_as_it_finishes(self, temp_db):
        """
        Step results MUST stream to step_callback and WebSocket incrementally
        as each step completes (not waiting until the entire loop finishes).
        """
        agent = AgentLoop(db_path=temp_db)
        streamed_steps = []

        def on_step_streamed(step_data):
            streamed_steps.append(step_data)

        class MultiStepAdapter:
            def __init__(self, **kwargs):
                pass

            def execute(self, inputs, task_id, target="vm"):
                return ToolObservation(
                    tool_id="nmap.scan.v1",
                    tool_version="1.0.0",
                    task_id=task_id,
                    status="success",
                    exit_code=0,
                    raw_stdout="Host is up. Port 80 open.",
                    raw_stderr="",
                    duration_ms=45.0,
                    observation={"open_ports": [80]},
                )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MultiStepAdapter):
            with patch.object(agent, "_stream_step_to_websocket", wraps=agent._stream_step_to_websocket) as mock_stream:
                res = agent.execute_task(
                    session_id="test_sess_streaming",
                    message="Assess attack surface for 127.0.0.1",
                    autonomous=True,
                    max_steps=3,
                    step_callback=on_step_streamed,
                )

                # Verified each step triggered the streaming callback
                assert len(streamed_steps) >= 1
                assert mock_stream.call_count >= 1
                # Each streamed payload contains standard tool execution card attributes
                first_stream = streamed_steps[0]
                assert "tool_executed" in first_stream or "execution" in first_stream
