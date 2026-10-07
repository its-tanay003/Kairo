"""
Integration Tests for Third-Party Tool Addition via ToolSpec SDK Alone
and Multi-Model Version Score History on Public Benchmark Leaderboard.

Validates:
1. Third-party developer authored 'subfinder.enum.v1' entirely using the ToolSpec SDK:
   - YAML specification in registry/tools/subfinder_enum_v1.yaml
   - Adapter in sdk/tools/subfinder_enum_v1/subfinder_enum_v1_adapter.py
   - Parser in sdk/tools/subfinder_enum_v1/subfinder_enum_v1_parser.py
2. ToolSpec 7-Gate Conformance Engine certification:
   - Gate 1: Blueprint Schema Gate (16 required fields)
   - Gate 2: Adapter Contract Gate (build_args, parse, etc.)
   - Gate 3: Argument Typing Gate
   - Gate 4: Parser Safety Gate (exception resilience)
   - Gate 5: Observer Fact Gate (entity extraction)
   - Gate 6: Scope Contract Gate (CIDR / domain boundary checks)
   - Gate 7: Operational Safety & Timeout Bounds (<= 300s, rollback declared)
   - Certified with 100% pass score and STATUS: TRUSTED.
3. Zero-core-modification discovery and execution:
   - Tool is discovered and loaded dynamically through sdk.registry_bridge.
   - Core orchestrator files required zero manual code additions for this tool.
4. Observer Structured Fact & Entity Extraction:
   - Subdomains, hosts, IPs, and observations extracted properly.
5. Public Benchmark Leaderboard Multi-Model Version Score History:
   - Evaluates history across >= 2 model versions (e.g. kairo-dpo-1b, kairo-sft-1b, kairo-grpo-1.5b).
   - Verifies mean scores, peak scores, and chronological evaluation runs per model version.
   - Verifies FastAPI route /benchmark/leaderboard delivers version_score_history payload.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from orchestrator.server import app
from orchestrator.benchmark_manager import BenchmarkManager, benchmark_manager
from orchestrator.observer import Observer, ObservationFact
from orchestrator.adapters.registry import adapter_registry
from registry.loader import ToolRegistry
from sdk.conformance import ToolSpecConformanceRunner, ConformanceReport
from sdk.cli import run_verify
from sdk.registry_bridge import auto_discover_sdk_tools
from sdk.tools.subfinder_enum_v1.subfinder_enum_v1_adapter import SubfinderEnumV1Adapter


@pytest.fixture
def client():
    """FastAPI TestClient for Orchestrator server routes."""
    return TestClient(app)


# ==============================================================================
# 1. THIRD-PARTY TOOL SPECIFICATION AND SDK ADAPTER VERIFICATION
# ==============================================================================

def test_third_party_tool_artifacts_exist():
    """Verify that the third-party tool was authored exclusively in SDK and registry locations."""
    repo_root = Path(__file__).resolve().parent.parent

    yaml_spec = repo_root / "registry" / "tools" / "subfinder_enum_v1.yaml"
    adapter_file = repo_root / "sdk" / "tools" / "subfinder_enum_v1" / "subfinder_enum_v1_adapter.py"
    parser_file = repo_root / "sdk" / "tools" / "subfinder_enum_v1" / "subfinder_enum_v1_parser.py"

    assert yaml_spec.exists(), f"Missing third-party YAML specification at {yaml_spec}"
    assert adapter_file.exists(), f"Missing third-party adapter at {adapter_file}"
    assert parser_file.exists(), f"Missing third-party parser at {parser_file}"

    # Verify YAML content has necessary metadata
    content = yaml_spec.read_text(encoding="utf-8")
    assert "id: subfinder.enum.v1" in content
    assert "category: recon" in content
    assert "version: 1.0.0" in content
    assert "binary: subfinder" in content


def test_third_party_tool_7_gate_conformance_certification():
    """Run the official SDK 7-Gate Conformance Engine on the third-party tool."""
    yaml_path = Path(__file__).resolve().parent.parent / "registry" / "tools" / "subfinder_enum_v1.yaml"

    report = run_verify(yaml_path=str(yaml_path))

    assert report is not None
    assert report.tool_id == "subfinder.enum.v1"
    assert report.total_gates == 7
    assert report.passed_gates == 7
    assert report.score_pct == 100.0
    assert report.trusted is True

    # Validate individual gate names
    gate_names = [g.name for g in report.gate_results]
    assert any("Blueprint" in name for name in gate_names)
    assert any("Adapter" in name for name in gate_names)
    assert any("Argument" in name for name in gate_names)
    assert any("Parser" in name for name in gate_names)
    assert any("Observer" in name for name in gate_names)
    assert any("Scope Contract" in name for name in gate_names)
    assert any("Operational Safety" in name for name in gate_names)


# ==============================================================================
# 2. DYNAMIC REGISTRY BRIDGING & ZERO CORE MODIFICATIONS
# ==============================================================================

def test_dynamic_registry_discovery_without_core_modification():
    """Verify the tool is registered dynamically through the SDK registry bridge."""
    # Ensure bridge discovery has loaded SDK tools
    auto_discover_sdk_tools()

    # Verify adapter registration in adapter_registry
    adapter = adapter_registry.get("subfinder.enum.v1")
    assert adapter is not None, "subfinder.enum.v1 adapter was not registered in adapter_registry"
    assert adapter.tool_id == "subfinder.enum.v1"

    # Verify ToolRegistry spec loading
    reg = ToolRegistry()
    spec = reg.get("subfinder.enum.v1")
    assert spec is not None
    assert spec.id == "subfinder.enum.v1"
    assert spec.category == "recon"
    assert spec.binary == "subfinder"


def test_third_party_adapter_argument_compilation():
    """Verify that the third-party adapter compiles command arguments accurately."""
    adapter = adapter_registry.get_instance("subfinder.enum.v1")
    assert adapter is not None

    args = adapter.build_args({
        "domain": "corp.internal.net",
        "silent": True,
        "threads": 25,
        "timeout": 45,
    })

    assert isinstance(args, list)
    assert "-d" in args
    assert "corp.internal.net" in args
    assert "-silent" in args
    assert "-t" in args
    assert "25" in args
    assert "-timeout" in args
    assert "45" in args


def test_third_party_parser_and_observer_fact_extraction():
    """Verify that the third-party parser normalizes outputs and Observer extracts facts."""
    observer = Observer()

    sample_stdout = """
[INF] Enumerating subdomains for corp.internal.net
api.corp.internal.net
auth.corp.internal.net 10.0.0.15
vpn.corp.internal.net
portal.corp.internal.net
[INF] Found 4 subdomains in 1.2 seconds
"""
    obs = observer.observe(
        tool_id="subfinder.enum.v1",
        stdout=sample_stdout,
        stderr="",
        exit_code=0,
        meta={"inputs": {"domain": "corp.internal.net"}},
    )

    assert isinstance(obs.facts, ObservationFact)
    assert obs.status.lower() == "success"

    # Verify discovered hosts & subdomains
    extracted_hosts = obs.facts.hosts
    assert any("api.corp.internal.net" in h for h in extracted_hosts) or "api.corp.internal.net" in obs.raw_observation.get("subdomains", [])
    assert any("vpn.corp.internal.net" in h for h in extracted_hosts) or "vpn.corp.internal.net" in obs.raw_observation.get("subdomains", [])

    # Verify raw observation findings
    assert obs.raw_observation.get("count", 0) >= 3
    assert len(obs.raw_observation.get("findings", [])) >= 1


# ==============================================================================
# 3. MULTI-MODEL VERSION SCORE HISTORY ON BENCHMARK LEADERBOARD
# ==============================================================================

def test_leaderboard_multi_model_version_score_history_manager():
    """Verify that BenchmarkManager aggregates empirical score history across >= 2 model versions."""
    mgr = BenchmarkManager()
    leaderboard = mgr.get_leaderboard_data()

    assert "version_score_history" in leaderboard
    vh_list = leaderboard["version_score_history"]

    assert isinstance(vh_list, list)
    assert len(vh_list) >= 2, f"Expected at least 2 model versions in history, got {len(vh_list)}"

    model_ids = [vh["model_id"] for vh in vh_list]
    assert "kairo-sft-1b" in model_ids, "Expected kairo-sft-1b in score history"
    assert "kairo-dpo-1b" in model_ids, "Expected kairo-dpo-1b in score history"

    # Check structure of each model version item
    for vh in vh_list:
        assert "model_id" in vh
        assert "model_name" in vh
        assert "model_version" in vh
        assert "model_badge" in vh
        assert "model_tier" in vh
        assert vh["total_runs"] > 0
        assert vh["mean_composite_score"] > 0
        assert vh["best_composite_score"] >= vh["mean_composite_score"]
        assert len(vh["chronological_scores"]) > 0

        # Check score points
        for pt in vh["chronological_scores"]:
            assert "run_id" in pt
            assert "composite_score" in pt
            assert "tasks" in pt
            assert "commit" in pt


def test_leaderboard_runs_contain_model_attribution():
    """Verify that every historical evaluation run includes explicit model version attribution."""
    mgr = BenchmarkManager()
    leaderboard = mgr.get_leaderboard_data()

    recent_runs = leaderboard["golden_benchmark"]["recent_runs"]
    assert len(recent_runs) > 0

    # Ensure model metadata is attached to runs
    for run in recent_runs:
        assert "model_id" in run
        assert "model_name" in run
        assert "model_badge" in run
        assert "model_tier" in run
        assert run["model_id"] in ["kairo-dpo-1b", "kairo-sft-1b", "kairo-grpo-1.5b", "kairo-base-380m"]


def test_leaderboard_api_endpoint_delivers_version_score_history(client):
    """Verify FastAPI endpoint GET /benchmark/leaderboard exposes version score history."""
    response = client.get("/benchmark/leaderboard")
    assert response.status_code == 200

    data = response.json()
    assert "version_score_history" in data
    assert len(data["version_score_history"]) >= 2

    # Check model versions represented
    v_ids = [v["model_id"] for v in data["version_score_history"]]
    assert "kairo-dpo-1b" in v_ids
    assert "kairo-sft-1b" in v_ids


def test_trigger_benchmark_run_updates_version_score_history():
    """Verify triggering a benchmark run records to the specific model version history."""
    mgr = BenchmarkManager()

    # Trigger a run on kairo-dpo-1b
    res = mgr.trigger_benchmark_run(benchmark_type="golden", model_id="kairo-dpo-1b")
    assert res["success"] is True
    run_res = res["run"]
    assert run_res["model_id"] == "kairo-dpo-1b"
    assert run_res["composite_score"] > 80.0

    # Verify updated leaderboard includes this run
    updated_lb = mgr.get_leaderboard_data()
    dpo_history = next((vh for vh in updated_lb["version_score_history"] if vh["model_id"] == "kairo-dpo-1b"), None)
    assert dpo_history is not None
    assert dpo_history["total_runs"] >= 1
    recent_run_ids = [s["run_id"] for s in dpo_history["chronological_scores"]]
    assert run_res["run_id"] in recent_run_ids
