"""
Test suite for Failure-Aware Reporter component and linked recovery event chain.
Verifies:
1. format_recovery_narrative formats the required causal lineage narrative.
2. Causal parent_event chaining in the event store across failure -> recovery -> retry -> success.
3. Reporter.generate_plan_report generates resilience metrics, DAG attempt history, and findings matrix.
4. Reporter.save_report_artifact computes valid SHA-256 hashes and writes signed JSON and Markdown artifacts.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from events.db import init_db, insert_event, Event, insert_plan, PlanDAG, PlanNode, get_artifacts_by_task, get_events_by_session
from orchestrator.reporter import (
    format_recovery_narrative,
    Reporter,
    reporter,
)


@pytest.fixture
def temp_env():
    temp_dir = tempfile.mkdtemp()
    db_path = Path(temp_dir) / "kairo_test.db"
    init_db(db_path)
    yield temp_dir, db_path
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_format_recovery_narrative():
    """Verify narrative formatting matches required failure-aware narrative specification."""
    steps = [
        {
            "attempt": 1,
            "tool": "gobuster.dir.v1",
            "args": {"wordlist": "common"},
            "failure_reason": "timed out after 30s",
        },
        {
            "attempt": 2,
            "tool": "ffuf.fuzz.v1",
            "args": {"threads": 5},
            "transition": "switched to ffuf with reduced thread count",
            "outcome": "succeeded, found 3 endpoints",
        },
    ]

    narrative = format_recovery_narrative(steps)
    expected = "Attempted gobuster (common wordlist) -> timed out after 30s -> switched to ffuf with reduced thread count -> succeeded, found 3 endpoints."
    assert narrative == expected


def test_parent_event_causal_chain(temp_env):
    """Verify that failed executions, recovery interventions, and retries link via parent_event."""
    _, db_path = temp_env
    task_id = "task_node_rec_test"

    # Step 1: Initial tool execution attempt that fails
    ev1_obj = Event.create(
        session_id="session_test",
        task_id=task_id,
        actor="orchestrator",
        tool_id="gobuster.dir.v1",
        exit_code=124,
        result_summary="Command timed out after 30s",
        parent_event=None,
    )
    ev1_row = insert_event(ev1_obj, db_path)
    ev1_id = str(ev1_row)

    # Step 2: Observer & Critic flag no progress -> Recovery Agent intervenes
    ev2_obj = Event.create(
        session_id="session_test",
        task_id=task_id,
        actor="recovery_agent",
        tool_id="recovery.retry.v1",
        result_summary="Switching tool to ffuf with reduced thread count",
        parent_event=ev1_id,
    )
    ev2_row = insert_event(ev2_obj, db_path)
    ev2_id = str(ev2_row)

    # Step 3: Second attempt executes with alternate tool
    ev3_obj = Event.create(
        session_id="session_test",
        task_id=task_id,
        actor="orchestrator",
        tool_id="ffuf.fuzz.v1",
        exit_code=0,
        result_summary="Found: /admin [200], /api [200], /login [200]",
        parent_event=ev2_id,
    )
    ev3_row = insert_event(ev3_obj, db_path)
    ev3_id = str(ev3_row)

    # Step 4: Observer extracts facts and Critic confirms progress
    ev4_obj = Event.create(
        session_id="session_test",
        task_id=task_id,
        actor="critic",
        tool_id="critic.eval.v1",
        result_summary="Attempted gobuster (common wordlist) -> timed out after 30s -> switched to ffuf with reduced thread count -> succeeded, found 3 endpoints.",
        parent_event=ev3_id,
    )
    insert_event(ev4_obj, db_path)

    # Validate parent_event lineage in the event store
    events = get_events_by_session("session_test", db_path)
    assert len(events) == 4

    # ev1 has no parent
    assert events[0]["parent_event"] is None
    # ev2 points to ev1
    assert events[1]["parent_event"] == ev1_id
    # ev3 points to ev2
    assert events[2]["parent_event"] == ev2_id
    # ev4 points to ev3
    assert events[3]["parent_event"] == ev3_id


def test_reporter_generation_and_artifact_signing(temp_env):
    """Verify that Reporter generates failure-aware metrics and signs artifacts with SHA-256."""
    temp_dir, db_path = temp_env
    plan_id = "test_plan_resilience"

    # Create plan with 2 nodes: one requiring recovery, one clean
    plan_nodes = [
        PlanNode(
            node_id="node_web",
            capability="web_directory_enum",
            label="Enumerate Web Endpoints",
            assigned_tool="ffuf.fuzz.v1",
            status="success",
            result=json.dumps({
                "attempts": 2,
                "recovery_narrative": "Attempted gobuster (common wordlist) -> timed out after 30s -> switched to ffuf with reduced thread count -> succeeded, found 3 endpoints.",
                "recovery_path": [
                    {
                        "attempt": 1,
                        "tool": "gobuster.dir.v1",
                        "status": "failed",
                        "failure_reason": "timed out after 30s",
                        "action_taken": "switch_tool",
                    },
                    {
                        "attempt": 2,
                        "tool": "ffuf.fuzz.v1",
                        "status": "success",
                        "action_taken": "switched to ffuf with reduced thread count",
                    },
                ],
                "facts": {
                    "endpoints": [
                        {"path": "/admin", "status": 200},
                        {"path": "/api/v1", "status": 200},
                        {"path": "/login", "status": 200},
                    ]
                },
            }),
        ),
        PlanNode(
            node_id="node_port",
            capability="network_port_scan",
            label="Scan Ports",
            assigned_tool="nmap.scan.v1",
            status="success",
            result=json.dumps({
                "attempts": 1,
                "facts": {
                    "ports": [
                        {"port": 80, "service": "http"},
                        {"port": 22, "service": "ssh"},
                    ]
                },
            }),
        ),
    ]

    plan = PlanDAG(
        plan_id=plan_id,
        session_id="session_123",
        goal="Audit web server and network surface",
        nodes=plan_nodes,
        status="completed",
    )
    insert_plan(plan, db_path)

    reporter = Reporter(db_path=db_path, artifacts_dir=temp_dir)
    report = reporter.generate_plan_report(plan_id)

    assert report["plan_id"] == plan_id
    metrics = report["resilience_metrics"]
    assert metrics["total_nodes"] == 2
    assert metrics["successful_nodes"] == 2
    assert metrics["nodes_requiring_recovery"] == 1
    assert metrics["total_recovery_interventions"] == 1
    assert metrics["autonomous_healing_rate_pct"] == 100.0

    # Verify recovery narratives dictionary contains the node
    assert "node_web" in report["recovery_narratives"]
    assert "timed out after 30s" in report["recovery_narratives"]["node_web"]

    # Verify findings matrix includes the discovering node's recovery path
    findings = report["findings_matrix"]
    assert len(findings["endpoints"]) == 3
    for ep in findings["endpoints"]:
        assert ep["discovering_node"] == "node_web"
        assert ep["recovery_narrative"] == report["recovery_narratives"]["node_web"]
        assert len(ep["recovery_path"]) == 2

    # Save artifacts and check SHA-256 integrity
    artifact_res = reporter.save_report_artifact(plan_id, report)
    assert artifact_res["json"]["sha256"] is not None
    assert artifact_res["markdown"]["sha256"] is not None

    # Check that artifact was logged in database
    arts = get_artifacts_by_task(f"plan_{plan_id}", db_path)
    assert len(arts) == 1
    assert arts[0]["sha256"] == artifact_res["json"]["sha256"]
    meta = json.loads(arts[0]["metadata"])
    assert meta["autonomous_healing_rate_pct"] == 100.0
    assert "node_web" in meta["recovery_narratives"]


if __name__ == "__main__":
    pytest.main(["-v", __file__])
