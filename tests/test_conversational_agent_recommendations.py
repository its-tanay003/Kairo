"""
Integration tests for Kairo conversational agent recommendations and synthesis.

Verifies:
1. End-to-end task execution yielding conversational synthesis with 4 mandatory sections:
   - ## 1. Executive Summary
   - ## 2. Step-by-Step Breakdown
   - ## 3. Verified Findings & Evidence
   - ## 4. What We Can Do Next
   - Preserves # Security Assessment Synthesis title for backward compatibility.
2. 3-5 actionable click-to-run recommendations with ToolSpec IDs, priority, and rationale.
3. Top-level and synthesis-level next_step_recommendations propagation.
4. Schema conformance of generated recommendations against orchestrator schema validator.
5. Trajectory recording into SQLite for training dataset curation.
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
from orchestrator.conversational_synthesizer import (
    generate_conversational_synthesis,
    generate_next_step_recommendations,
)
from orchestrator.schema_gen import (
    build_recommendation_json_schema,
    build_recommendation_list_json_schema,
)
from events.db import (
    init_db,
    seed_default_scope_contract,
    create_scope_contract,
    get_trajectories,
)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_conv_events.db"
        init_db(db_path)
        seed_default_scope_contract(db_path)
        create_scope_contract(
            targets=["127.0.0.1", "localhost", "10.10.10.50"],
            network_scope="internal",
            time_window="24h",
            allowed_tool_tiers=[1, 2, 3],
            authorized_by="security_admin",
            db_path=db_path,
        )
        yield db_path


class TestConversationalAgentRecommendations:
    """Verifies conversational chat synthesis and recommendation engine."""

    def test_end_to_end_dag_conversational_synthesis(self, temp_db):
        """
        Runs an autonomous DAG task and confirms the 4 mandatory conversational synthesis
        sections and 3-5 click-to-run recommendations are produced.
        """
        agent = AgentLoop(db_path=temp_db)

        step_counter = 0

        class MockSecAdapter:
            def __init__(self, **kwargs):
                pass

            def execute(self, inputs, task_id, target="vm"):
                nonlocal step_counter
                step_counter += 1
                if step_counter == 1:
                    return ToolObservation(
                        tool_id="nmap.scan.v1",
                        tool_version="1.0.0",
                        task_id=task_id,
                        status="success",
                        exit_code=0,
                        raw_stdout="PORT 80/tcp open http Apache/2.4.41\nPORT 22/tcp open ssh OpenSSH 8.2p1",
                        raw_stderr="",
                        duration_ms=100.0,
                        observation={
                            "open_ports": [80, 22],
                            "services": [
                                {"port": 80, "service": "http", "version": "Apache 2.4.41"},
                                {"port": 22, "service": "ssh", "version": "OpenSSH 8.2p1"},
                            ],
                        },
                    )
                else:
                    return ToolObservation(
                        tool_id="gobuster.dir.v1",
                        tool_version="1.0.0",
                        task_id=task_id,
                        status="success",
                        exit_code=0,
                        raw_stdout="/admin (Status: 200)\n/api/v1 (Status: 200)\n/login (Status: 200)",
                        raw_stderr="",
                        duration_ms=150.0,
                        observation={
                            "discovered_paths": ["/admin", "/api/v1", "/login"],
                            "findings": ["Exposed administrative endpoint at /admin"],
                        },
                    )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MockSecAdapter):
            res = agent.execute_task(
                session_id="test_sess_conv_dag",
                message="Assess attack surface and discover sensitive web endpoints on 127.0.0.1",
                autonomous=True,
                max_steps=4,
            )

        assert res["success"] is True
        reply = res.get("reply", "")

        # 1. Mandatory title and 4 conversational sections
        assert "# Security Assessment Synthesis" in reply
        assert "## 1. Executive Summary" in reply
        assert "## 2. Step-by-Step Breakdown" in reply
        assert "## 3. Verified Findings & Evidence" in reply
        assert "## 4. What We Can Do Next" in reply

        # 2. Recommendations propagation
        recs = res.get("next_step_recommendations") or []
        assert isinstance(recs, list)
        assert 3 <= len(recs) <= 5

        # Check structure of each recommendation
        for r in recs:
            assert "title" in r and len(r["title"]) > 0
            assert "prompt" in r and len(r["prompt"]) > 0
            assert "tool_id" in r and len(r["tool_id"]) > 0
            assert r.get("priority") in ("high", "medium", "low")
            assert "rationale" in r and len(r["rationale"]) > 0

        # Check alias recommendations key
        assert res.get("recommendations") == recs

        # Check synthesis object contains next_step_recommendations
        synth = res.get("synthesis") or {}
        assert "next_step_recommendations" in synth or "recommendations" in synth

        # 3. Trajectory recorded in database
        trajectories = get_trajectories(session_id="test_sess_conv_dag", db_path=temp_db)
        assert len(trajectories) >= 1
        traj = trajectories[0]
        assert traj["session_id"] == "test_sess_conv_dag"
        assert len(traj["steps"]) >= 1

    def test_single_tool_conversational_synthesis(self, temp_db):
        """Verifies single tool execution returns conversational synthesis and recommendations."""
        agent = AgentLoop(db_path=temp_db)

        class MockNmapAdapter:
            def __init__(self, **kwargs):
                pass

            def execute(self, inputs, task_id, target="vm"):
                return ToolObservation(
                    tool_id="nmap.scan.v1",
                    tool_version="1.0.0",
                    task_id=task_id,
                    status="success",
                    exit_code=0,
                    raw_stdout="PORT 80/tcp open http Apache/2.4.41",
                    raw_stderr="",
                    duration_ms=60.0,
                    observation={"open_ports": [80], "services": [{"port": 80, "service": "http"}]},
                )

        with patch("orchestrator.adapters.registry.adapter_registry.get", return_value=MockNmapAdapter):
            res = agent.execute_task(
                session_id="test_sess_single_tool",
                message="Run port scan on 127.0.0.1",
                explicit_tool="nmap.scan.v1",
                explicit_args={"target": "127.0.0.1"},
            )

        assert res["exit_code"] == 0
        recs = res.get("next_step_recommendations") or []
        assert isinstance(recs, list)
        assert 3 <= len(recs) <= 5

        for r in recs:
            assert "prompt" in r
            assert "tool_id" in r

    def test_recommendation_schema_conformance(self):
        """Verifies recommendation payloads conform to the defined JSON schemas."""
        recs = generate_next_step_recommendations(
            goal="Scan web server",
            target="127.0.0.1",
            findings=["Discovered port 80 Apache 2.4.41", "Found endpoint /admin"],
            executed_tools=["nmap.scan.v1"],
        )

        assert 3 <= len(recs) <= 5
        rec_schema = build_recommendation_json_schema()
        assert rec_schema["type"] == "object"
        assert "title" in rec_schema["properties"]
        assert "prompt" in rec_schema["properties"]
        assert "tool_id" in rec_schema["properties"]

        for r in recs:
            for required_prop in rec_schema["required"]:
                assert required_prop in r, f"Missing required property {required_prop}"
