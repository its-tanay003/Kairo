"""
Regression Test Suite: Permanent Removal of Tool Authorization Tiers (ADR-004)
Ensures future development does not reintroduce the legacy Tier 1/2/3 execution model.
"""

import pytest
from pathlib import Path
import tempfile

from events.db import (
    TOOL_TIER_MAPPING,
    create_scope_contract,
    get_active_scope_contract,
    get_tool_tier,
    init_db,
    validate_scope_request,
)
from orchestrator.execution_gateway import ExecutionGateway


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_tier_regression.db"
        init_db(db_path)
        yield db_path


def test_no_tools_classified_into_tiers():
    """Verify that get_tool_tier returns None for all canonical and arbitrary tools."""
    sample_tools = [
        "whois.lookup.v1",
        "dig.lookup.v1",
        "searchsploit.search.v1",
        "nmap.scan.v1",
        "gobuster.dir.v1",
        "ffuf.fuzz.v1",
        "nikto.scan.v1",
        "sqlmap.scan.v1",
        "hydra.brute.v1",
        "metasploit.rpc.v1",
        "kali.exec.v1",
        "shell.run.v1",
        "burpsuite.gui.v1",
        "wireshark.gui.v1",
        "zap.gui.v1",
        "browser.security.v1",
        "custom_exploit_tool.v1",
    ]
    for tid in sample_tools:
        assert get_tool_tier(tid) is None, f"Tool '{tid}' must not have a tier classification"


def test_scope_contract_creation_without_tiers(temp_db):
    """Verify ScopeContract can be created and activated with zero tier configuration."""
    contract = create_scope_contract(
        targets=["192.168.1.0/24", "target.local"],
        network_scope="authorized_lab",
        time_window="8h",
        authorized_by="secops_admin@kairo.test",
        db_path=temp_db,
    )
    assert contract["signature_valid"] is True
    assert "allowed_tool_tiers" not in contract or contract["allowed_tool_tiers"] is None

    active = get_active_scope_contract(temp_db)
    assert active is not None
    assert active["contract_id"] == contract["contract_id"]
    assert active["signature_valid"] is True


def test_former_tier3_tools_authorized_without_tier_prompt(temp_db):
    """Verify former Tier 3 intrusive tools execute without tool tier exceeded errors."""
    create_scope_contract(
        targets=["192.168.1.50", "target.local"],
        network_scope="authorized_lab",
        time_window="8h",
        authorized_by="secops_admin@kairo.test",
        db_path=temp_db,
    )

    # Intrusive tools that previously required Tier 3
    intrusive_tools = [
        ("sqlmap.scan.v1", "192.168.1.50"),
        ("hydra.brute.v1", "192.168.1.50"),
        ("nmap.scan.v1", "192.168.1.50"),
        ("burpsuite.gui.v1", "target.local"),
        ("browser.security.v1", "target.local"),
    ]

    for tool_id, target in intrusive_tools:
        res = validate_scope_request(target=target, tool_id=tool_id, db_path=temp_db)
        assert res["authorized"] is True, f"Tool {tool_id} should be authorized for target {target}"
        assert "TOOL_TIER_EXCEEDED" not in res.get("reason", "")


def test_out_of_scope_target_remains_blocked(temp_db):
    """Ensure removing tiers does NOT relax target scope boundary enforcement."""
    create_scope_contract(
        targets=["192.168.1.0/24"],
        network_scope="authorized_lab",
        time_window="8h",
        authorized_by="secops_admin@kairo.test",
        db_path=temp_db,
    )

    res = validate_scope_request(
        target="10.0.0.99",
        tool_id="nmap.scan.v1",
        db_path=temp_db,
    )
    assert res["authorized"] is False
    assert "OUT_OF_SCOPE_TARGET" in res["reason"]


def test_gateway_executes_intrusive_tool_in_scope_without_tier_rejection(temp_db):
    """Verify ExecutionGateway dispatches active tools targeting in-scope assets without tier rejection."""
    create_scope_contract(
        targets=["127.0.0.1"],
        network_scope="authorized_lab",
        time_window="1h",
        authorized_by="admin@kairo.test",
        db_path=temp_db,
    )
    gw = ExecutionGateway(db_path=temp_db)
    res = gw.execute(
        tool_id="nmap.scan.v1",
        arguments={"target": "127.0.0.1", "scan_type": "sS"},
        session_id="test_sess_regression",
        task_id="task_reg_01",
        db_path=temp_db,
    )
    assert res.authorized is True
    assert res.rejection_reason is None or "TOOL_TIER" not in res.rejection_reason

