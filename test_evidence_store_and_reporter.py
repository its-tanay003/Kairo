"""
Unit and Integration Tests for Kairo Evidence Store and Report Generator.

Tests:
1. Six Blueprint Artifact Classes (command, network, file, visual, analytic, report)
2. Finding Cards with title, affected asset, evidence references, confidence score, and recovery path
3. Resolving evidence references via SHA-256 cryptographic hashes
4. Report Generator: Assembling selected findings into Markdown/HTML reports with embedded evidence
5. Reproducible Workflow generation: ToolSpec sequence, normalized args, and replay script
"""

import json
import os
import tempfile
from pathlib import Path
import pytest

from events.db import init_db, get_connection
from orchestrator.evidence_store import (
    EvidenceStore,
    EvidenceClass,
    Finding,
    CommandEvidence,
    NetworkEvidence,
    FileEvidence,
    VisualEvidence,
    AnalyticEvidence,
    ReportEvidence,
)
from orchestrator.report_generator import ReportGenerator


@pytest.fixture
def temp_evidence_env():
    """Provides an isolated SQLite database and artifacts directory."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "kairo_evidence_test.db"
        artifacts_dir = Path(tmp_dir) / "evidence_artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        init_db(db_path)
        yield str(tmp_dir), db_path, artifacts_dir


def test_six_artifact_classes_persistence(temp_evidence_env):
    """Verify storing all 6 blueprint artifact classes with SHA-256 hashes."""
    _, db_path, art_dir = temp_evidence_env
    store = EvidenceStore(db_path=db_path, artifacts_dir=art_dir)

    task_id = "test_task_recon"

    # 1. Command Evidence
    cmd_ev = store.store_command_evidence(
        task_id=task_id,
        command_line="nmap -sV -p 80,443 127.0.0.1",
        stdout="PORT 80/tcp OPEN http\nPORT 443/tcp OPEN https",
        exit_code=0,
        duration_ms=1250.5,
    )
    assert cmd_ev.evidence_class == EvidenceClass.COMMAND
    assert len(cmd_ev.sha256) == 64
    assert Path(cmd_ev.filepath).exists()

    # 2. Network Evidence
    net_ev = store.store_network_evidence(
        task_id=task_id,
        host="127.0.0.1",
        port=80,
        protocol="tcp",
        service="http",
        banner="Apache/2.4.52",
        http_method="GET",
        http_url="http://127.0.0.1/",
        http_status=200,
        http_headers={"Server": "Apache/2.4.52"},
        http_body_preview="<html><title>Dashboard</title></html>",
    )
    assert net_ev.evidence_class == EvidenceClass.NETWORK
    assert net_ev.port == 80
    assert net_ev.sha256 != ""

    # 3. File Evidence
    dummy_file = art_dir / "target_discovery.txt"
    dummy_file.write_text("/admin\n/login\n/api/v1", encoding="utf-8")
    file_ev = store.store_file_evidence(
        task_id=task_id,
        target_filepath=str(dummy_file),
        content_snippet="/admin\n/login\n/api/v1",
    )
    assert file_ev.evidence_class == EvidenceClass.FILE
    assert file_ev.target_filename == "target_discovery.txt"

    # 4. Visual Evidence
    vis_ev = store.store_visual_evidence(
        task_id=task_id,
        caption="Web Application Admin Login Page Screenshot",
        dom_snapshot="<form id='login-form'><input type='password'/></form>",
    )
    assert vis_ev.evidence_class == EvidenceClass.VISUAL
    assert vis_ev.dom_snapshot is not None

    # 5. Analytic Evidence
    ana_ev = store.store_analytic_evidence(
        task_id=task_id,
        analytic_type="vulnerability_deduction",
        facts={"cve": "CVE-2023-12345", "severity": "HIGH", "score": 8.5},
        confidence=0.95,
        critique_verdict="Confirmed SQL injection path",
    )
    assert ana_ev.evidence_class == EvidenceClass.ANALYTIC
    assert ana_ev.confidence == 0.95

    # 6. Report Evidence
    rep_ev = ReportEvidence(
        evidence_id="rep_summary_001",
        title="Summary Engagement Evidence",
        task_id=task_id,
        format_type="markdown",
        included_findings=["find_001"],
    )
    store.store_evidence(rep_ev)
    assert rep_ev.evidence_class == EvidenceClass.REPORT
    assert rep_ev.sha256 != ""

    # Check that all artifacts were registered in SQLite
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM artifacts WHERE task_id = ?", (task_id,))
        count = cursor.fetchone()[0]
    conn.close()
    assert count == 6


def test_finding_cards_with_recovery_path(temp_evidence_env):
    """Verify Finding card data model with recovery path and evidence references."""
    _, db_path, art_dir = temp_evidence_env
    store = EvidenceStore(db_path=db_path, artifacts_dir=art_dir)

    # Create network evidence
    net_ev = store.store_network_evidence(
        task_id="task_fuzz",
        host="staging.corp.internal",
        port=8080,
        http_method="GET",
        http_url="http://staging.corp.internal:8080/admin",
        http_status=200,
    )

    # Finding with Task 2.5 failure-aware recovery lineage
    recovery_narrative = (
        "Attempted gobuster (common wordlist) -> timed out after 30s -> "
        "switched to ffuf with reduced thread count -> succeeded, found 3 endpoints."
    )
    finding = Finding(
        id="find_admin_panel",
        title="Exposed Admin Console at /admin",
        affected_asset="http://staging.corp.internal:8080/admin",
        evidence_references=[f"sha256:{net_ev.sha256}"],
        confidence_score=0.96,
        recovery_path=recovery_narrative,
        severity="HIGH",
        description="Publicly accessible administrative interface discovered without mutual TLS authentication.",
        remediation="Enforce IP whitelisting or move endpoint behind corporate SSO.",
        discovering_tool="ffuf.fuzz.v1",
        session_id="sess_alpha",
        plan_id="plan_omega",
    )

    store.store_finding(finding)

    # Retrieve and verify finding
    retrieved = store.get_finding("find_admin_panel")
    assert retrieved is not None
    assert retrieved.title == "Exposed Admin Console at /admin"
    assert retrieved.affected_asset == "http://staging.corp.internal:8080/admin"
    assert retrieved.confidence_score == 0.96
    assert retrieved.recovery_path == recovery_narrative
    assert retrieved.severity == "HIGH"
    assert len(retrieved.evidence_references) == 1
    assert net_ev.sha256 in retrieved.evidence_references[0]

    # Resolve evidence references
    resolved = store.resolve_evidence_references(retrieved.evidence_references)
    assert len(resolved) == 1
    assert resolved[0]["sha256"] == net_ev.sha256
    assert resolved[0]["filename"] == net_ev.filename


def test_report_generator_with_selected_findings_and_reproducible_workflow(temp_evidence_env):
    """Verify ReportGenerator assembles selected findings into Markdown and HTML with reproducible workflow."""
    _, db_path, art_dir = temp_evidence_env
    store = EvidenceStore(db_path=db_path, artifacts_dir=art_dir)
    rep_gen = ReportGenerator(db_path=db_path, artifacts_dir=art_dir, store=store)

    # Store command evidence
    cmd_ev1 = store.store_command_evidence(
        task_id="task_1",
        command_line="nmap -sV -p 80 127.0.0.1",
        stdout="80/tcp open http",
    )
    cmd_ev2 = store.store_command_evidence(
        task_id="task_2",
        command_line="ffuf -u http://127.0.0.1/FUZZ -w wordlist.txt",
        stdout="[200] /admin\n[200] /api",
    )

    # Store 3 findings
    f1 = Finding(
        id="f1",
        title="Open HTTP Port 80",
        affected_asset="127.0.0.1:80",
        evidence_references=[f"sha256:{cmd_ev1.sha256}"],
        confidence_score=0.99,
        recovery_path=None,
        severity="LOW",
        session_id="sess_1",
    )
    f2 = Finding(
        id="f2",
        title="Exposed Management API /api/v1",
        affected_asset="http://127.0.0.1/api/v1",
        evidence_references=[f"sha256:{cmd_ev2.sha256}"],
        confidence_score=0.92,
        recovery_path="Attempted gobuster -> timed out after 30s -> switched to ffuf -> succeeded.",
        severity="HIGH",
        session_id="sess_1",
    )
    f3 = Finding(
        id="f3",
        title="Debug Header Leakage",
        affected_asset="http://127.0.0.1/debug",
        evidence_references=[],
        confidence_score=0.70,
        recovery_path=None,
        severity="INFO",
        session_id="sess_1",
    )

    store.store_finding(f1)
    store.store_finding(f2)
    store.store_finding(f3)

    # 1. Assemble report with ONLY selected findings [f1, f2] (f3 excluded)
    report_res = rep_gen.assemble_report(
        finding_ids=["f1", "f2"],
        session_id="sess_1",
        title="Production Security Audit Report",
        include_workflow=True,
    )

    assert report_res["report_id"] is not None
    assert report_res["findings_count"] == 2
    assert report_res["markdown"] is not None
    assert report_res["html"] is not None

    md = report_res["markdown"]
    html_text = report_res["html"]

    # Verify selected findings present and unselected omitted
    assert "Exposed Management API /api/v1" in md
    assert "Open HTTP Port 80" in md
    assert "Debug Header Leakage" not in md  # Not selected!

    # Verify recovery lineage is rendered (Task 2.5 differentiator)
    assert "Autonomous Recovery Lineage" in md
    assert "Attempted gobuster -> timed out after 30s" in md
    assert "Autonomous Recovery Lineage" in html_text

    # Verify embedded evidence references
    assert cmd_ev1.sha256 in md
    assert cmd_ev2.sha256 in md

    # Verify Reproducible Workflow section & replay script
    assert "Reproducible Workflow" in md
    assert "replay_audit.sh" in md
    assert "#!/usr/bin/env bash" in report_res["replay_script"]

    # Verify files created on disk with SHA-256 provenance
    assert Path(report_res["markdown_path"]).exists()
    assert Path(report_res["html_path"]).exists()
    assert len(report_res["markdown_sha256"]) == 64
    assert len(report_res["html_sha256"]) == 64


def test_auto_ingest_from_node_result(temp_evidence_env):
    """Verify auto_ingest_from_node_result creates findings and evidence from DAG node outputs."""
    _, db_path, art_dir = temp_evidence_env
    store = EvidenceStore(db_path=db_path, artifacts_dir=art_dir)

    result_data = {
        "command_executed": "ffuf -u http://192.168.1.50/FUZZ -w common.txt",
        "raw_stdout": "[Status: 200, Size: 1420] /admin\n[Status: 200, Size: 840] /login",
        "attempts": 2,
        "recovery_narrative": "Attempted gobuster -> timed out after 30s -> switched to ffuf with reduced thread count -> succeeded, found 2 endpoints.",
        "recovery_path": [
            {"attempt": 1, "tool": "gobuster", "status": "failed", "details": "timed out after 30s"},
            {"attempt": 2, "tool": "ffuf", "status": "success", "details": "succeeded, found 2 endpoints"},
        ],
        "facts": {
            "ports": [
                {"port": 80, "service": "http", "host": "192.168.1.50"}
            ],
            "endpoints": [
                {"path": "/admin", "status": 200},
                {"path": "/login", "status": 200},
            ],
            "vulnerabilities": [
                {"type": "SQL Injection", "severity": "HIGH", "confidence": 0.95, "description": "Blind SQLi in login"}
            ]
        }
    }

    findings = store.auto_ingest_from_node_result(
        plan_id="plan_test_ingest",
        node_id="node_fuzz",
        tool="ffuf.fuzz.v1",
        result_data=result_data,
        target_asset="192.168.1.50",
    )

    # 1 port + 2 endpoints + 1 vuln = 4 findings
    assert len(findings) == 4
    for f in findings:
        assert f.recovery_path == result_data["recovery_narrative"]
        assert len(f.evidence_references) >= 1

    # Check that they can be retrieved from DB
    all_f = store.list_findings(plan_id="plan_test_ingest")
    assert len(all_f) == 4
