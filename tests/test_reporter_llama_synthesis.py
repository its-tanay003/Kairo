"""
Tests for Local Model (llama.cpp) Conversational Chat Reply Synthesis in Kairo.

Verifies:
1. LlamaCppClient.generate_json enforces strict JSON-schema grammar constraints.
2. reporter_templates.synthesize_agent_response wires final chat composition through llama_client.py.
3. Strict evidence context grounding: model cannot invent findings not in the evidence.
4. Schema discipline: guarantees reply, headline, security_posture, and key_takeaways.
5. Honest labeling preservation: simulation banners and host fallback banners are always prepended.
6. Resilient deterministic fallback: if llama-server is unreachable or errors, template fallback is seamless.
7. Scope contract violations remain zero-trust gatekeepers and are never bypassed.
8. Live end-to-end verification when local llama.cpp server is available.
"""

import json
from unittest.mock import MagicMock, patch
import pytest

from orchestrator.llama_client import LlamaCppClient
from orchestrator.reporter_templates import (
    synthesize_agent_response,
    synthesize_with_llama,
    get_llama_client,
    REPORTER_CHAT_REPLY_JSON_SCHEMA,
    REPORTER_SYSTEM_PROMPT,
)


class TestLlamaClientGenerateJson:
    """Tests for LlamaCppClient.generate_json structured inference method."""

    def test_generate_json_payload_structure(self):
        client = LlamaCppClient(base_url="http://127.0.0.1:8080")
        schema = {"type": "object", "properties": {"verdict": {"type": "string"}}}
        messages = [{"role": "user", "content": "Hello"}]

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"verdict": "ok"})}}]
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
            res = client.generate_json(messages, schema, temperature=0.1, timeout=5.0)
            assert res == {"verdict": "ok"}
            req = mock_urlopen.call_args[0][0]
            body = json.loads(req.data.decode("utf-8"))
            assert body["response_format"]["type"] == "json_object"
            assert body["response_format"]["schema"] == schema
            assert body["temperature"] == 0.1


class TestReporterLlamaSynthesis:
    """Tests for reporter_templates dynamic synthesis with strict evidence grounding."""

    def test_schema_structure_and_mandates(self):
        """Verifies JSON schema enforces required fields and evidence citation."""
        props = REPORTER_CHAT_REPLY_JSON_SCHEMA["properties"]
        assert "reply" in props
        assert "headline" in props
        assert "security_posture" in props
        assert "key_takeaways" in props
        assert "verified_evidence_cited" in props
        req = REPORTER_CHAT_REPLY_JSON_SCHEMA["required"]
        assert "reply" in req
        assert "headline" in req
        assert "security_posture" in req
        assert "key_takeaways" in req

    def test_system_prompt_anti_hallucination_mandate(self):
        """Verifies system prompt strictly forbids inventing findings outside evidence."""
        prompt_l = REPORTER_SYSTEM_PROMPT.lower()
        assert "must not invent" in prompt_l
        assert "evidence context" in prompt_l
        assert "hallucinate" in prompt_l
        assert "simulated" in prompt_l

    def test_synthesize_with_mocked_llama_updates_response(self):
        """When llama_client returns structured reasoning, chat reply and results are updated."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = True
        mock_client.generate_json.return_value = {
            "reply": "### 🛡️ Security Assessment for 192.168.1.50\n\nI analyzed your scan target 192.168.1.50. Port 22/tcp is listening for SSH, which requires key-based authentication.",
            "headline": "OpenSSH detected on 192.168.1.50",
            "security_posture": "Exposed SSH Management Port",
            "key_takeaways": [
                "Target 192.168.1.50 is active and responding.",
                "Port 22/tcp OpenSSH is listening.",
            ],
            "verified_evidence_cited": ["22/tcp", "192.168.1.50"],
        }

        observation = {
            "hosts": [{"ip": "192.168.1.50", "hostname": "web-srv", "ports": [{"port": 22, "protocol": "tcp", "service": "ssh"}]}],
            "hosts_found": 1,
            "open_ports": 1,
        }

        synth = synthesize_agent_response(
            user_goal="Scan 192.168.1.50 and check if SSH is exposed",
            tool_id="nmap.scan.v1",
            tool_name="Nmap Network Scanner",
            inputs={"target": "192.168.1.50", "ports": "22"},
            exit_code=0,
            stdout="Nmap scan report for web-srv (192.168.1.50)\n22/tcp open ssh\n",
            observation=observation,
            llama_client=mock_client,
            prefer_llm=True,
        )

        assert synth["synthesis_source"] == "llama_local"
        assert synth["process"]["synthesizer"] == "llama_client:json_schema"
        assert "Security Assessment for 192.168.1.50" in synth["reply"]
        assert synth["result"]["headline"] == "OpenSSH detected on 192.168.1.50"
        assert synth["result"]["security_posture"] == "Exposed SSH Management Port"
        assert len(synth["result"]["key_takeaways"]) == 2

        # Check call arguments to llama_client
        mock_client.generate_json.assert_called_once()
        call_kwargs = mock_client.generate_json.call_args[1]
        assert call_kwargs["schema"] == REPORTER_CHAT_REPLY_JSON_SCHEMA
        user_prompt_content = call_kwargs["messages"][1]["content"]
        assert "192.168.1.50" in user_prompt_content
        assert "STRICT COMPLETED EXECUTION EVIDENCE" in user_prompt_content

    def test_simulation_notice_preserved_over_llm_reply(self):
        """Simulation banner must remain at the top of the reply even with LLM synthesis."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = True
        mock_client.generate_json.return_value = {
            "reply": "Demonstration scan of target completed.",
            "headline": "Demo scan finished",
            "security_posture": "Simulated Environment",
            "key_takeaways": ["Simulated demo executed."],
        }

        synth = synthesize_agent_response(
            user_goal="Demonstrate Burp Suite scan",
            tool_id="burp.gui.v1",
            tool_name="Burp Suite Professional",
            inputs={"target": "demo.internal"},
            exit_code=0,
            stdout="[SIMULATED] Demo finished.",
            is_simulated=True,
            simulation_notice="[SIMULATED — demo mode, not a live scan]",
            llama_client=mock_client,
            prefer_llm=True,
        )

        assert synth["reply"].startswith("> ⚠️ **[SIMULATED — demo mode, not a live scan]**")
        assert "Demonstration scan of target completed." in synth["reply"]
        assert synth["process"]["is_simulated"] is True

    def test_fallback_notice_preserved_over_llm_reply(self):
        """Host fallback notice banner must remain at the top of the reply even with LLM synthesis."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = True
        mock_client.generate_json.return_value = {
            "reply": "Executed diagnostics on host machine.",
            "headline": "Host execution complete",
            "security_posture": "Host Fallback",
            "key_takeaways": ["Host fallback used."],
        }

        notice = "[HOST FALLBACK — running on host, not Kali VM]"
        synth = synthesize_agent_response(
            user_goal="Run local diagnostic",
            tool_id="shell.run.v1",
            tool_name="Shell Runner",
            inputs={"command": "dir"},
            exit_code=0,
            stdout="sample dir output",
            execution_plane="local_host_fallback",
            fallback_notice=notice,
            llama_client=mock_client,
            prefer_llm=True,
        )

        assert synth["reply"].startswith(f"> ⚠️ **{notice}**")
        assert "Executed diagnostics on host machine." in synth["reply"]
        assert synth["process"]["local_fallback"] is True

    def test_unhealthy_llama_server_graceful_template_fallback(self):
        """If llama server is down, synthesize_agent_response falls back seamlessly to deterministic templates."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = False

        synth = synthesize_agent_response(
            user_goal="Scan localhost",
            tool_id="nmap.scan.v1",
            tool_name="Nmap Network Scanner",
            inputs={"target": "127.0.0.1"},
            exit_code=0,
            stdout="Nmap scan report for localhost (127.0.0.1)\n80/tcp open http\n",
            llama_client=mock_client,
            prefer_llm=True,
        )

        assert synth["synthesis_source"] == "deterministic_template"
        assert synth["process"]["synthesizer"] == "reporter_templates:deterministic"
        assert "Network Reconnaissance Findings" in synth["reply"]
        mock_client.generate_json.assert_not_called()

    def test_llama_exception_graceful_template_fallback(self):
        """If llama.cpp throws an error/timeout, the response safely falls back without raising."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = True
        mock_client.generate_json.side_effect = RuntimeError("Connection timeout to llama.cpp")

        synth = synthesize_agent_response(
            user_goal="Scan localhost",
            tool_id="nmap.scan.v1",
            tool_name="Nmap Network Scanner",
            inputs={"target": "127.0.0.1"},
            exit_code=0,
            stdout="Nmap scan report for localhost (127.0.0.1)\n80/tcp open http\n",
            llama_client=mock_client,
            prefer_llm=True,
        )

        assert synth["synthesis_source"] == "deterministic_template"
        assert synth["process"]["synthesizer"] == "reporter_templates:deterministic"
        assert "Network Reconnaissance Findings" in synth["reply"]

    def test_scope_violation_never_delegated_to_llm(self):
        """Scope contract rejections must never be delegated to LLM to preserve zero-trust boundary."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = True

        synth = synthesize_agent_response(
            user_goal="Scan unauthorized target 8.8.8.8",
            tool_id="nmap.scan.v1",
            tool_name="Nmap Network Scanner",
            inputs={"target": "8.8.8.8"},
            exit_code=403,
            stdout="",
            stderr="TARGET_OUT_OF_SCOPE",
            is_scope_violation=True,
            scope_violation_reason="Target 8.8.8.8 is out of scope",
            llama_client=mock_client,
            prefer_llm=True,
        )

        mock_client.generate_json.assert_not_called()
        assert "Target Outside Authorized Scope Contract" in synth["reply"]
        assert synth["process"]["status"] == "rejected"

    def test_prefer_llm_false_uses_deterministic_template(self):
        """Explicit prefer_llm=False forces deterministic template even if llama is healthy."""
        mock_client = MagicMock(spec=LlamaCppClient)
        mock_client.is_healthy.return_value = True

        synth = synthesize_agent_response(
            user_goal="Scan localhost",
            tool_id="nmap.scan.v1",
            tool_name="Nmap Network Scanner",
            inputs={"target": "127.0.0.1"},
            exit_code=0,
            stdout="",
            llama_client=mock_client,
            prefer_llm=False,
        )

        mock_client.generate_json.assert_not_called()
        assert synth["synthesis_source"] == "deterministic_template"

    def test_live_llama_inference_if_server_running(self):
        """
        If the local llama-server is currently active on localhost:8080,
        verify live end-to-end constrained synthesis.
        """
        client = get_llama_client()
        if not client.is_healthy():
            pytest.skip("llama-server is not running on 127.0.0.1:8080; skipping live test")

        res = synthesize_agent_response(
            user_goal="Scan local router 192.168.1.1 for open ports",
            tool_id="nmap.scan.v1",
            tool_name="Nmap Network Scanner",
            inputs={"target": "192.168.1.1", "ports": "80,443"},
            exit_code=0,
            stdout="Nmap scan report for router.local (192.168.1.1)\n80/tcp open http\n443/tcp open ssl/https\n",
            observation={
                "hosts": [{"ip": "192.168.1.1", "ports": [{"port": 80, "service": "http"}, {"port": 443, "service": "https"}]}],
                "hosts_found": 1,
                "open_ports": 2,
            },
            llama_client=client,
            prefer_llm=True,
        )

        assert res["synthesis_source"] == "llama_local"
        assert res["process"]["synthesizer"] == "llama_client:json_schema"
        assert isinstance(res["reply"], str)
        assert len(res["reply"]) > 20
        assert "headline" in res["result"]
        assert "security_posture" in res["result"]
        assert isinstance(res["result"]["key_takeaways"], list)
