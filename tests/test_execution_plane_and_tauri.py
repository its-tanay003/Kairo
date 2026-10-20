"""
Unit and integration tests for Local Execution Plane Detection,
Kali Worker Connection Layer (Linux, Windows WSL2, macOS Virtualization),
and Tauri Desktop Shell Packaging.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from orchestrator.kali_connector import (
    KaliWorkerConnector,
    ExecutionPlaneType,
    ExecutionPlaneInfo,
    WinKexStatus,
    get_kali_connector,
)
from orchestrator.vm_manager import vm_manager

ROOT_DIR = Path(__file__).resolve().parent.parent
import sys
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


class TestKaliExecutionPlaneDetection(unittest.TestCase):
    """Verifies that the Kali worker connection layer branches appropriately across OS platforms."""

    def test_singleton_connector_exists(self):
        connector = get_kali_connector()
        self.assertIsNotNone(connector)
        status = connector.get_status()
        self.assertIn("plane_type", status)
        self.assertIn("backend_name", status)
        self.assertIn("is_connected", status)
        self.assertIn("host_os", status)

    def test_windows_wsl2_plane_detection(self):
        connector = KaliWorkerConnector(force_plane=ExecutionPlaneType.WINDOWS_WSL2)
        status = connector.get_status(force_refresh=True)

        self.assertEqual(status["plane_type"], ExecutionPlaneType.WINDOWS_WSL2.value)
        self.assertIn("WSL2", status["backend_name"])
        self.assertIsNotNone(status["wsl_version"])
        self.assertEqual(status["wsl_version"], 2)
        self.assertIn("win_kex", status)
        self.assertIsInstance(status["win_kex"], dict)
        self.assertIn("ready_for_phase5_gui", status["win_kex"])

    def test_linux_native_plane_detection(self):
        connector = KaliWorkerConnector(force_plane=ExecutionPlaneType.LINUX_NATIVE)
        status = connector.get_status(force_refresh=True)

        self.assertEqual(status["plane_type"], ExecutionPlaneType.LINUX_NATIVE.value)
        self.assertIn("Native", status["backend_name"])
        self.assertTrue(status["is_connected"])

    def test_macos_virtualization_plane_detection(self):
        connector = KaliWorkerConnector(force_plane=ExecutionPlaneType.MACOS_VIRTUALIZATION)
        status = connector.get_status(force_refresh=True)

        self.assertEqual(status["plane_type"], ExecutionPlaneType.MACOS_VIRTUALIZATION.value)
        self.assertIn("Virtualization", status["backend_name"])
        self.assertTrue(status["is_connected"])

    def test_transparent_execution_interface_uniform_keys(self):
        """Verifies that calling execute() returns the exact same structured envelope."""
        connector = get_kali_connector()
        res = connector.execute(
            task_id="test_uniform_01",
            command="echo",
            args=["hello_kairo_plane"],
            timeout_ms=15000,
        )

        expected_keys = {
            "task_id", "status", "exit_code", "stdout", "stderr",
            "duration_ms", "execution_plane", "timed_out", "artifacts"
        }
        for k in expected_keys:
            self.assertIn(k, res, f"Result must contain key '{k}' regardless of platform.")

        self.assertEqual(res["task_id"], "test_uniform_01")
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("hello_kairo_plane", res["stdout"])

    def test_vm_manager_integration(self):
        """Verifies that VMManager incorporates execution_plane status transparently."""
        vm_status = vm_manager.get_status()
        self.assertIn("execution_plane", vm_status)
        plane = vm_status["execution_plane"]
        self.assertIn("backend_name", plane)
        self.assertIn("plane_type", plane)
        self.assertTrue(vm_status["running"])

    def test_local_host_fallback_enum_and_notice(self):
        """Verifies ExecutionPlaneType includes LOCAL_HOST_FALLBACK with value 'local_host_fallback'."""
        self.assertEqual(ExecutionPlaneType.LOCAL_HOST_FALLBACK.value, "local_host_fallback")
        self.assertIn("local_host_fallback", [e.value for e in ExecutionPlaneType])

    def test_execute_linux_native_tags_local_host_fallback_and_notice(self):
        """
        When _execute_linux_native fires because no isolated Kali VM/worker is reachable,
        it must tag execution_plane as 'local_host_fallback' and provide the plain-language notice.
        """
        from unittest.mock import patch, MagicMock
        connector = KaliWorkerConnector()
        with patch("subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "fallback output"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            res = connector._execute_linux_native(
                task_id="task_fallback_01",
                command="echo",
                args=["testing_fallback"],
                cwd="/home/kali",
                timeout_ms=5000,
            )

            self.assertEqual(res["execution_plane"], ExecutionPlaneType.LOCAL_HOST_FALLBACK.value)
            self.assertEqual(res["execution_plane"], "local_host_fallback")
            self.assertEqual(res["fallback_notice"], "Ran directly on this machine — no isolated Kali worker was available.")
            self.assertTrue(res["local_fallback"])

    def test_claude_synthesis_surfaces_fallback_notice_in_reply_and_tool_card(self):
        """
        Verifies that synthesize_agent_response injects the visible warning banner in chat reply
        and process metadata when running on local_host_fallback.
        """
        from orchestrator.claude_synthesis import synthesize_agent_response
        synth = synthesize_agent_response(
            user_goal="Test host fallback behavior",
            tool_id="shell.run.v1",
            tool_name="Shell Command",
            inputs={"command": "whoami"},
            exit_code=0,
            stdout="hp",
            stderr="",
            execution_plane="local_host_fallback",
            fallback_notice="Ran directly on this machine — no isolated Kali worker was available.",
        )

        self.assertIn("Ran directly on this machine — no isolated Kali worker was available.", synth["reply"])
        self.assertTrue(synth["reply"].startswith("> ⚠️ **Ran directly on this machine — no isolated Kali worker was available.**"))
        self.assertEqual(synth["process"]["execution_plane"], "local_host_fallback")
        self.assertEqual(synth["process"]["fallback_notice"], "Ran directly on this machine — no isolated Kali worker was available.")
        self.assertTrue(synth["process"]["local_fallback"])
        metrics = synth["output"]["summary_metrics"]
        self.assertTrue(any(m["label"] == "Execution Plane" and "Host Fallback" in m["value"] for m in metrics))

    def test_agent_records_local_host_fallback_event(self):
        """
        Verifies that AgentLoop._execute_single_tool records execution_plane: 'local_host_fallback'
        in the SQLite event network_context and returns the notice.
        """
        import time
        from unittest.mock import patch, MagicMock
        from orchestrator.agent import AgentLoop
        from events.db import init_db

        temp_db = ROOT_DIR / "temp_fallback_test.db"
        try:
            init_db(temp_db)
            agent = AgentLoop(db_path=temp_db)

            # Mock vm_manager to return fallback plane
            with patch("orchestrator.agent.vm_manager.execute_in_vm") as mock_exec:
                mock_exec.return_value = {
                    "task_id": "task_fb_test",
                    "status": "success",
                    "exit_code": 0,
                    "stdout": "host executed",
                    "stderr": "",
                    "duration_ms": 15,
                    "execution_plane": "local_host_fallback",
                    "fallback_notice": "Ran directly on this machine — no isolated Kali worker was available.",
                    "local_fallback": True,
                }

                mock_record = MagicMock(
                    selected_model="test_model",
                    actual_model_id="test_model",
                    inference_runtime="llama_cpp",
                    processed_by_selected_model=True,
                    structured_output={},
                    fallback_used=False,
                    fallback_reason=None,
                )
                mock_record.to_dict.return_value = {"model_id": "test_model"}

                res = agent._execute_single_tool(
                    session_id="sess_fb_01",
                    task_id="task_fb_test",
                    tool_id="kali.exec.v1",
                    requested_args={"command": "whoami", "workflow_token": "KAIRO-WF-APPROVED"},
                    active_model_info={"model_id": "test_model", "role": "primary"},
                    exec_record=mock_record,
                    message="run host tool",
                    t0=time.time(),
                    start_time_iso="2026-10-20T12:00:00Z",
                    parent_event=None,
                    plan_id=None,
                    node_id=None,
                )

                self.assertEqual(res["execution_plane"], "local_host_fallback")
                self.assertIn("Ran directly on this machine — no isolated Kali worker was available.", res["reply"])

                # Inspect SQLite event
                import sqlite3
                conn = sqlite3.connect(temp_db)
                row = conn.execute("SELECT network_context FROM events WHERE task_id = 'task_fb_test'").fetchone()
                conn.close()
                self.assertIsNotNone(row)
                net_ctx = json.loads(row[0])
                self.assertEqual(net_ctx["execution_plane"], "local_host_fallback")
                self.assertEqual(net_ctx["fallback_notice"], "Ran directly on this machine — no isolated Kali worker was available.")
                self.assertTrue(net_ctx["local_fallback"])
        finally:
            if temp_db.exists():
                try:
                    temp_db.unlink()
                except Exception:
                    pass


class TestTauriDesktopShell(unittest.TestCase):
    """Verifies that the Next.js UI is properly wrapped in a Tauri desktop shell."""

    def setUp(self):
        self.ui_dir = ROOT_DIR / "ui"
        self.tauri_dir = self.ui_dir / "src-tauri"

    def test_tauri_cargo_manifest(self):
        cargo_toml = self.tauri_dir / "Cargo.toml"
        self.assertTrue(cargo_toml.exists(), "Cargo.toml must exist in ui/src-tauri")
        content = cargo_toml.read_text(encoding="utf-8")
        self.assertIn("name = \"kairo-desktop\"", content)
        self.assertIn("tauri = { version = \"2\"", content)
        self.assertIn("tauri-build", content)

    def test_tauri_config_json(self):
        conf_path = self.tauri_dir / "tauri.conf.json"
        self.assertTrue(conf_path.exists(), "tauri.conf.json must exist in ui/src-tauri")
        with open(conf_path, "r", encoding="utf-8") as f:
            conf = json.load(f)

        self.assertEqual(conf.get("productName"), "Kairo")
        self.assertEqual(conf.get("identifier"), "com.kairo.desktop")
        self.assertIn("build", conf)
        self.assertEqual(conf["build"]["devUrl"], "http://localhost:3000")
        self.assertEqual(conf["build"]["beforeDevCommand"], "npm run dev")
        self.assertEqual(conf["build"]["beforeBuildCommand"], "npm run build")
        self.assertIn("app", conf)
        self.assertTrue(len(conf["app"]["windows"]) > 0)
        self.assertEqual(conf["app"]["windows"][0]["title"], "Kairo Autonomous Cyber Agent")

    def test_tauri_rust_source_files(self):
        main_rs = self.tauri_dir / "src" / "main.rs"
        lib_rs = self.tauri_dir / "src" / "lib.rs"
        build_rs = self.tauri_dir / "build.rs"

        self.assertTrue(main_rs.exists(), "main.rs must exist")
        self.assertTrue(lib_rs.exists(), "lib.rs must exist")
        self.assertTrue(build_rs.exists(), "build.rs must exist")

        lib_content = lib_rs.read_text(encoding="utf-8")
        self.assertIn("tauri::Builder", lib_content)
        self.assertIn("get_shell_info", lib_content)

    def test_ui_package_json_tauri_scripts(self):
        pkg_path = self.ui_dir / "package.json"
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)

        scripts = pkg.get("scripts", {})
        self.assertIn("tauri", scripts)
        self.assertIn("tauri:dev", scripts)
        self.assertIn("tauri:build", scripts)
        self.assertEqual(scripts["tauri:dev"], "tauri dev")
        self.assertEqual(scripts["tauri:build"], "tauri build")

        dev_deps = pkg.get("devDependencies", {})
        self.assertIn("@tauri-apps/cli", dev_deps)


if __name__ == "__main__":
    unittest.main()
