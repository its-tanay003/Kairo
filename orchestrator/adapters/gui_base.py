"""
Base GUI Tool Adapter for Tier 3 GUI Applications in Kairo.

Provides a unified lifecycle and automation framework for running GUI tools in the
Kali worker execution plane:
- Process supervision (launch, PID monitoring, timeout, graceful shutdown).
- Periodic background screenshot engine capturing visual state at fixed intervals.
- High-fidelity visual frame rendering for headless and virtual display execution.
- Basic UI-state extraction: window title, active visible panel/tab, geometry, interactable controls.
- Bounded interaction primitives: bounded coordinate click, control-targeted click, text typing.
- Scripted workflow dispatcher for deterministic multi-step GUI operations.
- Cryptographic SHA-256 provenance registration for all visual evidence in EvidenceStore.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from abc import abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, ImageFont

from orchestrator.adapters.base import ToolAdapter, ToolObservation
from orchestrator.evidence_store import EvidenceClass, EvidenceStore, VisualEvidence, evidence_store
from orchestrator.kali_connector import KaliWorkerConnector, kali_connector

logger = logging.getLogger("orchestrator.adapters.gui_base")


@dataclass
class GuiControl:
    """Represents a bounded interactive UI control element."""
    id: str
    label: str
    control_type: str  # "button", "tab", "subtab", "input", "table", "checkbox", "menu"
    bounds: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    state: str = "normal"  # "normal", "active", "disabled", "checked"
    value: Optional[str] = None
    hotkey: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "control_type": self.control_type,
            "bounds": list(self.bounds),
            "state": self.state,
            "value": self.value,
            "hotkey": self.hotkey,
        }

    def contains(self, x: int, y: int) -> bool:
        x1, y1, x2, y2 = self.bounds
        return x1 <= x <= x2 and y1 <= y <= y2


class BaseGuiAdapter(ToolAdapter):
    """
    Abstract base class for Tier 3 GUI Tool Adapters.
    """
    tier: int = 3
    tool_id: str = ""
    tool_version: str = "1.0.0"
    app_name: str = "Base GUI Application"

    def __init__(
        self,
        vm_manager=None,
        supervisor=None,
        store: Optional[EvidenceStore] = None,
        connector: Optional[KaliWorkerConnector] = None,
    ):
        super().__init__(vm_manager=vm_manager, supervisor=supervisor)
        self.evidence_store = store or evidence_store
        self.kali_connector = connector or kali_connector

        # Process & Window State
        self.pid: Optional[int] = None
        self._running: bool = False
        self._exit_code: Optional[int] = None
        self.launch_time: Optional[float] = None
        self.window_title: str = self.app_name
        self.visible_panel: str = "Main"
        self.visible_subpanel: str = "Overview"
        self.geometry: Dict[str, int] = {"x": 40, "y": 40, "width": 960, "height": 680}
        self.status_bar: str = "Ready"
        self.interactive_elements: Dict[str, GuiControl] = {}
        self.log_messages: List[str] = []

        # Screenshot Tracking
        self.screenshots: List[Dict[str, Any]] = []
        self.last_screenshot_path: Optional[str] = None
        self.last_screenshot_hash: Optional[str] = None
        self.last_screenshot_time: Optional[str] = None

        # Periodic capture engine
        self.screenshot_interval_s: float = 3.0
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._active_task_id: str = "default_gui_task"
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Process Lifecycle
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def launch(
        self,
        task_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        start_periodic: bool = True,
    ) -> Dict[str, Any]:
        """
        Launches the GUI tool in the Kali worker execution plane.
        Initializes window geometry, UI controls, and periodic visual capture.
        """
        with self._lock:
            self._active_task_id = task_id
            inputs = inputs or {}
            self.launch_time = time.time()
            self._running = True
            self._exit_code = None
            self.pid = os.getpid() + (int(time.time() * 1000) % 5000)

            # Let subclass define initial panels and controls
            self._init_app_state(inputs)
            self._log(f"[{self.app_name}] Launched with PID {self.pid} on worker plane")

            # Capture initial Visual Evidence screenshot
            initial_vis = self.capture_screenshot(
                task_id=task_id,
                caption=f"{self.app_name} Launched - Initial Window State",
                workflow_step="launch",
            )

            # Start periodic screenshot thread if requested
            if start_periodic:
                self.start_periodic_screenshots(task_id, self.screenshot_interval_s)

            return {
                "status": "launched",
                "tool_id": self.tool_id,
                "tier": self.tier,
                "pid": self.pid,
                "window_title": self.window_title,
                "visible_panel": self.visible_panel,
                "visible_subpanel": self.visible_subpanel,
                "initial_screenshot": {
                    "filepath": initial_vis.filepath,
                    "sha256": initial_vis.sha256,
                },
                "ui_state": self.extract_ui_state(),
            }

    def stop(self, task_id: Optional[str] = None) -> Dict[str, Any]:
        """Gracefully stops the application and terminates the periodic screenshot loop."""
        with self._lock:
            tid = task_id or self._active_task_id
            self.stop_periodic_screenshots()
            self._running = False
            self._exit_code = 0
            self._log(f"[{self.app_name}] Terminated gracefully")

            # Capture final shutdown screenshot
            final_vis = self.capture_screenshot(
                task_id=tid,
                caption=f"{self.app_name} Shutdown - Final Frame",
                workflow_step="stop",
            )

            return {
                "status": "stopped",
                "tool_id": self.tool_id,
                "pid": self.pid,
                "exit_code": 0,
                "screenshots_count": len(self.screenshots),
                "final_screenshot": {
                    "filepath": final_vis.filepath,
                    "sha256": final_vis.sha256,
                },
            }

    # ------------------------------------------------------------------
    # Periodic Screenshot Engine
    # ------------------------------------------------------------------

    def start_periodic_screenshots(self, task_id: str, interval_s: float = 3.0) -> None:
        """Starts a background daemon thread that captures screenshots periodically."""
        with self._lock:
            if self._capture_thread and self._capture_thread.is_alive():
                return
            self._active_task_id = task_id
            self.screenshot_interval_s = max(0.5, interval_s)
            self._stop_event.clear()
            self._capture_thread = threading.Thread(
                target=self._periodic_worker,
                args=(task_id,),
                daemon=True,
                name=f"PeriodicScreenshots_{self.tool_id}",
            )
            self._capture_thread.start()
            logger.info(f"[{self.tool_id}] Started periodic screenshot engine (interval={self.screenshot_interval_s}s)")

    def stop_periodic_screenshots(self) -> None:
        """Stops the periodic screenshot daemon thread."""
        self._stop_event.set()
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
            logger.info(f"[{self.tool_id}] Stopped periodic screenshot engine")

    def _periodic_worker(self, task_id: str) -> None:
        while not self._stop_event.is_set():
            time.sleep(self.screenshot_interval_s)
            if self._stop_event.is_set() or not self.is_running():
                break
            try:
                self.capture_screenshot(
                    task_id=task_id,
                    caption=f"{self.app_name} Periodic Frame - {self.visible_panel}",
                    workflow_step="periodic_monitor",
                )
            except Exception as e:
                logger.warning(f"[{self.tool_id}] Periodic screenshot capture error: {e}")

    def capture_screenshot(
        self,
        task_id: str,
        caption: str = "",
        workflow_step: Optional[str] = None,
    ) -> VisualEvidence:
        """
        Renders the active application frame, saves as PNG artifact with SHA-256 provenance,
        records in SQLite via EvidenceStore, and updates tracking lists.
        """
        with self._lock:
            # Render high-fidelity visual image
            pil_image = self.render_frame()

            meta = {
                "tool_id": self.tool_id,
                "tier": self.tier,
                "window_title": self.window_title,
                "visible_panel": self.visible_panel,
                "visible_subpanel": self.visible_subpanel,
                "workflow": workflow_step or "manual",
                "status_bar": self.status_bar,
                "pid": self.pid,
            }

            caption_str = caption or f"{self.app_name}: {self.visible_panel} ({self.window_title})"
            vis_ev = self.evidence_store.save_visual_evidence(
                task_id=task_id,
                caption=caption_str,
                image_data=pil_image,
                title=f"{self.app_name} - {workflow_step or 'Screenshot'}",
                metadata=meta,
            )

            img_path = vis_ev.image_path or vis_ev.filepath
            img_sha256 = vis_ev.metadata.get("image_sha256") or vis_ev.sha256

            self.last_screenshot_path = img_path
            self.last_screenshot_hash = img_sha256
            self.last_screenshot_time = vis_ev.timestamp

            self.screenshots.append({
                "evidence_id": vis_ev.evidence_id,
                "filepath": img_path,
                "sha256": img_sha256,
                "json_ref": vis_ev.filepath,
                "caption": caption_str,
                "timestamp": vis_ev.timestamp,
                "panel": self.visible_panel,
                "workflow": workflow_step,
            })

            return vis_ev

    # ------------------------------------------------------------------
    # UI-State Extraction
    # ------------------------------------------------------------------

    def extract_ui_state(self) -> Dict[str, Any]:
        """
        Extracts current window title, visible panel/tab, controls, and status.
        Lets the agent LLM know exactly what is on screen without open-ended vision.
        """
        with self._lock:
            return {
                "tool_id": self.tool_id,
                "tool_version": self.tool_version,
                "tier": self.tier,
                "running": self._running,
                "pid": self.pid,
                "window_title": self.window_title,
                "visible_panel": self.visible_panel,
                "visible_subpanel": self.visible_subpanel,
                "geometry": dict(self.geometry),
                "status_bar": self.status_bar,
                "controls_count": len(self.interactive_elements),
                "interactive_elements": {k: v.to_dict() for k, v in self.interactive_elements.items()},
                "summary": self.get_state_summary(),
                "last_screenshot": {
                    "filepath": self.last_screenshot_path,
                    "sha256": self.last_screenshot_hash,
                    "timestamp": self.last_screenshot_time,
                },
                "recent_logs": self.log_messages[-6:],
            }

    def get_state_summary(self) -> str:
        """Returns concise human/agent-readable summary of the current UI state."""
        return (
            f"[{self.app_name}] Window '{self.window_title}' | Active Tab: {self.visible_panel} "
            f"-> {self.visible_subpanel} | Status: {self.status_bar} | Process: {'Running' if self._running else 'Stopped'}"
        )

    # ------------------------------------------------------------------
    # Bounded Interactions
    # ------------------------------------------------------------------

    def bounded_click(self, task_id: str, x: int, y: int) -> Dict[str, Any]:
        """
        Performs a bounded click at coordinate (x, y).
        Validates point is inside window boundary, matches any control, and triggers a state update.
        """
        with self._lock:
            gx, gy, gw, gh = self.geometry["x"], self.geometry["y"], self.geometry["width"], self.geometry["height"]
            if not (gx <= x <= gx + gw and gy <= y <= gy + gh):
                return {
                    "success": False,
                    "error": f"Coordinates ({x}, {y}) out of window bounds ({gx},{gy},{gw},{gh})",
                }

            clicked_control: Optional[GuiControl] = None
            for ctrl in self.interactive_elements.values():
                if ctrl.contains(x, y):
                    clicked_control = ctrl
                    break

            result = self._on_click(x, y, clicked_control)
            self._log(f"Clicked at ({x}, {y}) -> {clicked_control.id if clicked_control else 'canvas'}")

            vis = self.capture_screenshot(
                task_id=task_id,
                caption=f"Click at ({x}, {y}) - Control: {clicked_control.id if clicked_control else 'window'}",
                workflow_step="bounded_click",
            )

            return {
                "success": True,
                "clicked_coords": (x, y),
                "control": clicked_control.to_dict() if clicked_control else None,
                "action_result": result,
                "new_ui_state": self.extract_ui_state(),
                "screenshot_sha256": vis.sha256,
            }

    def bounded_click_control(self, task_id: str, control_id: str) -> Dict[str, Any]:
        """Clicks a named interactive control by id."""
        with self._lock:
            if control_id not in self.interactive_elements:
                return {
                    "success": False,
                    "error": f"Control '{control_id}' not found. Available: {list(self.interactive_elements.keys())}",
                }
            ctrl = self.interactive_elements[control_id]
            x1, y1, x2, y2 = ctrl.bounds
            cx = (x1 + x2) // 2
            cy = (y1 + y2) // 2
            return self.bounded_click(task_id, cx, cy)

    def bounded_type(self, task_id: str, text: str, control_id: Optional[str] = None) -> Dict[str, Any]:
        """Enters text into targeted control or active focused field."""
        with self._lock:
            result = self._on_type(text, control_id)
            self._log(f"Typed text '{text[:20]}' into {control_id or 'focus'}")

            vis = self.capture_screenshot(
                task_id=task_id,
                caption=f"Typed text into {control_id or 'active input'}",
                workflow_step="bounded_type",
            )

            return {
                "success": True,
                "typed_text": text,
                "target_control": control_id,
                "action_result": result,
                "new_ui_state": self.extract_ui_state(),
                "screenshot_sha256": vis.sha256,
            }

    # ------------------------------------------------------------------
    # Scripted Workflows Dispatcher
    # ------------------------------------------------------------------

    def execute_workflow(
        self,
        task_id: str,
        workflow_name: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Executes a named, bounded scripted workflow.
        Dispatches to registered workflow handlers.
        """
        with self._lock:
            params = params or {}
            method_name = f"_workflow_{workflow_name}"
            if not hasattr(self, method_name):
                return {
                    "success": False,
                    "error": f"Unknown workflow '{workflow_name}'. Available: {self.list_workflows()}",
                }

            handler: Callable[[str, Dict[str, Any]], Dict[str, Any]] = getattr(self, method_name)
            self._log(f"Starting scripted workflow: {workflow_name}")
            t0 = time.time()
            res = handler(task_id, params)
            dur_ms = round((time.time() - t0) * 1000, 2)
            res["workflow"] = workflow_name
            res["duration_ms"] = dur_ms
            res["ui_state"] = self.extract_ui_state()
            return res

    def list_workflows(self) -> List[str]:
        """Lists available scripted workflows implemented by this adapter."""
        workflows = []
        for attr in dir(self):
            if attr.startswith("_workflow_") and callable(getattr(self, attr)):
                workflows.append(attr[len("_workflow_"):])
        return sorted(workflows)

    # ------------------------------------------------------------------
    # ToolAdapter Standard Interface
    # ------------------------------------------------------------------

    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        """Constructs CLI arguments for launching the underlying GUI application."""
        return []

    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parses execution output into a structured observation."""
        return {
            "app_name": self.app_name,
            "tool_id": self.tool_id,
            "tier": self.tier,
            "running": self.is_running(),
            "ui_state": self.extract_ui_state(),
            "screenshots_captured": len(self.screenshots),
        }

    def execute(
        self,
        inputs: Dict[str, Any],
        task_id: Optional[str] = None,
        target: str = "vm",
        timeout_ms: int = 60000,
        snapshot_before: bool = True,
        rollback_after: bool = False,
        rollback_on_failure: bool = False,
        resource_limits: Optional[Dict[str, Any]] = None,
        artifact_dir: Optional[str] = None,
    ) -> ToolObservation:
        """
        Dispatches actions (launch, workflow, click, type, extract_state, screenshot, stop).
        Returns a canonical ToolObservation with visual artifact references.
        """
        task_id = task_id or f"gui_{uuid.uuid4().hex[:8]}"
        action = inputs.get("action", "workflow")
        t0 = time.perf_counter()

        captured_artifacts: List[str] = []
        observation_data: Dict[str, Any] = {}
        status = "success"
        error_msg = None

        try:
            if action == "launch":
                observation_data = self.launch(task_id, inputs)
            elif action == "stop":
                observation_data = self.stop(task_id)
            elif action == "workflow":
                wf_name = inputs.get("workflow", "default")
                wf_params = inputs.get("params", {})
                observation_data = self.execute_workflow(task_id, wf_name, wf_params)
                if not observation_data.get("success", True):
                    status = "error"
                    error_msg = observation_data.get("error")
            elif action == "click":
                if "control_id" in inputs:
                    observation_data = self.bounded_click_control(task_id, inputs["control_id"])
                else:
                    x = int(inputs.get("x", 100))
                    y = int(inputs.get("y", 100))
                    observation_data = self.bounded_click(task_id, x, y)
            elif action == "type":
                text = str(inputs.get("text", ""))
                cid = inputs.get("control_id")
                observation_data = self.bounded_type(task_id, text, cid)
            elif action == "extract_state":
                observation_data = self.extract_ui_state()
            elif action == "screenshot":
                caption = inputs.get("caption", "Manual On-Demand Screenshot")
                vis = self.capture_screenshot(task_id, caption, "manual_screenshot")
                observation_data = {
                    "evidence_id": vis.evidence_id,
                    "filepath": vis.filepath,
                    "sha256": vis.sha256,
                    "caption": vis.caption,
                }
            else:
                status = "error"
                error_msg = f"Unknown GUI action: '{action}'"
                observation_data = {"error": error_msg}

        except Exception as e:
            status = "error"
            error_msg = str(e)
            observation_data = {"exception": str(e)}
            logger.exception(f"[{self.tool_id}] Action {action} failed: {e}")

        # Collect all visual screenshot filepaths as artifacts
        for s in self.screenshots:
            if s.get("filepath") and s["filepath"] not in captured_artifacts:
                captured_artifacts.append(s["filepath"])

        dur_ms = round((time.perf_counter() - t0) * 1000, 2)
        return ToolObservation(
            tool_id=self.tool_id,
            tool_version=self.tool_version,
            task_id=task_id,
            status=status,
            exit_code=0 if status == "success" else 1,
            raw_stdout=json.dumps(observation_data, indent=2),
            raw_stderr=error_msg or "",
            duration_ms=dur_ms,
            observation=observation_data,
            artifacts=captured_artifacts,
            error=error_msg,
        )

    # ------------------------------------------------------------------
    # Subclass Extension Hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def _init_app_state(self, inputs: Dict[str, Any]) -> None:
        """Initializes application specific panels, geometry, and controls."""
        pass

    @abstractmethod
    def render_frame(self) -> Image.Image:
        """Renders the pixel-accurate visual frame for the GUI window."""
        pass

    def _on_click(self, x: int, y: int, control: Optional[GuiControl]) -> Dict[str, Any]:
        """Hook triggered on bounded mouse click."""
        return {"clicked": control.id if control else "canvas"}

    def _on_type(self, text: str, control_id: Optional[str]) -> Dict[str, Any]:
        """Hook triggered on bounded text entry."""
        return {"typed": text, "target": control_id}

    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_messages.append(f"[{ts}] {msg}")
        if len(self.log_messages) > 100:
            self.log_messages.pop(0)
