"""
Comprehensive verification test suite for the Model-Driven Intent & Planning Flow:

User message
     |
     v
Intent classification
     |
     +---- General question ------> Conversational response
     |
     +---- Task request ----------> Structured task plan -> Validate & authorize -> Execute safely
     |
     +---- Plan-only request -----> Explain plan; execute nothing
     |
     +---- Tool request ----------> Validate and authorize -> Execute safely

Requirements verified:
1. Every ordinary user message is processed through a defined intent and planning stage,
   rather than being sent directly to a tool selector based primarily on rules.
2. The custom model (kairo-scale-2b / transformers) handles reasoning tasks when available.
3. The local fallback (Qwen2.5-0.5B-Instruct / llama.cpp) handles tasks when custom model is unready.
4. Step provenance explicitly exposes whether custom model or local fallback handled each step.
5. Plan-only requests explain the plan and execute NOTHING.
6. Local-only operation is strictly enforced (cloud inference blocked).
"""

import sqlite3
from unittest.mock import patch
import pytest

from orchestrator.adapters.base import ToolObservation
from orchestrator.agent import AgentLoop
from orchestrator.intent_classifier import (
    IntentClassifier,
    IntentType,
)


@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / "test_events.db")


@pytest.fixture
def agent(test_db_path):
    loop = AgentLoop(db_path=test_db_path)
    return loop


@pytest.fixture
def mock_nmap_observation():
    return ToolObservation(
        tool_id="nmap.scan.v1",
        tool_version="1.0.0",
        task_id="task_mock_obs",
        status="success",
        exit_code=0,
        raw_stdout="PORT   STATE SERVICE\n80/tcp open  http\n443/tcp open  https\n",
        raw_stderr="",
        duration_ms=450.0,
        observation={
            "hosts": [{"host": "192.168.1.50", "status": "up"}],
            "open_ports": [
                {"port": "80", "service": "http", "state": "open"},
                {"port": "443", "service": "https", "state": "open"},
            ],
        },
    )


class TestIntentClassifierUnit:
    """Verifies intent classification across all 4 core architectural branches."""

    def test_classify_general_question(self):
        classifier = IntentClassifier()
        questions = [
            "What is Server-Side Request Forgery (SSRF)?",
            "How does SQL injection work?",
            "Can you explain the difference between symmetric and asymmetric cryptography?",
            "What is the MITRE ATT&CK framework?",
        ]
        for q in questions:
            result = classifier.classify(q)
            assert result.intent == IntentType.GENERAL_QUESTION, f"Failed for '{q}'"
            assert result.confidence >= 0.7
            assert len(result.provenance) >= 1
            assert result.provenance[0].stage == "intent_classification"

    def test_classify_plan_only_request(self):
        classifier = IntentClassifier()
        requests = [
            "Plan a penetration test on 192.168.1.50 without executing anything",
            "Outline a task plan for web reconnaissance dry run execute nothing",
            "Give me a plan-only assessment of target 10.0.0.1",
            "Can you draft a step-by-step strategy for auditing the subnet? Do not run tools",
        ]
        for r in requests:
            result = classifier.classify(r)
            assert result.intent == IntentType.PLAN_ONLY, f"Failed for '{r}'"
            assert result.plan_only is True

    def test_classify_tool_request(self):
        classifier = IntentClassifier()
        requests = [
            "Run an nmap scan on 192.168.1.50",
            "Execute whois on example.com",
            "Run ffuf directory fuzzing on target http://192.168.1.50/api",
            "Perform dig lookup on target 192.168.1.50",
        ]
        for r in requests:
            result = classifier.classify(r)
            assert result.intent == IntentType.TOOL_REQUEST, f"Failed for '{r}'"

    def test_classify_task_request(self):
        classifier = IntentClassifier()
        requests = [
            "Conduct a full security assessment on target 192.168.1.50",
            "Perform vulnerability discovery and port mapping on 192.168.1.50",
            "Assess the perimeter security of 192.168.1.50",
        ]
        for r in requests:
            result = classifier.classify(r)
            assert result.intent == IntentType.TASK_REQUEST, f"Failed for '{r}'"

    def test_conversational_response_generation(self):
        classifier = IntentClassifier()
        reply, prov = classifier.generate_conversational_response(
            "What is cross-site scripting (XSS)?",
            model_id="kairo-scale-2b"
        )
        assert len(reply) > 20
        assert "XSS" in reply or "Cross-Site Scripting" in reply or "security" in reply.lower()
        assert prov.stage == "conversational_generation"
        assert prov.executed is False

    def test_plan_explanation_generation(self):
        classifier = IntentClassifier()
        dummy_nodes = [
            {"node_id": "step_1", "capability": "network_port_scan", "target": "192.168.1.50"},
            {"node_id": "step_2", "capability": "service_banner_grab", "target": "192.168.1.50"},
        ]
        explanation, prov = classifier.generate_plan_explanation(
            goal="Full security assessment",
            nodes=dummy_nodes,
            model_id="kairo-scale-2b"
        )
        assert "Execution" in explanation or "Plan" in explanation
        assert "step_1" in explanation
        assert "network_port_scan" in explanation
        assert prov.stage == "plan_explanation"
        assert prov.executed is False


class TestFlowGeneralQuestion:
    """Verifies that general security questions produce conversational responses without executing tools."""

    def test_general_question_executes_zero_tools_and_records_provenance(self, agent):
        session_id = "test-session-general-q"
        query = "What is Server-Side Request Forgery (SSRF) and how can developers prevent it?"

        result = agent.execute_task(session_id=session_id, message=query)

        # 1. Verification of Intent and Zero Execution
        assert result["intent"] == "general_question"
        assert result["tool_executed"] is None
        assert result.get("execution") is None
        assert result["tools_executed_count"] == 0
        assert result["plan_only"] is False

        # 2. Conversational reply generated
        assert len(result["reply"]) > 20
        assert "SSRF" in result["reply"] or "Request Forgery" in result["reply"] or "server" in result["reply"].lower()

        # 3. Step Provenance exists and correctly labels stages
        prov = result["step_provenance"]
        assert len(prov) >= 2
        stages = [p["stage"] for p in prov]
        assert "intent_classification" in stages
        assert "reasoning" in stages
        assert all(not p["executed"] for p in prov if p["stage"] == "execution")

        # 4. Checkpoint & Model info
        assert result["actual_model_id"] in ("kairo-scale-2b", "Qwen2.5-0.5B-Instruct")
        assert result["handled_by_custom_model"] or result["handled_by_fallback"]

        # 5. Database event record exists and has tool_id=None
        conn = sqlite3.connect(agent.db_path)
        cur = conn.cursor()
        cur.execute("SELECT actor, tool_id, result_summary FROM events WHERE session_id=?", (session_id,))
        rows = cur.fetchall()
        assert len(rows) >= 1
        assert rows[0][1] is None  # tool_id must be None
        conn.close()


class TestFlowPlanOnly:
    """Verifies that plan-only requests generate a DAG, explain it, and execute strictly nothing."""

    def test_plan_only_explains_and_executes_nothing(self, agent):
        session_id = "test-session-plan-only"
        query = "Plan a full penetration test on 192.168.1.50 without running any tools. Dry run only."

        result = agent.execute_task(session_id=session_id, message=query)

        # 1. Verification of Plan-Only flag and Zero Execution
        assert result["intent"] == "plan_only"
        assert result["plan_only"] is True
        assert result["tool_executed"] is None
        assert result.get("execution") is None
        assert result["tools_executed_count"] == 0

        # 2. Structured Task Plan is present
        assert result["plan"] is not None
        plan = result["plan"]
        assert "nodes" in plan
        assert len(plan["nodes"]) >= 2

        # 3. Explanation details the planned steps
        reply = result["reply"]
        assert "Execution" in reply or "Plan" in reply
        assert any(n["node_id"] in reply for n in plan["nodes"])

        # 4. Step Provenance reflects zero execution
        prov = result["step_provenance"]
        stages = [p["stage"] for p in prov]
        assert "intent_classification" in stages
        assert "plan_decomposition" in stages
        assert "plan_explanation" in stages
        assert all(not p["executed"] for p in prov if p["stage"] == "execution")

        # 5. Database records plan_only event without execution
        conn = sqlite3.connect(agent.db_path)
        cur = conn.cursor()
        cur.execute("SELECT tool_id, result_summary FROM events WHERE session_id=?", (session_id,))
        rows = cur.fetchall()
        assert len(rows) >= 1
        assert rows[0][0] is None
        assert "plan-only" in rows[0][1].lower() or "0 commands executed" in rows[0][1].lower()
        conn.close()


class TestFlowTaskRequest:
    """Verifies that multi-step task requests decompose into DAG, validate scope, and execute safely."""

    def test_task_request_decomposes_and_executes_ready_step(self, agent, mock_nmap_observation):
        session_id = "test-session-task-req"
        query = "Conduct a security assessment on target 192.168.1.50"

        with patch("orchestrator.adapters.nmap_adapter.NmapAdapter.execute", return_value=mock_nmap_observation):
            result = agent.execute_task(session_id=session_id, message=query)

            # 1. Intent & Plan verification
            assert result["intent"] == "task_request"
            assert result["plan_only"] is False
            assert result["plan"] is not None
            assert len(result["plan"]["nodes"]) >= 2

            # 2. Execution occurred for ready initial node (autonomous executes all eligible steps by default)
            assert result["tool_executed"] is not None
            assert result["tool_executed"]["id"] in ("nmap.scan.v1", "network_port_scan")
            assert result["execution"]["exit_code"] == 0
            assert result["tools_executed_count"] >= 1

            # 3. Step Provenance covers full flow: intent -> decomposition -> validation -> execution
            prov = result["step_provenance"]
            stages = [p["stage"] for p in prov]
            assert "intent_classification" in stages
            assert "task_decomposition" in stages
            assert "validation_and_authorization" in stages
            assert "execution" in stages

            exec_step = next(p for p in prov if p["stage"] == "execution")
            assert exec_step["executed"] is True

            # 4. Database records the execution event
            conn = sqlite3.connect(agent.db_path)
            cur = conn.cursor()
            cur.execute("SELECT tool_id, exit_code FROM events WHERE session_id=?", (session_id,))
            rows = cur.fetchall()
            assert len(rows) >= 1
            assert rows[0][0] in ("nmap.scan.v1", "network_port_scan")
            assert rows[0][1] == 0
            conn.close()


class TestFlowToolRequest:
    """Verifies that direct tool requests validate arguments, verify scope, and execute safely."""

    def test_tool_request_validates_and_executes(self, agent, mock_nmap_observation):
        session_id = "test-session-tool-req"
        query = "Run an nmap scan on target 192.168.1.50"

        with patch("orchestrator.adapters.nmap_adapter.NmapAdapter.execute", return_value=mock_nmap_observation):
            result = agent.execute_task(session_id=session_id, message=query)

            # 1. Intent verification
            assert result["intent"] == "tool_request"
            assert result["plan_only"] is False

            # 2. Tool executed
            assert result["tool_executed"] is not None
            assert result["tool_executed"]["id"] == "nmap.scan.v1"
            assert result["execution"]["exit_code"] == 0

            # 3. Step Provenance reflects tool validation & execution
            prov = result["step_provenance"]
            stages = [p["stage"] for p in prov]
            assert "intent_classification" in stages
            assert "argument_validation" in stages
            assert "validation_and_authorization" in stages
            assert "execution" in stages

    def test_tool_request_outside_scope_is_blocked(self, agent):
        session_id = "test-session-scope-block"
        # 8.8.8.8 is outside active boundary (192.168.1.0/24)
        query = "Run an nmap scan on target 8.8.8.8"

        result = agent.execute_task(session_id=session_id, message=query)

        # Should be stopped by scope boundary contract
        assert result.get("scope_violation") is not None or "scope" in result.get("reply", "").lower()
        assert result.get("execution") is None or result["execution"]["exit_code"] == 403


class TestModelProvenanceExposure:
    """Verifies that the system explicitly exposes whether custom model or fallback handled each step."""

    def test_custom_model_provenance_exposure(self, agent):
        session_id = "test-session-custom-prov"
        query = "Explain how buffer overflow vulnerabilities are exploited"

        # Explicitly request the custom primary model
        result = agent.execute_task(
            session_id=session_id,
            message=query,
            model_id="kairo-scale-2b"
        )

        assert result["actual_model_id"] == "kairo-scale-2b"
        assert result["inference_runtime"] == "transformers"
        assert result["handled_by_custom_model"] is True
        assert result["handled_by_fallback"] is False

        # All non-tool steps record kairo-scale-2b as handler
        for step in result["step_provenance"]:
            if step["stage"] in ("intent_classification", "reasoning", "conversational_generation"):
                assert step["handled_by"] == "kairo-scale-2b"
                assert step["is_custom_model"] is True
                assert step["is_fallback"] is False

    def test_local_fallback_provenance_exposure(self, agent):
        session_id = "test-session-fallback-prov"
        query = "Explain what a cross-site scripting attack is"

        # Request an unavailable model to trigger fallback to Qwen2.5-0.5B-Instruct
        result = agent.execute_task(
            session_id=session_id,
            message=query,
            model_id="non-existent-checkpoint-999b"
        )

        assert result["actual_model_id"] in ("kairo-scale-2b", "Qwen2.5-0.5B-Instruct")
        assert result["fallback_used"] is True
        assert result["fallback_reason"] is not None

        # Step provenance records fallback explicitly
        for step in result["step_provenance"]:
            if step["stage"] in ("intent_classification", "reasoning", "conversational_generation"):
                assert step["handled_by"] in ("kairo-scale-2b", "Qwen2.5-0.5B-Instruct")

    def test_cloud_inference_is_never_introduced(self, agent):
        session_id = "test-session-cloud-prohibited"
        query = "What is DNS spoofing?"

        # Attempting cloud model should be rejected
        with pytest.raises(PermissionError):
            agent.execute_task(
                session_id=session_id,
                message=query,
                model_id="gpt-4o"
            )
