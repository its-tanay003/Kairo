"""
Tests for Trustworthy Execution Results in Kairo.

Verifies:
1. Kairo never reports success just because a command was attempted or formatted.
2. Every execution produces a real status, recorded command line, typed invocation, and true exit code.
3. If an adapter or tool fails, the agent explains the error with diagnostics instead of inventing success.
4. Active findings verification engine performs scope-gated live checks (sockets, HTTP, banners).
5. Failed DAG nodes do not contaminate evidence store with fabricated findings.
"""

import socket
import threading
import time
from pathlib import Path
from typing import Dict, Any

import pytest

from events.db import init_db
from orchestrator.agent import AgentLoop
from orchestrator.claude_synthesis import (
    synthesize_agent_response,
    _synthesize_nmap_scan,
    _synthesize_web_audit,
    _synthesize_domain_recon,
    _synthesize_generic_execution,
)
from orchestrator.dag_controller import DAGController, EvidenceContext
from orchestrator.evidence_store import EvidenceStore, Finding
from orchestrator.finding_verifier import FindingVerifier


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "test_trustworthy.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def agent(temp_db: Path):
    return AgentLoop(db_path=temp_db)


@pytest.fixture
def evidence_store(temp_db: Path, tmp_path: Path):
    art_dir = tmp_path / "artifacts"
    return EvidenceStore(db_path=temp_db, artifacts_dir=art_dir)


class TestTruthfulExitCodesAndInvocations:
    """Tests ensuring truthful exit codes, real status, and recorded invocations."""

    def test_unregistered_tool_returns_127_and_error_status(self, agent: AgentLoop):
        """Unregistered tool must exit 127 with status 'error' and explain tool is not registered."""
        result = agent.execute_task(
            session_id="test_session",
            message="Run nonexistent_super_tool against 127.0.0.1",
            explicit_tool="nonexistent_super_tool",
            explicit_args={"target": "127.0.0.1"},
        )
        assert result["exit_code"] == 127
        assert result["status"] == "error"
        assert "Tool 'nonexistent_super_tool' is not an authorized or registered tool adapter" in result["execution"]["stderr"]
        assert result["command_line"] != ""
        assert result["typed_invocation"]["tool"] == "nonexistent_super_tool"
        assert result["typed_invocation"]["arguments"] == {"target": "127.0.0.1"}

    def test_adapter_exception_returns_nonzero_exit_code(self, agent: AgentLoop, monkeypatch):
        """When an adapter raises an exception, exit_code must NOT be forged to 0."""
        from orchestrator.adapters.registry import adapter_registry

        class BrokenAdapter:
            tool_version = "v1"
            def __init__(self, **kwargs):
                pass
            def execute(self, inputs, task_id, target):
                raise RuntimeError("Network socket allocation failed in test")

        monkeypatch.setitem(adapter_registry, "broken.test.v1", BrokenAdapter)

        result = agent.execute_task(
            session_id="test_session",
            message="Run broken adapter",
            explicit_tool="broken.test.v1",
            explicit_args={"target": "127.0.0.1"},
        )
        assert result["exit_code"] == 1
        assert result["status"] == "error"
        assert "Network socket allocation failed in test" in result["execution"]["stderr"]
        assert result["typed_invocation"]["tool"] == "broken.test.v1"
        assert "Execution error in adapter 'broken.test.v1'" in result["execution"]["stderr"]

    def test_recorded_command_and_typed_invocation_in_standard_tools(self, agent: AgentLoop):
        """Standard built-in tools must record CLI command line and typed invocation."""
        result = agent.execute_task(
            session_id="test_session",
            message="Test system health",
            explicit_tool="system_ping",
            explicit_args={},
        )
        assert result["exit_code"] == 0
        assert result["status"] == "success"
        assert result["command_line"] == "kairo-diag --self-test"
        assert result["typed_invocation"]["tool"] == "system_ping"
        assert isinstance(result["typed_invocation"]["arguments"], dict)


class TestHonestSynthesisReporting:
    """Tests ensuring Claude-style synthesis engine never claims success on failed runs."""

    def test_nmap_scan_synthesis_on_failure(self):
        """When nmap fails, synthesis must report failure and not claim 0 open ports or clean posture."""
        synth = _synthesize_nmap_scan(
            user_goal="Scan 10.10.10.50",
            inputs={"target": "10.10.10.50", "ports": "80,443"},
            exit_code=1,
            stdout="",
            stderr="Host unreachable: route down",
            duration_s=1.2,
        )
        assert "❌ Execution Failed" in synth["reply"]
        assert "Host unreachable: route down" in synth["reply"]
        assert synth["process"]["status"] == "error"
        assert synth["result"]["status"] == "failed"
        assert "Scan Failed" in synth["result"]["security_posture"]
        # Must NOT claim 'No Open Ports Exposed' (which falsely implies clean perimeter)
        assert "No Open Ports Exposed" not in synth["result"]["security_posture"]
        assert len(synth["output"]["findings_table"]) == 0

    def test_web_audit_synthesis_on_failure(self):
        """When web audit fails, synthesis must report failure rather than 'Audit Completed'."""
        synth = _synthesize_web_audit(
            user_goal="Audit web service",
            tool_id="zap.gui.v1",
            tool_name="OWASP ZAP",
            inputs={"target": "http://192.168.1.100"},
            exit_code=2,
            stdout="",
            stderr="Connection refused by remote host",
            duration_s=2.0,
        )
        assert "❌ Execution Failed" in synth["reply"]
        assert "Connection refused" in synth["reply"]
        assert synth["result"]["status"] == "failed"
        assert "Audit Failed" in synth["result"]["security_posture"]
        assert len(synth["output"]["findings_table"]) == 0

    def test_generic_execution_synthesis_on_failure(self):
        """Generic command execution must not be reported as 'Completed with Warnings' on non-zero exit."""
        synth = _synthesize_generic_execution(
            user_goal="Run custom exploit script",
            tool_id="shell.run.v1",
            tool_name="Shell Runner",
            inputs={"command": "python", "args": ["exploit.py"]},
            exit_code=127,
            stdout="",
            stderr="exploit.py: File not found",
            duration_s=0.5,
        )
        assert "❌ Execution Failed (Exit Code 127)" in synth["reply"]
        assert "Completed with Warnings" not in synth["reply"]
        assert synth["result"]["status"] == "failed"
        assert "Execution Failed (Exit Code 127)" in synth["result"]["security_posture"]

    def test_domain_recon_synthesis_on_failure(self):
        """Domain reconnaissance must report query failure on non-zero exit code."""
        synth = _synthesize_domain_recon(
            user_goal="Query domain records",
            tool_id="whois.v1",
            tool_name="WHOIS",
            inputs={"domain": "nonexistent-test-domain.internal"},
            exit_code=1,
            stdout="",
            stderr="Name or service not known",
            duration_s=0.8,
        )
        assert "❌ Domain Reconnaissance Failed" in synth["reply"]
        assert synth["result"]["status"] == "failed"
        assert "Reconnaissance Failed" in synth["result"]["security_posture"]


class TestDAGExecutionTrustworthiness:
    """Tests ensuring DAGController execution is transparent and does not fabricate findings."""

    def test_dag_unregistered_node_exits_127(self, temp_db: Path):
        """A DAG node attempting an unregistered tool must exit 127 and report failed status."""
        controller = DAGController(db_path=temp_db)
        from events.db import PlanDAG, PlanNode
        from dataclasses import asdict
        plan = PlanDAG(
            plan_id="plan_unregistered_test",
            session_id="s_test",
            goal="Test unregistered tool handling",
            nodes=[
                PlanNode(
                    node_id="n1",
                    capability="custom_exploit",
                    label="Run unregistered exploit tool",
                    description="Run unregistered exploit tool",
                    assigned_tool="nonexistent_super_tool",
                )
            ],
        )
        controller.evidence_store._ensure_tables()
        from events.db import insert_plan
        insert_plan(plan, db_path=temp_db)

        context = EvidenceContext(plan_id=plan.plan_id, session_id="s_test", target="127.0.0.1")
        res = controller.execute_node(
            plan_id=plan.plan_id,
            session_id="s_test",
            node={"node_id": "n1", "capability": "custom_exploit", "assigned_tool": "nonexistent_super_tool"},
            context=context,
        )
        assert res.status == "failed"
        assert res.exit_code == 127
        assert "not registered" in res.stderr
        assert res.command_line != ""
        assert res.typed_invocation["tool"] != ""

    def test_failed_dag_node_does_not_ingest_false_observations(self, temp_db: Path):
        """Failed execution (exit_code != 0) must skip observation extraction."""
        context = EvidenceContext(plan_id="p1", session_id="s1", target="127.0.0.1")
        # Simulate observation with junk data from a failed run
        junk_obs = {
            "hosts": [{"ip": "10.99.99.99", "ports": [{"port": 8888, "service": "backdoor"}]}],
            "vulnerabilities": [{"title": "Fabricated CVE-9999-9999", "severity": "CRITICAL"}],
        }
        context.ingest_observation(
            node_id="n1",
            capability="port_scan",
            tool_id="nmap.scan.v1",
            obs=junk_obs,
            stdout="open 8888/tcp backdoor",
            exit_code=1,  # FAILED execution
        )
        # Verify nothing was ingested into context
        assert 8888 not in context.open_ports
        assert len(context.vulnerabilities) == 0
        assert context.target_ip != "10.99.99.99"


class TestFindingVerificationEngine:
    """Tests for the FindingVerifier: scope boundary, socket handshake, and status updating."""

    def test_scope_authorization_blocks_out_of_scope_probe(self, temp_db: Path):
        """Finding verifier must reject probes to targets outside authorized ScopeContract."""
        from events.db import create_scope_contract
        create_scope_contract(
            targets=["10.0.0.0/24"],
            network_scope="10.0.0.0/24",
            time_window="8h",
            allowed_tool_tiers=[1, 2, 3],
            authorized_by="Lead Pentester",
            db_path=temp_db,
        )

        verifier = FindingVerifier(db_path=temp_db)
        # Probe an unauthorized IP (e.g. public IP outside 10.0.0.0/24)
        res = verifier.verify_open_port(host="8.8.8.8", port=53)
        assert res["verified"] is False
        assert res["verification_status"] == "blocked_out_of_scope"
        assert "outside authorized ScopeContract" in res["reason"]

    def test_verify_open_port_with_live_socket(self, temp_db: Path):
        """Tests live socket verification against a real listening port on loopback."""
        # 1. Start a real temporary TCP server on loopback
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(1)
        port = server_sock.getsockname()[1]

        def serve_one():
            try:
                conn, _ = server_sock.accept()
                conn.close()
            except Exception:
                pass

        t = threading.Thread(target=serve_one, daemon=True)
        t.start()

        try:
            verifier = FindingVerifier(db_path=temp_db)
            res = verifier.verify_open_port(host="127.0.0.1", port=port, allowed_targets=["127.0.0.1"])
            assert res["verified"] is True
            assert res["verification_status"] == "verified"
            assert res["latency_ms"] >= 0
            assert f"TCP connection successfully established to 127.0.0.1:{port}" in res["details"]
        finally:
            server_sock.close()

    def test_verify_closed_port_refutes_finding(self, temp_db: Path):
        """Probing a closed port must return verified=False with status 'refuted'."""
        verifier = FindingVerifier(db_path=temp_db)
        # Port 59999 is typically unused on local machine
        res = verifier.verify_open_port(host="127.0.0.1", port=59999, timeout=0.5, allowed_targets=["127.0.0.1"])
        assert res["verified"] is False
        assert res["verification_status"] == "refuted"
        assert "connection refused or timed out" in res["details"]

    def test_finding_verification_updates_evidence_store(self, temp_db: Path, evidence_store: EvidenceStore):
        """Full finding verification workflow updates the Finding in EvidenceStore and stores AnalyticEvidence."""
        finding = Finding(
            id="find_test_80",
            title="Open Port 59998 Detected",
            affected_asset="127.0.0.1:59998",
            confidence_score=0.75,
            discovering_tool="nmap.scan.v1",
        )
        evidence_store.store_finding(finding)

        verifier = FindingVerifier(db_path=temp_db, evidence_store=evidence_store)
        verif_result = verifier.verify_finding(finding_id="find_test_80", allowed_targets=["127.0.0.1"])

        assert verif_result["finding_id"] == "find_test_80"
        assert verif_result["verified"] is False
        assert verif_result["verification_status"] == "refuted"
        # Confidence score should drop for refuted finding
        assert verif_result["confidence_score"] < 0.75

        # Check finding persisted in database has new verification metadata
        updated_finding = evidence_store.get_finding("find_test_80")
        assert updated_finding is not None
        assert updated_finding.verified is False
        assert updated_finding.verification_status == "refuted"
        assert updated_finding.verified_at is not None
        assert updated_finding.verification_details is not None

        # Verify an AnalyticEvidence was stored
        analytics = evidence_store.list_findings()
        assert len(analytics) == 1
        assert len(updated_finding.evidence_references) > 0
