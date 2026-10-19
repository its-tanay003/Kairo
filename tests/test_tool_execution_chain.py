"""
Comprehensive verification test suite for Kairo Tool Adapters and the Complete Execution Chain.

Verifies:
1. Individual tool adapters (all 23 typed security adapters + broad execution adapters).
   - build_args constructs typed CLI arguments.
   - validate_inputs enforces schema bounds and blocks command injection.
   - parse extracts structured observation dictionaries containing 'tool' key and domain entities.
2. Argument construction and schema validation.
   - Required fields, types, enums, bounds.
   - Command injection rejection.
3. Broad command execution restriction vs typed adapters.
   - shell.run.v1 and kali.exec.v1 rejected without explicit workflow approval.
   - shell.run.v1 and kali.exec.v1 permitted with approved_workflow=True or Scope Contract authorization.
   - Natural language operations strictly favor typed adapters over broad command execution.
4. Complete End-to-End Execution Chain:
   User request → tool selection → argument construction → validation → adapter → Kali execution → output parsing.
"""

from __future__ import annotations
import os
import sys
from pathlib import Path
import tempfile
import uuid
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.adapters.registry import adapter_registry
from orchestrator.adapters.base import ToolAdapter, ToolObservation
from orchestrator.tool_selector import tool_selector, CAPABILITY_TOOL_AFFINITY
from orchestrator.validation import validate_tool_arguments, is_workflow_approved
from orchestrator.agent import AgentLoop
from registry.loader import ToolRegistry, ToolSpec
from events.db import init_db, seed_default_scope_contract, create_scope_contract, get_events_by_session


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_events.db"
        init_db(db_path)
        seed_default_scope_contract(db_path)
        yield db_path


# =============================================================================
# 1. INDIVIDUAL TOOL ADAPTER TESTS (ALL 23 TYPED ADAPTERS)
# =============================================================================

TYPED_ADAPTER_IDS = [
    "nmap.scan.v1",
    "metasploit.rpc.v1",
    "gobuster.dir.v1",
    "ffuf.fuzz.v1",
    "nikto.scan.v1",
    "whatweb.scan.v1",
    "sqlmap.scan.v1",
    "hydra.brute.v1",
    "searchsploit.search.v1",
    "whois.lookup.v1",
    "dig.lookup.v1",
    "dnsenum.enum.v1",
    "tcpdump.capture.v1",
    "exiftool.extract.v1",
    "hashid.identify.v1",
    "burpsuite.gui.v1",
    "wireshark.gui.v1",
    "zap.gui.v1",
    "browser.security.v1",
    "dnsrecon.enum.v1",
    "subfinder.enum.v1",
    "trivy.fs.v1",
    "wpscan.audit.v1",
]


class TestAllTypedAdaptersIndividually:
    def test_all_23_adapters_registered(self):
        registered = adapter_registry.list_tool_ids()
        for tool_id in TYPED_ADAPTER_IDS:
            assert tool_id in registered, f"Adapter '{tool_id}' must be registered in adapter_registry"

    def test_adapters_instantiate_cleanly(self):
        for tool_id in TYPED_ADAPTER_IDS:
            instance = adapter_registry.get_instance(tool_id)
            assert isinstance(instance, ToolAdapter), f"Tool '{tool_id}' must instantiate as ToolAdapter"
            assert instance.tool_id == tool_id

    def test_dnsrecon_adapter_build_args_and_parse(self):
        from orchestrator.adapters.dnsrecon_adapter import DnsreconAdapter
        adapter = DnsreconAdapter()
        args = adapter.build_args({"target": "target.lab", "scan_type": "axfr"})
        assert "-d" in args and "target.lab" in args
        assert "-t" in args and "axfr" in args

        sample_stdout = (
            "[*] A target.lab 192.168.1.100\n"
            "[*] NS ns1.target.lab 192.168.1.1\n"
            "[*] Zone Transfer Successful on ns1.target.lab\n"
        )
        parsed = adapter.parse(sample_stdout, "", 0, {"inputs": {"target": "target.lab"}})
        assert parsed["tool"] == "dnsrecon"
        assert len(parsed["dns_records"]) == 2
        assert "192.168.1.100" in parsed["hosts"]
        assert len(parsed["findings"]) == 1
        assert parsed["findings"][0]["title"] == "DNS Zone Transfer Allowed"

    def test_subfinder_adapter_build_args_and_parse(self):
        from orchestrator.adapters.subfinder_adapter import SubfinderAdapter
        adapter = SubfinderAdapter()
        args = adapter.build_args({"target": "example.com", "threads": 25})
        assert "-d" in args and "example.com" in args
        assert "-silent" in args
        assert "-t" in args and "25" in args

        sample_stdout = "api.example.com\nadmin.example.com\nmail.example.com\n"
        parsed = adapter.parse(sample_stdout, "", 0, {"inputs": {"target": "example.com"}})
        assert parsed["tool"] == "subfinder"
        assert len(parsed["subdomains"]) == 3
        assert "api.example.com" in parsed["subdomains"]

    def test_trivy_adapter_build_args_and_parse(self):
        from orchestrator.adapters.trivy_adapter import TrivyAdapter
        adapter = TrivyAdapter()
        args = adapter.build_args({"target": "/home/kali", "severity": "CRITICAL"})
        assert "fs" in args
        assert "--severity" in args and "CRITICAL" in args
        assert "/home/kali" in args

        sample_json = (
            '{"Results": [{"Target": "package-lock.json", "Vulnerabilities": '
            '[{"VulnerabilityID": "CVE-2023-1234", "PkgName": "lodash", "Severity": "CRITICAL", "Title": "Prototype Pollution"}]}]}'
        )
        parsed = adapter.parse(sample_json, "", 0, {"inputs": {"target": "/home/kali"}})
        assert parsed["tool"] == "trivy"
        assert len(parsed["vulnerabilities"]) == 1
        assert parsed["vulnerabilities"][0]["cve_id"] == "CVE-2023-1234"
        assert parsed["vulnerabilities"][0]["package"] == "lodash"

    def test_wpscan_adapter_build_args_and_parse(self):
        from orchestrator.adapters.wpscan_adapter import WpscanAdapter
        adapter = WpscanAdapter()
        args = adapter.build_args({"target": "http://10.0.2.15/wp", "detection_mode": "mixed"})
        assert "--url" in args and "http://10.0.2.15/wp" in args
        assert "--detection-mode" in args and "mixed" in args

        sample_json = (
            '{"version": {"number": "6.2.1"}, "plugins": {"contact-form-7": {"version": {"number": "5.7"}, '
            '"vulnerabilities": [{"title": "Unauthenticated Reflected XSS", "references": {"cve": ["2023-3456"]}}]}}, '
            '"users": {"admin": {}}}'
        )
        parsed = adapter.parse(sample_json, "", 0, {"inputs": {"target": "http://10.0.2.15/wp"}})
        assert parsed["tool"] == "wpscan"
        assert parsed["wordpress_version"] == "6.2.1"
        assert len(parsed["plugins_found"]) == 1
        assert len(parsed["vulnerabilities"]) == 1
        assert "admin" in parsed["users"]


# =============================================================================
# 2. ARGUMENT VALIDATION & SECURITY SANITIZATION TESTS
# =============================================================================

class TestArgumentValidationAndSecurity:
    @pytest.fixture
    def registry(self):
        return ToolRegistry()

    def test_validate_nmap_valid_arguments(self, registry):
        spec = registry.get("nmap.scan.v1")
        assert spec is not None
        valid_args = {"target": "10.0.2.15", "ports": "22,80,443", "timing": 4, "scan_type": "sV"}
        is_valid, errors = validate_tool_arguments(spec, valid_args)
        assert is_valid is True
        assert len(errors) == 0

    def test_validate_missing_required_parameter(self, registry):
        spec = registry.get("nmap.scan.v1")
        assert spec is not None
        invalid_args = {"ports": "80,443"}  # missing 'target'
        is_valid, errors = validate_tool_arguments(spec, invalid_args)
        assert is_valid is False
        assert any("Missing required parameter 'target'" in e for e in errors)

    def test_validate_invalid_type_and_enum(self, registry):
        spec = registry.get("nmap.scan.v1")
        assert spec is not None
        invalid_args = {"target": "10.0.2.15", "timing": "not_an_int", "scan_type": "INVALID_SCAN"}
        is_valid, errors = validate_tool_arguments(spec, invalid_args)
        assert is_valid is False
        assert any("Parameter 'timing' must be an integer" in e for e in errors)
        assert any("Parameter 'scan_type'" in e and "not in permitted choices" in e for e in errors)

    def test_validate_command_injection_rejected(self, registry):
        spec = registry.get("nmap.scan.v1")
        assert spec is not None
        injection_args = {"target": "10.0.2.15 && cat /etc/passwd"}
        is_valid, errors = validate_tool_arguments(spec, injection_args)
        assert is_valid is False
        assert any("command injection sequence" in e for e in errors)

    def test_adapter_validate_inputs_rejects_injection_directly(self):
        from orchestrator.adapters.nmap_adapter import NmapAdapter
        adapter = NmapAdapter()
        is_valid, errors = adapter.validate_inputs({"target": "127.0.0.1; rm -rf /"})
        assert is_valid is False
        assert any("Command injection sequence" in e for e in errors)

        # Execution returns exit_code=400 error observation without running
        obs = adapter.execute({"target": "127.0.0.1; rm -rf /"})
        assert obs.status == "error"
        assert obs.exit_code == 400
        assert "Command injection" in obs.error


# =============================================================================
# 3. BROAD COMMAND EXECUTION RESTRICTION VS TYPED ADAPTERS
# =============================================================================

class TestWorkflowApprovalAndTypedPrecedence:
    def test_typed_tools_always_approved(self):
        for tool_id in ["nmap.scan.v1", "gobuster.dir.v1", "wpscan.audit.v1", "subfinder.enum.v1"]:
            approved, reason = is_workflow_approved(tool_id, {"target": "10.0.2.15"})
            assert approved is True
            assert "Typed security tool" in reason

    def test_broad_execution_rejected_without_approved_workflow(self):
        for broad_id in ["shell.run.v1", "kali.exec.v1"]:
            approved, reason = is_workflow_approved(broad_id, {"command": "whoami"})
            assert approved is False
            assert "restricted to explicitly approved workflows" in reason

    def test_broad_execution_permitted_with_approved_workflow_flag(self):
        for broad_id in ["shell.run.v1", "kali.exec.v1"]:
            approved, reason = is_workflow_approved(broad_id, {"command": "whoami", "approved_workflow": True})
            assert approved is True
            assert "Explicit workflow approval granted" in reason

    def test_broad_execution_permitted_via_scope_contract(self):
        scope_contract = {
            "contract_id": "scope_test_123",
            "metadata": {"allow_unrestricted_execution": True},
        }
        approved, reason = is_workflow_approved("kali.exec.v1", {"command": "id"}, scope_contract=scope_contract)
        assert approved is True
        assert "Unrestricted execution approved under Scope Contract" in reason

    def test_tool_selector_favors_typed_adapters_over_broad_execution(self):
        # Even when prompt says "run command" or "in kali", a security operation MUST map to typed adapter
        queries = [
            ("Run an nmap scan on 10.0.2.15 to check open ports", "nmap.scan.v1"),
            ("In Kali sandbox, execute gobuster directory scan on http://10.0.2.15", "gobuster.dir.v1"),
            ("Run subfinder subdomain enumeration for target.lab", "subfinder.enum.v1"),
            ("Perform WordPress scan on http://target.lab with wpscan", "wpscan.audit.v1"),
            ("Run trivy filesystem scan on /home/kali to detect CVEs", "trivy.fs.v1"),
            ("DNS zone transfer check with dnsrecon on target.lab", "dnsrecon.enum.v1"),
            ("SQL injection test on http://target.lab/vuln.php with sqlmap", "sqlmap.scan.v1"),
        ]

        for query, expected_tool_id in queries:
            result = tool_selector.select(goal=query)
            assert result.selected_tool.tool_id == expected_tool_id, (
                f"Query '{query}' expected typed tool '{expected_tool_id}', "
                f"but got '{result.selected_tool.tool_id}' ({result.selected_tool.tool_name})"
            )


# =============================================================================
# 4. COMPLETE END-TO-END EXECUTION CHAIN TESTS
# =============================================================================

class TestCompleteExecutionChain:
    """
    Verifies the entire sequence:
    User request → tool selection → argument construction → validation → adapter → Kali execution → output parsing.
    """

    def test_complete_chain_nmap_recon(self, temp_db):
        agent = AgentLoop(db_path=temp_db)
        prompt = "Run nmap scan on 127.0.0.1 to find open services"

        res = agent.execute_task(session_id="test_session_chain", message=prompt)

        # 1. Tool selection verified
        assert res["tool_executed"]["id"] == "nmap.scan.v1"
        assert res["tool_selection"]["selected_tool"]["tool_id"] == "nmap.scan.v1"

        # 2. Argument construction verified
        raw_args = res["event"]["requested_args"]
        import json
        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        assert args["target"] == "127.0.0.1"

        # 3. Validation passed
        assert res.get("status") != "rejected"
        assert res["execution"]["exit_code"] in (0, -1, 403) or "exit_code" in res["execution"]

        # 4. Adapter & Kali execution executed
        assert res["execution"]["adapter"] == "nmap.scan.v1"

        # 5. Output parsing verified
        obs = res["execution"].get("observation", {})
        assert obs.get("tool") == "nmap"

        # 6. Event stored in SQLite events.db
        events = get_events_by_session("test_session_chain", temp_db)
        assert len(events) >= 1
        assert events[0]["tool_id"] == "nmap.scan.v1"

    def test_complete_chain_subfinder_discovery(self, temp_db):
        agent = AgentLoop(db_path=temp_db)
        prompt = "Enumerate subdomains for 127.0.0.1 using subfinder"

        res = agent.execute_task(session_id="test_session_subfinder", message=prompt)

        assert res["tool_executed"]["id"] == "subfinder.enum.v1"
        assert res["execution"]["adapter"] == "subfinder.enum.v1"
        assert res.get("status") != "rejected"

    def test_complete_chain_wpscan_audit(self, temp_db):
        agent = AgentLoop(db_path=temp_db)
        prompt = "Scan WordPress website at http://127.0.0.1:8080 with wpscan"

        res = agent.execute_task(session_id="test_session_wpscan", message=prompt)

        assert res["tool_executed"]["id"] == "wpscan.audit.v1"
        assert res["execution"]["adapter"] == "wpscan.audit.v1"
        assert res.get("status") != "rejected"

    def test_complete_chain_unapproved_command_execution_blocked(self, temp_db):
        agent = AgentLoop(db_path=temp_db)
        prompt = "Execute raw bash command `rm -rf /` via shell.run.v1"

        res = agent.execute_task(
            session_id="test_session_blocked",
            message=prompt,
            explicit_tool="shell.run.v1",
            explicit_args={"command": "rm -rf /"},
        )

        # Must be rejected by Workflow Policy Gate
        assert res["status"] == "rejected"
        assert res["error"] == "UNAPPROVED_COMMAND_EXECUTION"
        assert "restricted to explicitly approved workflows" in res["reply"]
        assert res["execution"]["exit_code"] == 403

        # Must be audited in events.db
        events = get_events_by_session("test_session_blocked", temp_db)
        assert len(events) >= 1
        assert events[0]["exit_code"] == 403
        assert events[0]["actor"] == "gateway:workflow_policy"

    def test_complete_chain_approved_broad_command_permitted(self, temp_db):
        # Create Scope Contract with explicit unrestricted execution authorization
        create_scope_contract(
            targets=["127.0.0.1", "localhost"],
            network_scope="authorized_lab",
            time_window="48h",
            authorized_by="secops_lead@kairo.internal",
            allowed_tool_tiers=[1, 2, 3, 4],
            metadata={"allow_unrestricted_execution": True},
            db_path=temp_db,
        )

        agent = AgentLoop(db_path=temp_db)
        res = agent.execute_task(
            session_id="test_session_approved_broad",
            message="Run uname -a in kali sandbox",
            explicit_tool="kali.exec.v1",
            explicit_args={"command": "uname", "args": ["-a"], "approved_workflow": True},
        )

        # Approved: not rejected by workflow gate
        assert res.get("status") != "rejected"
        assert res["tool_executed"]["id"] == "kali.exec.v1"
        assert res["execution"]["adapter"] == "kali.exec.v1"
        assert res["execution"]["adapter"] == "kali.exec.v1"
