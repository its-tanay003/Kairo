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

ROOT_DIR = Path(__file__).resolve().parent


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
            timeout_ms=5000,
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
