"""
Tests for Tool Knowledge Center, Automatic Update Subsystem, and Execution Modes in KAIRO.
Verifies ADR-004 adherence, 13-section metadata extraction, live health verification,
pre-update snapshot rollback, and execution mode gating (autonomous, plan_only, step_by_step).
"""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from orchestrator.server import app
from orchestrator.tool_knowledge_center import tool_knowledge_center, ToolKnowledgeCenter
from orchestrator.update_manager import update_manager, UpdatePolicy, UpdateManager
from orchestrator.dag_controller import dag_controller, EvidenceContext
from events.db import init_db, PlanDAG, PlanNode, insert_plan, get_plan, create_scope_contract


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_knowledge_updates.db"
    init_db(db_file)
    # Seed active scope contract
    create_scope_contract(
        targets=["192.168.1.0/24", "127.0.0.1", "target.local"],
        network_scope="authorized_lab",
        authorized_by="operator@kairo.local",
        time_window="24h",
        db_path=db_file,
    )
    return db_file


def test_tool_knowledge_center_list_tools():
    """Verify tool listing returns registered tools with 13-section capability summary."""
    tools = tool_knowledge_center.list_tools()
    assert len(tools) > 0

    # Verify canonical registered tools exist
    tool_ids = [t["tool_id"] for t in tools]
    assert "nmap.scan.v1" in tool_ids
    assert "gobuster.dir.v1" in tool_ids
    assert "sqlmap.scan.v1" in tool_ids

    # Check structure of a summary item
    nmap_summary = next(t for t in tools if t["tool_id"] == "nmap.scan.v1")
    assert nmap_summary["name"]
    assert nmap_summary["category"] == "recon"
    assert "capabilities" in nmap_summary
    assert "is_installed" in nmap_summary
    assert "health_status" in nmap_summary


def test_tool_knowledge_center_get_details():
    """Verify 13-section technical metadata for a registered tool."""
    detail = tool_knowledge_center.get_tool_details("nmap.scan.v1")
    assert detail is not None
    assert detail["tool_id"] == "nmap.scan.v1"
    assert detail["name"]
    assert detail["category"] == "recon"
    assert detail["license"]
    assert detail["official_docs"]
    assert len(detail["natural_language_examples"]) > 0
    assert len(detail["cli_examples"]) > 0
    assert "operational_guidance" in detail
    assert "noisy_flags" in detail["operational_guidance"]
    assert "safety_notes" in detail["operational_guidance"]
    assert "timeout_advice" in detail["operational_guidance"]
    assert "chat_prompt_template" in detail
    assert "recent_runs" in detail
    assert "success_rate_pct" in detail


def test_tool_knowledge_center_verify_live_tool():
    """Verify health verification probe executes benign version query."""
    res = tool_knowledge_center.verify_tool("nmap.scan.v1")
    assert res["tool_id"] == "nmap.scan.v1"
    assert "health_status" in res
    assert "duration_ms" in res
    assert res["health_status"] in ("healthy", "warning", "missing")


def test_update_manager_check_updates():
    """Verify update discovery lists system, tool, and database update items."""
    updates = update_manager.check_updates()
    assert len(updates) > 0
    ids = [u.id for u in updates]
    assert "db_searchsploit" in ids or "db_nmap_scripts" in ids or "tool_nmap" in ids


def test_update_manager_policy_configuration():
    """Verify update policy can be changed between standard_managed, managed_rolling, and manual_control."""
    assert update_manager.set_policy("managed_rolling") is True
    assert update_manager.policy == UpdatePolicy.MANAGED_ROLLING

    assert update_manager.set_policy("manual_control") is True
    assert update_manager.policy == UpdatePolicy.MANUAL_CONTROL

    assert update_manager.set_policy("invalid_policy") is False


def test_update_manager_apply_and_rollback(temp_db):
    """Verify applying update creates snapshot, runs health check, and logs immutable record."""
    mgr = UpdateManager(db_path=temp_db)

    with patch("orchestrator.update_manager.vm_manager") as mock_vm, \
         patch("orchestrator.update_manager.kali_connector") as mock_kali:
        mock_vm.take_snapshot.return_value = {"snapshot": "pre_update_test_123"}
        mock_vm.rollback_snapshot.return_value = {"status": "restored"}
        mock_kali.execute.return_value = {"exit_code": 0, "stdout": "Updated v2.0", "stderr": ""}

        rec = mgr.apply_update("db_searchsploit", create_snapshot=True)
        assert rec["status"] == "success"
        assert rec["snapshot_name"] is not None
        assert rec["health_check_status"] == "passed"

        # Verify history saved to SQLite
        hist = mgr.list_update_history()
        assert len(hist) >= 1
        assert hist[0]["item_id"] == "db_searchsploit"
        assert hist[0]["status"] == "success"

        # Verify rollback restores snapshot
        rb_res = mgr.rollback_to_snapshot(rec["snapshot_name"])
        assert rb_res["success"] is True
        assert rb_res["snapshot_restored"] == rec["snapshot_name"]


def test_execution_mode_plan_only(temp_db):
    """Verify plan_only execution mode performs tool/arg resolution without calling gateway."""
    plan_id = "test_plan_dry_run"
    plan_dag = PlanDAG(
        plan_id=plan_id,
        session_id="test_sess_dry",
        goal="Scan network 192.168.1.0/24 for web ports",
        nodes=[
            PlanNode(
                node_id="n1",
                capability="network_port_scan",
                label="Network Port Scan",
                dependencies=[],
                status="queued",
            ),
            PlanNode(
                node_id="n2",
                capability="web_directory_enumeration",
                label="Web Route Discovery",
                dependencies=["n1"],
                status="queued",
            ),
        ],
    )
    insert_plan(plan_dag, db_path=temp_db)

    res = dag_controller.execute_plan(
        plan_id=plan_id,
        session_id="test_sess_dry",
        target="192.168.1.50",
        goal="Scan network 192.168.1.0/24 for web ports",
        mode="plan_only",
        db_path=temp_db,
    )

    assert res.status == "planned"
    assert res.completed_count == 0
    assert len(res.nodes_executed) == 2
    for node in res.nodes_executed:
        assert node.status == "planned"
        assert node.command_line
        assert "Dry-run plan validation only" in node.skipped_reason


def test_execution_mode_step_by_step(temp_db):
    """Verify step_by_step execution mode executes single ready step then pauses."""
    plan_id = "test_plan_step"
    plan_dag = PlanDAG(
        plan_id=plan_id,
        session_id="test_sess_step",
        goal="Scan target 192.168.1.50",
        nodes=[
            PlanNode(
                node_id="step1",
                capability="network_port_scan",
                label="Initial Port Sweep",
                dependencies=[],
                status="queued",
            ),
            PlanNode(
                node_id="step2",
                capability="service_fingerprint",
                label="Service Version Probing",
                dependencies=["step1"],
                status="queued",
            ),
        ],
    )
    insert_plan(plan_dag, db_path=temp_db)

    with patch.object(dag_controller, "execute_node") as mock_exec_node:
        from orchestrator.dag_controller import DAGNodeExecution
        mock_exec_node.return_value = DAGNodeExecution(
            node_id="step1",
            capability="network_port_scan",
            label="Initial Port Sweep",
            status="success",
            duration_ms=120.0,
        )

        res = dag_controller.execute_plan(
            plan_id=plan_id,
            session_id="test_sess_step",
            target="192.168.1.50",
            goal="Scan target 192.168.1.50",
            mode="step_by_step",
            db_path=temp_db,
        )

        # Executed exactly 1 node
        assert len(res.nodes_executed) == 1
        assert res.nodes_executed[0].node_id == "step1"
        assert res.status == "step_completed"


def test_api_knowledge_and_update_endpoints(test_client):
    """Verify FastAPI routes for knowledge center and update manager."""
    # 1. Knowledge center tool list
    resp = test_client.get("/knowledge/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert data["total_count"] > 0

    # 2. Knowledge center tool details
    resp = test_client.get("/knowledge/tools/nmap.scan.v1")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["tool_id"] == "nmap.scan.v1"
    assert "natural_language_examples" in detail

    # 3. Knowledge center verify tool
    resp = test_client.post("/knowledge/tools/nmap.scan.v1/verify")
    assert resp.status_code == 200
    v_data = resp.json()
    assert v_data["tool_id"] == "nmap.scan.v1"
    assert "health_status" in v_data

    # 4. Updates status
    resp = test_client.get("/updates/status")
    assert resp.status_code == 200
    s_data = resp.json()
    assert "policy" in s_data
    assert "available_updates" in s_data

    # 5. Updates check
    resp = test_client.post("/updates/check")
    assert resp.status_code == 200
    c_data = resp.json()
    assert "updates" in c_data

    # 6. Updates policy
    resp = test_client.post("/updates/policy", json={"policy": "manual_control"})
    assert resp.status_code == 200
    assert resp.json()["policy"] == "manual_control"
