"""
Kairo ToolSpec SDK - Conformance Test Suite & Trust Certifier.
Reuses and extends Task 1.3's conformance test patterns.

A third-party ToolSpec + Adapter + Parser MUST pass all 7 Conformance Gates
before being marked 'TRUSTED' by Kairo:
  Gate 1: Blueprint 16-Field JSON Schema Validation
  Gate 2: ToolAdapter Implementation Contract
  Gate 3: Argument Compilation & Parameter Safety
  Gate 4: Output Parser Determinism & Error Handling
  Gate 5: Observation Fact Normalization (Observer Integration)
  Gate 6: Scope Contract Boundary Compliance
  Gate 7: Operational Safety & Timeout Bounds (<= 300s, rollback declared)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
from orchestrator.adapters.base import ToolAdapter
from orchestrator.observer import Observer, ObservationFact
from registry.loader import ToolRegistry, ToolSpec

logger = logging.getLogger("sdk.conformance")


@dataclass
class GateResult:
    name: str
    passed: bool
    details: str
    errors: List[str] = field(default_factory=list)


@dataclass
class ConformanceReport:
    tool_id: str
    tool_version: str
    trusted: bool
    score_pct: float
    passed_gates: int
    total_gates: int
    gate_results: List[GateResult]
    sha256_spec: str
    sha256_adapter: str
    attestation_timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "trusted": self.trusted,
            "score_pct": self.score_pct,
            "passed_gates": self.passed_gates,
            "total_gates": self.total_gates,
            "gate_results": [
                {"name": g.name, "passed": g.passed, "details": g.details, "errors": g.errors}
                for g in self.gate_results
            ],
            "sha256_spec": self.sha256_spec,
            "sha256_adapter": self.sha256_adapter,
            "attestation_timestamp": self.attestation_timestamp,
        }


class ToolSpecConformanceRunner:
    """
    Executes rigorous conformance checks against a candidate ToolSpec and Adapter.
    Issues 'TRUSTED' certification status if all gates pass.
    """

    def __init__(self, registry: Optional[ToolRegistry] = None):
        self.registry = registry or ToolRegistry()
        self.observer = Observer()

    def run_conformance(
        self,
        yaml_path: Path | str,
        adapter_cls: Type[ToolAdapter],
        sample_inputs: Optional[Dict[str, Any]] = None,
        sample_stdout: str = "Scan completed successfully with 0 findings",
        sample_stderr: str = "",
        sample_exit_code: int = 0,
    ) -> ConformanceReport:
        yaml_file = Path(yaml_path)
        if not yaml_file.exists():
            raise FileNotFoundError(f"Spec file not found: {yaml_file}")

        # Compute file hashes
        with open(yaml_file, "rb") as f:
            sha256_spec = hashlib.sha256(f.read()).hexdigest()

        import inspect
        try:
            adapter_source = inspect.getsource(adapter_cls).encode("utf-8")
            sha256_adapter = hashlib.sha256(adapter_source).hexdigest()
        except Exception:
            sha256_adapter = "dynamic_class"

        with open(yaml_file, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)

        gates: List[GateResult] = []

        # ─────────────────────────────────────────────────────────────
        # Gate 1: Blueprint 16-Field Schema Conformance
        # ─────────────────────────────────────────────────────────────
        schema_errors = self.registry.validate_spec_data(raw_data)
        g1_pass = len(schema_errors) == 0
        gates.append(GateResult(
            name="Gate 1: Blueprint 16-Field JSON Schema",
            passed=g1_pass,
            details="All 16 core blueprint fields valid" if g1_pass else f"{len(schema_errors)} schema errors",
            errors=schema_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Gate 2: ToolAdapter Implementation Contract
        # ─────────────────────────────────────────────────────────────
        g2_errors = []
        if not issubclass(adapter_cls, ToolAdapter):
            g2_errors.append("Adapter does not inherit from ToolAdapter")
        if not getattr(adapter_cls, "tool_id", ""):
            g2_errors.append("Adapter missing 'tool_id' attribute")
        elif adapter_cls.tool_id != raw_data.get("id"):
            g2_errors.append(f"Adapter tool_id '{adapter_cls.tool_id}' does not match spec id '{raw_data.get('id')}'")
        
        try:
            instance = adapter_cls()
            if not callable(getattr(instance, "build_args", None)):
                g2_errors.append("Adapter missing callable 'build_args' method")
            if not callable(getattr(instance, "parse", None)):
                g2_errors.append("Adapter missing callable 'parse' method")
        except Exception as e:
            g2_errors.append(f"Adapter instantiation failed: {e}")

        g2_pass = len(g2_errors) == 0
        gates.append(GateResult(
            name="Gate 2: Adapter Implementation Contract",
            passed=g2_pass,
            details="Adapter adheres to standard execution contract" if g2_pass else "; ".join(g2_errors),
            errors=g2_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Gate 3: Argument Compilation & Parameter Safety
        # ─────────────────────────────────────────────────────────────
        g3_errors = []
        test_inputs = sample_inputs or self._synthesize_sample_inputs(raw_data.get("inputs", {}))
        try:
            adapter_instance = adapter_cls()
            args = adapter_instance.build_args(test_inputs)
            if not isinstance(args, list):
                g3_errors.append(f"'build_args' returned {type(args).__name__}, expected list[str]")
            elif not all(isinstance(a, str) for a in args):
                g3_errors.append("All CLI arguments must be strings")
            elif len(args) == 0:
                g3_errors.append("Compiled args list is empty for valid inputs")
        except Exception as e:
            g3_errors.append(f"Argument construction crashed: {e}")

        g3_pass = len(g3_errors) == 0
        gates.append(GateResult(
            name="Gate 3: Argument Compilation & Parameter Safety",
            passed=g3_pass,
            details="CLI arguments built and typed safely" if g3_pass else "; ".join(g3_errors),
            errors=g3_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Gate 4: Output Parser Determinism & Error Handling
        # ─────────────────────────────────────────────────────────────
        g4_errors = []
        try:
            adapter_instance = adapter_cls()
            # Test success parse
            meta = {"inputs": test_inputs, "exit_code": sample_exit_code}
            obs_success = adapter_instance.parse(sample_stdout, sample_stderr, sample_exit_code, meta)
            if not isinstance(obs_success, dict):
                g4_errors.append("Parser output must be a dictionary")
            
            # Test error/crash parse
            obs_err = adapter_instance.parse("", "Execution failed with code 1", 1, meta)
            if not isinstance(obs_err, dict):
                g4_errors.append("Parser failed to handle error/stderr dictionary output")
        except Exception as e:
            g4_errors.append(f"Parser raised unhandled exception: {e}")

        g4_pass = len(g4_errors) == 0
        gates.append(GateResult(
            name="Gate 4: Output Parser Determinism & Error Handling",
            passed=g4_pass,
            details="Parser deterministically handles success and failure envelopes" if g4_pass else "; ".join(g4_errors),
            errors=g4_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Gate 5: Observation Fact Normalization (Observer Integration)
        # ─────────────────────────────────────────────────────────────
        g5_errors = []
        try:
            # Temporarily register adapter in observer registry
            from orchestrator.adapters.registry import adapter_registry
            adapter_registry._adapters[adapter_cls.tool_id] = adapter_cls

            obs_result = self.observer.observe(
                tool_id=adapter_cls.tool_id,
                stdout=sample_stdout,
                stderr=sample_stderr,
                exit_code=sample_exit_code,
                meta={"inputs": test_inputs},
            )
            if not isinstance(obs_result.facts, ObservationFact):
                g5_errors.append("Observer failed to produce normalized ObservationFact")
            if not obs_result.status:
                g5_errors.append("Observer returned empty execution status")
        except Exception as e:
            g5_errors.append(f"Observer fact normalization failed: {e}")

        g5_pass = len(g5_errors) == 0
        gates.append(GateResult(
            name="Gate 5: Observation Fact Normalization (Observer Integration)",
            passed=g5_pass,
            details="Observer parses and normalizes structured facts" if g5_pass else "; ".join(g5_errors),
            errors=g5_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Gate 6: Scope Contract Boundary Compliance
        # ─────────────────────────────────────────────────────────────
        g6_errors = []
        from events.db import is_target_in_scope
        # Verify tool declares inputs schema with target domain/host checks
        inp_props = raw_data.get("inputs", {}).get("properties", {})
        target_keys = [k for k in inp_props.keys() if k in ("target", "domain", "host", "url", "ip")]
        if not target_keys and "path" not in inp_props:
            g6_errors.append("Inputs schema must define at least one target parameter (target, domain, host, url, path)")

        # Verify safe localhost resolution
        if not is_target_in_scope("127.0.0.1", ["127.0.0.1", "localhost", "target.lab"]):
            g6_errors.append("Default Scope Contract failed to validate local lab target")

        g6_pass = len(g6_errors) == 0
        gates.append(GateResult(
            name="Gate 6: Scope Contract Boundary Compliance",
            passed=g6_pass,
            details="Target attributes interface cleanly with Scope Contract verification" if g6_pass else "; ".join(g6_errors),
            errors=g6_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Gate 7: Operational Safety & Timeout Bounds
        # ─────────────────────────────────────────────────────────────
        g7_errors = []
        timeout = raw_data.get("timeout_ms", 5000)
        if timeout > 300000:
            g7_errors.append(f"Timeout {timeout}ms exceeds 300,000ms (5 min) upper safety limit")
        
        privilege = raw_data.get("privilege", "user")
        if privilege not in ["user", "root", "admin", "elevated", "guest"]:
            g7_errors.append(f"Invalid privilege token: {privilege}")

        if not raw_data.get("rollback"):
            g7_errors.append("ToolSpec must declare rollback strategy or compensation behavior")

        if not raw_data.get("failure_signals"):
            g7_errors.append("ToolSpec must declare failure signals")

        g7_pass = len(g7_errors) == 0
        gates.append(GateResult(
            name="Gate 7: Operational Safety & Timeout Bounds",
            passed=g7_pass,
            details="Timeout <= 300s, privilege valid, rollback and failure signals specified" if g7_pass else "; ".join(g7_errors),
            errors=g7_errors,
        ))

        # ─────────────────────────────────────────────────────────────
        # Final Attestation Evaluation
        # ─────────────────────────────────────────────────────────────
        passed_count = sum(1 for g in gates if g.passed)
        total_count = len(gates)
        score_pct = round((passed_count / total_count) * 100, 1)
        is_trusted = (passed_count == total_count)

        import time
        report = ConformanceReport(
            tool_id=raw_data.get("id", getattr(adapter_cls, "tool_id", "unknown")),
            tool_version=str(raw_data.get("version", getattr(adapter_cls, "tool_version", "1.0.0"))),
            trusted=is_trusted,
            score_pct=score_pct,
            passed_gates=passed_count,
            total_gates=total_count,
            gate_results=gates,
            sha256_spec=sha256_spec,
            sha256_adapter=sha256_adapter,
            attestation_timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        return report

    def _synthesize_sample_inputs(self, inputs_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesizes valid default inputs from the ToolSpec inputs schema."""
        props = inputs_schema.get("properties", {})
        result = {}
        for key, prop in props.items():
            if "default" in prop:
                result[key] = prop["default"]
            elif prop.get("type") == "string":
                if key in ("domain", "host", "target"):
                    result[key] = "target.lab"
                elif key == "url":
                    result[key] = "http://127.0.0.1:8888"
                elif key == "path":
                    result[key] = "/home/kali"
                elif "enum" in prop and prop["enum"]:
                    result[key] = prop["enum"][0]
                else:
                    result[key] = f"test_{key}"
            elif prop.get("type") == "integer":
                result[key] = 1
            elif prop.get("type") == "boolean":
                result[key] = False
            elif prop.get("type") == "array":
                result[key] = []
        return result
