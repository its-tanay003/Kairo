"""
Conformance test suite for trivy.fs.v1.
Verifies compliance with Kairo 7-Gate Conformance Standards.
"""

import pytest
from pathlib import Path
from sdk.conformance import ToolSpecConformanceRunner
from sdk.tools.trivy_fs_v1.trivy_fs_v1_adapter import TrivyFsV1Adapter

SPEC_PATH = Path(r"C:\New Volume (D)\dev\registry\tools\trivy_fs_v1.yaml")


def test_trivy_fs_v1_conformance_gates():
    runner = ToolSpecConformanceRunner()
    report = runner.run_conformance(
        yaml_path=SPEC_PATH,
        adapter_cls=TrivyFsV1Adapter,
        sample_inputs={"target": "127.0.0.1"},
        sample_stdout="Execution finished with exit code 0",
        sample_exit_code=0,
    )
    assert report.trusted is True, f"Conformance failed: {[g.name + ': ' + g.details for g in report.gate_results if not g.passed]}"
    assert report.passed_gates == report.total_gates
    assert report.score_pct == 100.0
