"""
Test Model Center configuration, system resource detection (VRAM/RAM),
model selection across all frontend options, and execution routing.
"""

from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.agent import AgentLoop
from orchestrator.model_center import model_center
from orchestrator.server import app


FRONTEND_MODEL_OPTIONS = [
    {
        "id": "kairo-scale-2b",
        "alias": "Kairo 3.7 (Cyber-Ops Sonnet)",
        "expected_role": "primary-custom-scaled-tier-c",
    },
    {
        "id": "Qwen2.5-0.5B-Instruct",
        "alias": "Kairo 3.5 (Haiku Fast)",
        "expected_role": "fallback",
    },
    {
        "id": "Qwen3-Coder-30B-A3B-Instruct",
        "alias": "Llama-3-70B Pentest SFT",
        "expected_role": "primary",
    },
    {
        "id": "kairo-scale-2b-grpo",
        "alias": "DeepSeek-R1 Reasoner",
        "expected_role": "primary-custom-scaled-grpo",
    },
]


def test_model_center_unit_status():
    """Verifies model center status reports valid telemetry and catalog."""
    status = model_center.get_status()
    assert "model_id" in status
    assert "runtime" in status
    assert "quantization" in status
    assert "context_length" in status
    assert "role" in status
    assert "total_mb" in status["vram"]
    assert "total_mb" in status["ram"]

    fallback = next((m for m in status["models_catalog"] if m.get("role") == "fallback"), None)
    assert fallback is not None, "Missing fallback model in models_catalog"
    assert fallback["model_id"] == "Qwen2.5-0.5B-Instruct"


def test_model_selection_across_all_frontend_options():
    """
    Verifies that selecting any of the frontend model options
    (by exact ID or by display alias) updates active_model correctly.
    """
    for opt in FRONTEND_MODEL_OPTIONS:
        # 1. Test selection by canonical ID
        res_id = model_center.select_model(opt["id"])
        assert res_id["model_id"] == opt["id"]
        assert model_center.get_active_model()["model_id"] == opt["id"]

        # 2. Test selection by display alias
        res_alias = model_center.select_model(opt["alias"])
        assert res_alias["model_id"] == opt["id"]
        assert model_center.get_active_model()["model_id"] == opt["id"]


def test_agent_execution_with_selected_model():
    """
    Verifies that passing model_id into AgentLoop.execute_task() activates
    the requested model and tags the execution result and event network_context.
    """
    agent = AgentLoop()

    for opt in FRONTEND_MODEL_OPTIONS:
        res = agent.execute_task(
            session_id=f"test_session_{opt['id']}",
            message="Check model status and tool execution",
            model_id=opt["id"],
        )

        assert res.get("model_id") == opt["id"], f"Expected model_id {opt['id']}, got {res.get('model_id')}"
        assert res.get("model_role") == opt["expected_role"]

        # Verify active model in model_center was switched
        assert model_center.get_active_model()["model_id"] == opt["id"]

        # Verify event network_context was tagged with the model
        event_dict = res.get("event")
        if isinstance(event_dict, dict):
            net_ctx = event_dict.get("network_context")
            if isinstance(net_ctx, dict):
                assert net_ctx.get("model_id") == opt["id"]


def test_fastapi_model_center_and_run_endpoints():
    """
    Tests FastAPI /model-center/select and /run endpoints with TestClient
    to ensure full end-to-end HTTP payload validation and model activation.
    """
    client = TestClient(app)

    # 1. GET /model-center
    get_res = client.get("/model-center")
    assert get_res.status_code == 200
    data = get_res.json()
    assert "model_id" in data
    assert "models_catalog" in data

    # 2. POST /model-center/select for all options
    for opt in FRONTEND_MODEL_OPTIONS:
        post_res = client.post("/model-center/select", json={"model_id": opt["id"]})
        assert post_res.status_code == 200, f"Failed selecting {opt['id']}: {post_res.text}"
        post_data = post_res.json()
        assert post_data["success"] is True
        assert post_data["active_model"]["model_id"] == opt["id"]

        # Verify GET /model-center reflects the switch
        curr_res = client.get("/model-center")
        assert curr_res.json()["model_id"] == opt["id"]

    # 3. POST /run with model_id
    target_opt = FRONTEND_MODEL_OPTIONS[0]  # Kairo 3.7 (kairo-scale-2b)
    run_res = client.post(
        "/run",
        json={
            "session_id": "api_test_session",
            "message": "ping check",
            "model_id": target_opt["id"],
        },
    )
    assert run_res.status_code == 200, f"/run failed: {run_res.text}"
    run_data = run_res.json()
    assert run_data.get("model_id") == target_opt["id"]
    assert run_data.get("model_role") == target_opt["expected_role"]
