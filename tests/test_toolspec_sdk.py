"""
Tests for Kairo ToolSpec SDK.
Validates:
  1. CLI tool generation (`create-toolspec`).
  2. Dynamic runtime registry bridging without modifying core orchestrator/gateway code.
  3. 7-Gate Conformance Engine (including rejection of non-compliant tools).
  4. Full conformance certification of 3 new tools:
     - dnsrecon.enum.v1
     - wpscan.audit.v1
     - trivy.fs.v1
  5. Observer observation fact normalization across all new tools.
"""

import tempfile
import pytest
from pathlib import Path
import yaml

from sdk.base import BaseToolAdapter, BaseToolParser
from sdk.generator import ToolSpecGenerator, to_slug, to_class_name
from sdk.registry_bridge import register_adapter, load_toolspec, auto_discover_sdk_tools
from sdk.conformance import ToolSpecConformanceRunner, ConformanceReport
from sdk.tools.dnsrecon_enum_v1.dnsrecon_enum_v1_adapter import DnsreconEnumV1Adapter
from sdk.tools.wpscan_audit_v1.wpscan_audit_v1_adapter import WpscanAuditV1Adapter
from sdk.tools.trivy_fs_v1.trivy_fs_v1_adapter import TrivyFsV1Adapter
from orchestrator.adapters.registry import adapter_registry
from orchestrator.observer import Observer, ObservationFact
from registry.loader import ToolRegistry


def test_generator_scaffolding():
    with tempfile.TemporaryDirectory() as tmp_dir:
        gen = ToolSpecGenerator(root_dir=tmp_dir)
        paths = gen.generate(
            tool_id="test.scanner.v1",
            category="recon",
            binary="testscan",
            output_dir=Path(tmp_dir) / "test_scanner_v1",
            target_in_registry=False,
        )

        assert paths["yaml"].exists()
        assert paths["adapter"].exists()
        assert paths["parser"].exists()
        assert paths["test"].exists()
        assert paths["readme"].exists()

        with open(paths["yaml"], "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            assert data["id"] == "test.scanner.v1"
            assert data["binary"] == "testscan"
            assert "rollback" in data
            assert "version_compatibility" in data


def test_conformance_runner_rejection_of_invalid_tool():
    runner = ToolSpecConformanceRunner()
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        bad_yaml = Path(tmp_dir) / "bad_tool.yaml"
        # Tool missing rollback and with excessive timeout (>300s)
        spec = {
            "id": "bad.tool.v1",
            "binary": "bad",
            "category": "exploit",
            "capabilities": ["test"],
            "inputs": {"type": "object", "properties": {"target": {"type": "string"}}},
            "outputs": {"type": "object"},
            "side_effects": ["traffic"],
            "privilege": "user",
            "gui": False,
            "parser": "bad_parser",
            "prerequisites": ["bad"],
            "docs": {"summary": "bad tool"},
            "success_signals": {"exit_codes": [0]},
            "failure_signals": {"exit_codes": [1]},
            "version_compatibility": {"min_agent_version": "1.0.0"},
            "timeout_ms": 500000, # Exceeds 300,000ms safety bound
        }
        with open(bad_yaml, "w", encoding="utf-8") as f:
            yaml.dump(spec, f)

        class NonConformantAdapter:
            tool_id = "bad.tool.v1"

        report = runner.run_conformance(
            yaml_path=bad_yaml,
            adapter_cls=NonConformantAdapter,  # Doesn't inherit from ToolAdapter
        )
        assert report.trusted is False
        assert report.passed_gates < report.total_gates
        # Gate 2 must fail due to inheritance
        g2 = next(g for g in report.gate_results if "Gate 2" in g.name)
        assert g2.passed is False
        # Gate 7 must fail due to timeout & missing rollback
        g7 = next(g for g in report.gate_results if "Gate 7" in g.name)
        assert g7.passed is False


def test_new_tool_dnsrecon_conformance():
    runner = ToolSpecConformanceRunner()
    yaml_path = Path("registry/tools/dnsrecon_enum_v1.yaml").resolve()
    report = runner.run_conformance(
        yaml_path=yaml_path,
        adapter_cls=DnsreconEnumV1Adapter,
        sample_inputs={"target": "target.lab", "scan_type": "std"},
        sample_stdout="[*] A target.lab 192.168.1.100\n[*] NS ns1.target.lab 192.168.1.1\n[*] Zone Transfer Successful",
        sample_exit_code=0,
    )
    assert report.trusted is True
    assert report.passed_gates == 7
    assert report.score_pct == 100.0
    assert report.sha256_spec
    assert report.sha256_adapter


def test_new_tool_wpscan_conformance():
    runner = ToolSpecConformanceRunner()
    yaml_path = Path("registry/tools/wpscan_audit_v1.yaml").resolve()
    report = runner.run_conformance(
        yaml_path=yaml_path,
        adapter_cls=WpscanAuditV1Adapter,
        sample_inputs={"target": "http://127.0.0.1:8080", "detection_mode": "passive"},
        sample_stdout="WordPress version 5.8.1 identified\n[i] Plugin: elementor (version 3.4.0)\n[!] Contact Form 7 SQL Injection",
        sample_exit_code=0,
    )
    assert report.trusted is True
    assert report.passed_gates == 7
    assert report.score_pct == 100.0


def test_new_tool_trivy_conformance():
    runner = ToolSpecConformanceRunner()
    yaml_path = Path("registry/tools/trivy_fs_v1.yaml").resolve()
    report = runner.run_conformance(
        yaml_path=yaml_path,
        adapter_cls=TrivyFsV1Adapter,
        sample_inputs={"target": "/home/kali", "severity": "HIGH,CRITICAL"},
        sample_stdout='{"Results": [{"Target": "/app/package.json", "Vulnerabilities": [{"VulnerabilityID": "CVE-2023-1234", "PkgName": "express", "Severity": "HIGH"}]}]}',
        sample_exit_code=0,
    )
    assert report.trusted is True
    assert report.passed_gates == 7
    assert report.score_pct == 100.0


def test_dynamic_registry_bridging_zero_core_modifications():
    # Verify that third party tools can register dynamically without touching orchestrator
    assert "dnsrecon.enum.v1" in adapter_registry._adapters
    assert "wpscan.audit.v1" in adapter_registry._adapters
    assert "trivy.fs.v1" in adapter_registry._adapters

    # ToolRegistry should successfully load and query specs
    reg = ToolRegistry()
    spec_dns = reg.get("dnsrecon.enum.v1")
    assert spec_dns is not None
    assert spec_dns.binary == "dnsrecon"

    spec_wp = reg.get("wpscan.audit.v1")
    assert spec_wp is not None
    assert spec_wp.binary == "wpscan"

    spec_trivy = reg.get("trivy.fs.v1")
    assert spec_trivy is not None
    assert spec_trivy.binary == "trivy"


def test_observer_structured_facts_normalization():
    observer = Observer()

    # 1. Test DNSRecon observation fact extraction
    obs_dns = observer.observe(
        tool_id="dnsrecon.enum.v1",
        stdout="[*] A target.lab 192.168.1.150\n[*] Zone Transfer Successful",
        stderr="",
        exit_code=0,
        meta={"inputs": {"target": "target.lab"}},
    )
    assert isinstance(obs_dns.facts, ObservationFact)
    assert obs_dns.status.lower() == "success"
    assert "target.lab" in obs_dns.facts.hosts or "192.168.1.150" in obs_dns.facts.hosts
    assert len(obs_dns.raw_observation.get("findings", [])) >= 1

    # 2. Test WPScan observation fact extraction
    obs_wp = observer.observe(
        tool_id="wpscan.audit.v1",
        stdout="WordPress version 6.2 identified\n[i] Plugin: woocommerce (version 7.0)\n[!] WooCommerce Authenticated RCE",
        stderr="",
        exit_code=0,
        meta={"inputs": {"target": "http://127.0.0.1:8080"}},
    )
    assert isinstance(obs_wp.facts, ObservationFact)
    assert any("WordPress" in t for t in obs_wp.raw_observation.get("technologies", []))
    assert len(obs_wp.raw_observation.get("vulnerabilities", [])) >= 1

    # 3. Test Trivy observation fact extraction
    obs_trivy = observer.observe(
        tool_id="trivy.fs.v1",
        stdout='{"Results": [{"Target": "/app", "Vulnerabilities": [{"VulnerabilityID": "CVE-2024-9999", "PkgName": "urllib3", "Severity": "CRITICAL"}]}]}',
        stderr="",
        exit_code=0,
        meta={"inputs": {"target": "/app"}},
    )
    assert isinstance(obs_trivy.facts, ObservationFact)
    assert any("CVE-2024-9999" in str(f) for f in obs_trivy.raw_observation.get("vulnerabilities", []))
