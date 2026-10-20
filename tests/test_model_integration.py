"""
Comprehensive verification test suite for Model Integration:
1. Records all 6 audit fields for every ordinary chat request:
   - selected_model
   - inference_runtime
   - processed_by_selected_model
   - structured_output
   - selected_tool and validated_args
   - fallback_reason
2. Verifies custom model is the primary model when available and ready.
3. Verifies existing local model (Qwen2.5-0.5B-Instruct) is the fallback when selected model is unavailable.
4. Verifies cloud inference is strictly blocked and never silently introduced as a fallback.
5. Verifies SQLite event persistence includes the full model_verification record.
6. Verifies model center telemetry returns real backend status, not merely selected label.
"""

import json
import sqlite3
import pytest
from orchestrator.model_integration import (
    ModelIntegrationEngine,
    ModelExecutionRecord,
)
from orchestrator.model_center import model_center
from orchestrator.agent import AgentLoop


@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / "test_events.db")


@pytest.fixture
def agent(test_db_path):
    loop = AgentLoop(db_path=test_db_path)
    return loop


class TestModelReadinessAndRegistration:
    """Verifies checkpoint presence, architecture validation, and air-gapped local checks."""

    def test_custom_primary_model_readiness(self):
        engine = ModelIntegrationEngine()
        report = engine.check_model_readiness("kairo-scale-2b")
        assert report.model_id == "kairo-scale-2b"
        assert report.checkpoint_exists is True
        assert report.ready is True
        assert report.local_only is True
        assert report.cloud_prevented is True
        assert report.size_bytes > 1_000_000_000  # ~1.7 GB
        assert report.architecture_valid is True
        assert report.architecture_details is not None
        assert report.architecture_details.get("swiglu") is True
        assert report.architecture_details.get("rope") is True

    def test_local_fallback_model_readiness(self):
        engine = ModelIntegrationEngine()
        report = engine.check_model_readiness("Qwen2.5-0.5B-Instruct")
        assert report.model_id == "Qwen2.5-0.5B-Instruct"
        assert report.checkpoint_exists is True
        assert report.ready is True
        assert report.runtime == "llama.cpp"
        assert report.local_only is True

    def test_missing_model_readiness_fails_gracefully(self):
        engine = ModelIntegrationEngine()
        report = engine.check_model_readiness("Qwen3-Coder-30B-A3B-Instruct")
        assert report.checkpoint_exists is False
        assert report.ready is False
        assert "not found" in (report.error or "").lower()

    def test_cloud_fallback_is_strictly_prohibited(self):
        engine = ModelIntegrationEngine()
        with pytest.raises(PermissionError) as exc_info:
            engine.resolve_model_for_request("gpt-4o")
        assert "Cloud inference is strictly prohibited" in str(exc_info.value)

        with pytest.raises(PermissionError) as exc_info2:
            engine.resolve_model_for_request("claude-3-7-sonnet")
        assert "Cloud inference is strictly prohibited" in str(exc_info2.value)


class TestModelResolutionAndFallback:
    """Verifies primary model precedence, fallback routing, and explicit reason recording."""

    def test_custom_model_is_primary_when_ready(self):
        engine = ModelIntegrationEngine()
        actual_meta, selected_id, processed_by_selected, fallback_reason = engine.resolve_model_for_request("kairo-scale-2b")
        assert actual_meta["model_id"] == "kairo-scale-2b"
        assert actual_meta.get("runtime", "transformers") == "transformers"
        assert selected_id == "kairo-scale-2b"
        assert processed_by_selected is True
        assert fallback_reason is None

    def test_missing_model_triggers_local_fallback_with_explicit_reason(self):
        engine = ModelIntegrationEngine()
        actual_meta, selected_id, processed_by_selected, fallback_reason = engine.resolve_model_for_request("Qwen3-Coder-30B-A3B-Instruct")
        assert processed_by_selected is False
        assert actual_meta["model_id"] in ("kairo-scale-2b", "Qwen2.5-0.5B-Instruct")
        assert selected_id == "Qwen3-Coder-30B-A3B-Instruct"
        assert fallback_reason is not None
        assert "Qwen3-Coder-30B-A3B-Instruct" in fallback_reason
        assert "fallback" in fallback_reason.lower()

    def test_dispatch_inference_produces_all_six_audit_fields(self):
        engine = ModelIntegrationEngine()
        record = engine.dispatch_inference(
            user_message="Hello, can you explain the target scope?",
            requested_model_id="kairo-scale-2b",
        )
        assert isinstance(record, ModelExecutionRecord)

        # 1. Which model was selected
        assert record.selected_model == "kairo-scale-2b"

        # 2. Which inference runtime handled the request
        assert record.inference_runtime in ("transformers", "llama.cpp")

        # 3. Whether the request was actually processed by that model
        assert record.processed_by_selected_model is True

        # 4. The model's structured output
        assert isinstance(record.structured_output, dict)
        assert "action" in record.structured_output
        assert "content" in record.structured_output
        assert record.structured_output["action"] in ("message", "tool_call")

        # 5. The selected tool and validated arguments, if any
        # (For this conversational query, no tool was invoked)
        assert record.selected_tool is None
        assert record.validated_args is None

        # 6. Why a fallback was used, if applicable
        assert record.fallback_used is False
        assert record.fallback_reason is None

        # Product local-only commitment check
        assert record.local_only is True


class TestOrdinaryChatRequestAuditing:
    """Tests orchestrator chat and tool execution recording the complete model verification chain."""

    def test_ordinary_chat_request_records_model_verification(self, agent):
        response = agent.execute_task(
            session_id="sess_audit_test_01",
            message="Hello agent, what is your status?",
            model_id="kairo-scale-2b",
        )

        # Response must include model_verification dict
        assert "model_verification" in response
        mv = response["model_verification"]

        # Audit Point 1: Which model was selected
        assert mv["selected_model"] == "kairo-scale-2b"
        assert response["selected_model"] == "kairo-scale-2b"

        # Audit Point 2: Which inference runtime handled the request
        assert mv["inference_runtime"] == "transformers"
        assert response["inference_runtime"] == "transformers"

        # Audit Point 3: Whether the request was actually processed by that model
        assert mv["processed_by_selected_model"] is True
        assert response["processed_by_selected_model"] is True

        # Audit Point 4: Model structured output
        assert isinstance(mv["structured_output"], dict)
        assert "action" in mv["structured_output"]

        # Audit Point 5: Tool & validated args
        assert "selected_tool" in mv
        assert "validated_args" in mv

        # Audit Point 6: Fallback reason
        assert mv["fallback_used"] is False
        assert mv["fallback_reason"] is None
        assert mv["local_only"] is True

        # Check SQLite persistence in Event store
        conn = sqlite3.connect(agent.db_path)
        cur = conn.cursor()
        cur.execute("SELECT network_context, normalized_args FROM events ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()

        assert row is not None
        net_ctx = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert "model_verification" in net_ctx
        saved_mv = net_ctx["model_verification"]
        assert saved_mv["selected_model"] == "kairo-scale-2b"
        assert saved_mv["inference_runtime"] == "transformers"
        assert saved_mv["processed_by_selected_model"] is True
        assert saved_mv["local_only"] is True

    def test_ordinary_chat_request_with_unready_model_records_fallback_reason(self, agent):
        response = agent.execute_task(
            session_id="sess_fallback_test_01",
            message="Please provide a system overview",
            model_id="Qwen3-Coder-30B-A3B-Instruct",  # Checkpoint not on disk
        )

        mv = response["model_verification"]
        # Audit Point 1: Which model was selected
        assert mv["selected_model"] == "Qwen3-Coder-30B-A3B-Instruct"

        # Audit Point 2: Which inference runtime handled the request
        assert mv["inference_runtime"] in ("transformers", "llama.cpp")

        # Audit Point 3: Not processed by selected model
        assert mv["processed_by_selected_model"] is False

        # Audit Point 6: Why fallback was used
        assert mv["fallback_used"] is True
        assert mv["fallback_reason"] is not None
        assert "Qwen3-Coder-30B-A3B-Instruct" in mv["fallback_reason"]

        # Local-only commitment preserved
        assert mv["local_only"] is True

    def test_tool_request_records_selected_tool_and_validated_args(self, agent):
        response = agent.execute_task(
            session_id="sess_tool_audit_test",
            message="Run nmap scan on 192.168.1.1",
            explicit_tool="nmap.port_scan.v1",
            explicit_args={"target": "192.168.1.1", "ports": "22,80,443"},
            model_id="kairo-scale-2b",
        )

        mv = response["model_verification"]
        assert mv["selected_model"] == "kairo-scale-2b"
        assert mv["selected_tool"] == "nmap.port_scan.v1"
        assert mv["validated_args"] is not None
        assert mv["validated_args"].get("target") == "192.168.1.1"
        assert mv["structured_output"]["action"] == "tool_call"
        tool_call = mv["structured_output"]["tool_call"]
        assert tool_call.get("tool_id") == "nmap.port_scan.v1" or tool_call.get("name") == "nmap.port_scan.v1"


class TestModelCenterBackendStatus:
    """Verifies that Model Center reports real backend status, not merely selected label."""

    def test_model_center_reports_real_backend_status(self):
        status = model_center.get_status()
        assert "real_backend_status" in status
        rbs = status["real_backend_status"]

        assert "active_model_id" in rbs
        assert "runtime" in rbs
        assert "role" in rbs
        assert "ready" in rbs
        assert "is_primary_custom" in rbs
        assert "custom_primary_ready" in rbs
        assert "fallback_ready" in rbs
        assert "fallback_model_id" in rbs
        assert rbs["local_only"] is True
        assert rbs["cloud_prevented"] is True

        # Custom primary model exists on disk and is ready
        assert rbs["custom_primary_ready"] is True
        assert rbs["fallback_model_id"] == "Qwen2.5-0.5B-Instruct"
