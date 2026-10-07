"""
Comprehensive Integration Tests for Shared Projects (Multi-User Collaboration)
and Audit Explorer (Searchable Timeline & Scope Contract History Correlation).
"""

import json
import os
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from events.db import (
    Event,
    init_db,
    insert_event,
    create_scope_contract,
    create_project,
    get_project,
    list_projects,
    update_project,
    update_project_shared_state,
    add_project_collaborator,
    remove_project_collaborator,
    seed_default_shared_project,
    query_audit_timeline,
    get_audit_stats,
    generate_scope_signature,
    verify_scope_signature,
    get_tool_tier,
    is_target_in_scope,
)
from orchestrator.server import app


@pytest.fixture
def test_db_path(tmp_path):
    """Provides a fresh isolated SQLite database for each test run."""
    db_file = tmp_path / "test_events.db"
    init_db(db_file)
    return db_file


@pytest.fixture
def client():
    """FastAPI TestClient for Orchestrator server routes."""
    return TestClient(app)


# ==============================================================================
# 1. SHARED PROJECTS (Multi-User, Same Project State) TESTS
# ==============================================================================

def test_project_crud_lifecycle(test_db_path):
    """Tests creating, fetching, updating, and listing shared projects."""
    # 1. Create project
    proj = create_project(
        name="Red Team Lab Alpha",
        owner_id="alice_secops",
        description="Multi-user assessment on authorized target range.",
        initial_state={
            "active_target": "192.168.1.10",
            "notes": "Initial pentest scope verified.",
            "tags": ["pentest", "internal"],
            "live_scratchpad": "# Field Notes\nTarget mapped.\n",
        },
        db_path=test_db_path,
    )
    assert proj["project_id"].startswith("proj_")
    assert proj["name"] == "Red Team Lab Alpha"
    assert proj["owner_id"] == "alice_secops"
    assert len(proj["collaborators"]) == 1
    assert proj["collaborators"][0]["user_id"] == "alice_secops"
    assert proj["collaborators"][0]["role"] == "owner"
    assert proj["shared_state"]["active_target"] == "192.168.1.10"

    # 2. Get project
    fetched = get_project(proj["project_id"], db_path=test_db_path)
    assert fetched is not None
    assert fetched["name"] == proj["name"]

    # 3. Update top-level metadata
    updated = update_project(
        project_id=proj["project_id"],
        name="Red Team Lab Alpha (Phase 2)",
        status="active",
        active_workspace_id="ws_redteam_01",
        db_path=test_db_path,
    )
    assert updated["name"] == "Red Team Lab Alpha (Phase 2)"
    assert updated["active_workspace_id"] == "ws_redteam_01"

    # 4. List projects
    projs = list_projects(limit=10, db_path=test_db_path)
    assert len(projs) >= 1
    assert projs[0]["project_id"] == proj["project_id"]


def test_project_shared_state_synchronization(test_db_path):
    """Tests multi-user state synchronization (scratchpad, target, notes)."""
    proj = create_project(
        name="Team Ops",
        owner_id="alice_secops",
        initial_state={"active_target": "target.local", "live_scratchpad": "Init"},
        db_path=test_db_path,
    )
    pid = proj["project_id"]

    # User 1 updates target
    synced1 = update_project_shared_state(
        project_id=pid,
        state_patch={"active_target": "api.target.local", "last_editor": "alice_secops"},
        db_path=test_db_path,
    )
    assert synced1["shared_state"]["active_target"] == "api.target.local"
    assert synced1["shared_state"]["live_scratchpad"] == "Init"

    # User 2 (Bob) updates live scratchpad simultaneously
    synced2 = update_project_shared_state(
        project_id=pid,
        state_patch={"live_scratchpad": "Init\n- Found open port 8080 (bob)", "last_editor": "bob_redteam"},
        db_path=test_db_path,
    )
    assert synced2["shared_state"]["active_target"] == "api.target.local"
    assert "- Found open port 8080 (bob)" in synced2["shared_state"]["live_scratchpad"]
    assert synced2["shared_state"]["last_editor"] == "bob_redteam"


def test_project_collaborator_management(test_db_path):
    """Tests adding and removing collaborators with roles."""
    proj = create_project(
        name="Collab Test",
        owner_id="alice_secops",
        db_path=test_db_path,
    )
    pid = proj["project_id"]

    # Add Bob as editor
    with_bob = add_project_collaborator(
        project_id=pid,
        user_id="bob_redteam",
        role="editor",
        client_type="linux-desktop",
        db_path=test_db_path,
    )
    assert len(with_bob["collaborators"]) == 2
    bob_collab = next(c for c in with_bob["collaborators"] if c["user_id"] == "bob_redteam")
    assert bob_collab["role"] == "editor"
    assert bob_collab["client_type"] == "linux-desktop"

    # Add Charlie as viewer
    with_charlie = add_project_collaborator(
        project_id=pid,
        user_id="charlie_auditor",
        role="viewer",
        client_type="browser-mobile",
        db_path=test_db_path,
    )
    assert len(with_charlie["collaborators"]) == 3

    # Remove Charlie
    without_charlie = remove_project_collaborator(
        project_id=pid,
        user_id="charlie_auditor",
        db_path=test_db_path,
    )
    assert len(without_charlie["collaborators"]) == 2
    assert not any(c["user_id"] == "charlie_auditor" for c in without_charlie["collaborators"])

    # Cannot remove project owner (Alice)
    attempt_owner_remove = remove_project_collaborator(
        project_id=pid,
        user_id="alice_secops",
        db_path=test_db_path,
    )
    assert any(c["user_id"] == "alice_secops" for c in attempt_owner_remove["collaborators"])


def test_seed_default_shared_project(test_db_path):
    """Tests canonical default shared project auto-seeding."""
    seeded = seed_default_shared_project(db_path=test_db_path)
    assert seeded is not None
    assert "Global Operations Center" in seeded["name"]
    assert seeded["owner_id"] == "alice_secops"

    # Calling again returns same project
    seeded2 = seed_default_shared_project(db_path=test_db_path)
    assert seeded2["project_id"] == seeded["project_id"]


# ==============================================================================
# 2. AUDIT EXPLORER & SCOPE CONTRACT ACCOUNTABILITY TESTS (Task 2.3)
# ==============================================================================

def test_scope_contract_history_correlation_and_verification(test_db_path):
    """
    Tests that Audit Explorer queries events, identifies governing Scope Contracts,
    cryptographically validates signatures, and tags scope compliance vs violation.
    """
    now = datetime.now(timezone.utc)
    t0 = (now - timedelta(hours=2)).isoformat()
    t1 = (now - timedelta(hours=1, minutes=30)).isoformat()
    t2 = (now - timedelta(hours=1)).isoformat()
    t3 = (now - timedelta(minutes=30)).isoformat()

    # 1. Create and activate Scope Contract 1 at t0
    # Targets: 192.168.1.0/24 and target.local; Tiers allowed: 1 and 2
    sc1 = create_scope_contract(
        targets=["192.168.1.0/24", "target.local"],
        network_scope="Authorized Lab CIDR",
        time_window="8h",
        allowed_tool_tiers=[1, 2],
        authorized_by="alice_secops",
        db_path=test_db_path,
    )
    assert sc1["signature_valid"] is True

    # 2. Event A at t1: Agent runs nmap on in-scope target 192.168.1.15 (Tier 2 probe)
    # -> Should be tagged IN SCOPE
    ev_a = Event.create(
        session_id="sess_alpha",
        task_id="task_recon_01",
        actor="agent",
        tool_id="nmap_audit_v1",
        tool_version="1.0.0",
        requested_args={"target": "192.168.1.15", "ports": "80,443"},
        normalized_args={"target": "192.168.1.15", "ports": "80,443"},
        process_id=101,
        exit_code=0,
        result_summary="Discovered 80/tcp open on 192.168.1.15",
        timestamp=t1,
    )
    insert_event(ev_a, db_path=test_db_path)

    # 3. Event B at t2: Agent runs tool on out-of-boundary target 10.0.0.99 (Target Violation)
    # -> Should be tagged SCOPE VIOLATION
    ev_b = Event.create(
        session_id="sess_alpha",
        task_id="task_probe_out_of_bounds",
        actor="agent",
        tool_id="shell.run.v1",
        tool_version="1.0.0",
        requested_args={"command": "curl", "args": ["http://10.0.0.99/admin"]},
        normalized_args={"command": "curl", "args": ["http://10.0.0.99/admin"]},
        process_id=102,
        exit_code=1,
        result_summary="Probing out of scope asset 10.0.0.99",
        timestamp=t2,
    )
    insert_event(ev_b, db_path=test_db_path)

    # 4. Event C at t3: Agent attempts Tier 3 intrusive exploit when contract only permits Tiers 1-2 (Tier Violation)
    # -> Should be tagged SCOPE VIOLATION
    ev_c = Event.create(
        session_id="sess_alpha",
        task_id="task_exploit_tier_violation",
        actor="agent",
        tool_id="metasploit.exploit.v1",
        tool_version="1.0.0",
        requested_args={"target": "target.local", "payload": "reverse_tcp"},
        normalized_args={"target": "target.local", "payload": "reverse_tcp"},
        process_id=103,
        exit_code=1,
        result_summary="Attempted Tier 3 exploit execution",
        timestamp=t3,
    )
    insert_event(ev_c, db_path=test_db_path)

    # 5. Query Audit Timeline
    timeline_res = query_audit_timeline(db_path=test_db_path)
    timeline = timeline_res["timeline"]

    # Verify Scope Contract milestone is present in timeline
    milestones = [item for item in timeline if item.get("is_scope_contract_milestone")]
    assert len(milestones) == 1
    assert milestones[0]["contract_id"] == sc1["contract_id"]
    assert milestones[0]["signature_valid"] is True
    assert "192.168.1.0/24" in milestones[0]["targets"]

    # Verify Event A (In Scope)
    event_a_item = next(item for item in timeline if item.get("task_id") == "task_recon_01")
    assert event_a_item["scope_status"] == "in_scope"
    assert event_a_item["target_in_scope"] is True
    assert event_a_item["governing_contract_id"] == sc1["contract_id"]

    # Verify Event B (Target Violation)
    event_b_item = next(item for item in timeline if item.get("task_id") == "task_probe_out_of_bounds")
    assert event_b_item["scope_status"] == "scope_violation"
    assert event_b_item["target_in_scope"] is False
    assert "Target '10.0.0.99' outside authorized boundaries" in event_b_item["scope_violation_reason"]

    # Verify Event C (Tier Violation)
    event_c_item = next(item for item in timeline if item.get("task_id") == "task_exploit_tier_violation")
    assert event_c_item["scope_status"] == "scope_violation"
    assert "Tool tier 3 exceeds authorized contract tiers" in event_c_item["scope_violation_reason"]

    # Verify overall stats
    stats = timeline_res["stats"]
    assert stats["in_scope_actions"] == 1
    assert stats["scope_violations"] == 2
    assert stats["active_contracts"] == 1


def test_audit_timeline_filters(test_db_path):
    """Tests timeline filtering by actor, tool_id, exit status, and query string."""
    now = datetime.now(timezone.utc).isoformat()

    insert_event(
        Event.create(session_id="s1", task_id="t1", actor="agent", tool_id="nmap_audit_v1", exit_code=0, result_summary="Nmap port scan finished", timestamp=now),
        db_path=test_db_path,
    )
    insert_event(
        Event.create(session_id="s1", task_id="t2", actor="supervisor", tool_id="process.kill.v1", exit_code=0, result_summary="Killed runaway process", timestamp=now),
        db_path=test_db_path,
    )
    insert_event(
        Event.create(session_id="s1", task_id="t3", actor="user", tool_id="shell.run.v1", exit_code=1, result_summary="Command returned non-zero error", timestamp=now),
        db_path=test_db_path,
    )

    # Filter by Actor
    res_agent = query_audit_timeline(actor="agent", db_path=test_db_path)
    matched_events = [e for e in res_agent["timeline"] if not e.get("is_scope_contract_milestone")]
    assert len(matched_events) == 1
    assert matched_events[0]["actor"] == "agent"

    # Filter by Tool
    res_tool = query_audit_timeline(tool_id="process.kill.v1", db_path=test_db_path)
    matched_tool = [e for e in res_tool["timeline"] if not e.get("is_scope_contract_milestone")]
    assert len(matched_tool) == 1
    assert matched_tool[0]["tool_id"] == "process.kill.v1"

    # Filter by Status (Failure)
    res_fail = query_audit_timeline(status="failure", db_path=test_db_path)
    matched_fail = [e for e in res_fail["timeline"] if not e.get("is_scope_contract_milestone")]
    assert len(matched_fail) == 1
    assert matched_fail[0]["exit_code"] == 1

    # Filter by Free-text Query
    res_query = query_audit_timeline(query="runaway", db_path=test_db_path)
    matched_query = [e for e in res_query["timeline"] if not e.get("is_scope_contract_milestone")]
    assert len(matched_query) == 1
    assert "runaway" in matched_query[0]["result_summary"]


def test_audit_stats_endpoint(test_db_path):
    """Tests high-level summary statistics calculation for Audit Explorer."""
    insert_event(Event.create(session_id="s1", task_id="t1", actor="agent", tool_id="nmap_audit_v1", exit_code=0), db_path=test_db_path)
    insert_event(Event.create(session_id="s1", task_id="t2", actor="agent", tool_id="wpscan_audit_v1", exit_code=0), db_path=test_db_path)
    insert_event(Event.create(session_id="s1", task_id="t3", actor="user", tool_id="shell.run.v1", exit_code=1), db_path=test_db_path)

    stats = get_audit_stats(db_path=test_db_path)
    assert stats["total_events"] == 3
    assert stats["successful_executions"] == 2
    assert stats["failed_executions"] == 1
    assert stats["actors"]["agent"] == 2
    assert stats["actors"]["user"] == 1
    assert stats["top_tools"]["nmap_audit_v1"] == 1


# ==============================================================================
# 3. HTTP API SERVER INTEGRATION TESTS
# ==============================================================================

def test_api_projects_endpoints(client):
    """Tests FastAPI /projects endpoints end-to-end."""
    # 1. GET /projects (auto-seeds canonical workspace)
    resp = client.get("/projects")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["projects"]) >= 1

    # 2. POST /projects (create new)
    create_resp = client.post(
        "/projects",
        json={
            "name": "Project Omega Operations",
            "owner_id": "alice_secops",
            "description": "Multi-agent assessment operations center",
            "initial_state": {"active_target": "target.local", "notes": "Scope validated."},
        },
    )
    assert create_resp.status_code == 200
    proj_id = create_resp.json()["project"]["project_id"]

    # 3. GET /projects/{id}
    get_resp = client.get(f"/projects/{proj_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["project"]["name"] == "Project Omega Operations"

    # 4. PUT /projects/{id}/state (shared state update)
    state_resp = client.put(
        f"/projects/{proj_id}/state",
        json={
            "user_id": "bob_redteam",
            "state_updates": {
                "active_target": "192.168.1.50",
                "live_scratchpad": "# Team Notes\nRecon finished on 192.168.1.50\n",
            },
        },
    )
    assert state_resp.status_code == 200
    assert state_resp.json()["project"]["shared_state"]["active_target"] == "192.168.1.50"

    # 5. POST /projects/{id}/presence (heartbeat)
    hb_resp = client.post(
        f"/projects/{proj_id}/presence",
        json={
            "user_id": "bob_redteam",
            "client_type": "linux-desktop",
            "role": "editor",
            "active_view": "live_session",
        },
    )
    assert hb_resp.status_code == 200
    assert hb_resp.json()["count"] >= 1
    assert any(c["user_id"] == "bob_redteam" for c in hb_resp.json()["collaborators_online"])


def test_api_audit_timeline_endpoints(client):
    """Tests FastAPI /audit/timeline and /audit/stats endpoints."""
    # GET /audit/timeline
    tl_resp = client.get("/audit/timeline?limit=20")
    assert tl_resp.status_code == 200
    tl_data = tl_resp.json()
    assert "timeline" in tl_data
    assert "stats" in tl_data

    # GET /audit/stats
    stats_resp = client.get("/audit/stats")
    assert stats_resp.status_code == 200
    stats_data = stats_resp.json()
    assert "total_events" in stats_data
    assert "success_rate_pct" in stats_data
