"""
Base classes for all Kairo tool adapters.

Every adapter must implement:
  - build_args(inputs: dict) -> list[str]  - construct CLI args from structured inputs
  - parse(stdout: str, stderr: str, exit_code: int, meta: dict) -> dict  - produce structured observation
  - tool_id: str (class attribute)
  - tool_version: str (class attribute)

The execute() method in ToolAdapter dispatches through vm_manager or process_supervisor
depending on 'target' (vm | local) in inputs.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

logger = logging.getLogger("orchestrator.adapters.base")


@dataclass
class ToolObservation:
    """
    Normalized structured output produced by every tool adapter's parser.
    This is the canonical 'observation' JSON object stored into the event log.
    """
    tool_id: str
    tool_version: str
    task_id: str
    status: str                              # "success" | "error" | "timeout"
    exit_code: int
    raw_stdout: str
    raw_stderr: str
    duration_ms: float
    observation: Dict[str, Any]              # Tool-specific structured result
    artifacts: List[str] = field(default_factory=list)   # File paths produced
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "task_id": self.task_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "raw_stdout": self.raw_stdout,
            "raw_stderr": self.raw_stderr,
            "duration_ms": self.duration_ms,
            "observation": self.observation,
            "artifacts": self.artifacts,
            "timestamp": self.timestamp,
            "error": self.error,
        }


@dataclass
class AdapterResult:
    """Full result envelope returned by ToolAdapter.execute()"""
    observation: ToolObservation
    event_id: Optional[int] = None


class ToolAdapter(ABC):
    """Abstract base class for all tool adapters."""
    tool_id: str = ""
    tool_version: str = "1.0.0"

    def __init__(self, vm_manager=None, supervisor=None):
        from orchestrator.vm_manager import vm_manager as default_vm
        from orchestrator.process_supervisor import supervisor as default_sup
        self._vm = vm_manager or default_vm
        self._supervisor = supervisor or default_sup

    @abstractmethod
    def build_args(self, inputs: Dict[str, Any]) -> List[str]:
        """Build ordered list of CLI arguments from structured inputs dict."""
        ...

    @abstractmethod
    def parse(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Parse raw command output into structured observation dict."""
        ...

    def execute(
        self,
        inputs: Dict[str, Any],
        task_id: Optional[str] = None,
        target: str = "vm",
        timeout_ms: int = 60000,
        snapshot_before: bool = True,
    ) -> ToolObservation:
        """
        Builds args, executes (via VM or local supervisor), parses output,
        returns ToolObservation.
        """
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        args = self.build_args(inputs)
        binary = self._binary()
        cwd = inputs.get("cwd", "/home/kali")

        t0 = time.perf_counter()

        if target == "vm":
            result = self._vm.execute_in_vm(
                task_id=task_id,
                tool_id=self.tool_id,
                tool_version=self.tool_version,
                args={
                    "command": binary,
                    "args": args,
                    "cwd": cwd,
                },
                snapshot_before=snapshot_before,
                timeout_ms=timeout_ms,
            )
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            exit_code = result.get("exit_code", -1)
            timed_out = result.get("timed_out", False)
            duration_ms = result.get("duration_ms", round((time.perf_counter() - t0) * 1000, 2))
        else:
            from orchestrator.process_supervisor import ProcessResult
            proc: ProcessResult = self._supervisor.execute(
                task_id=task_id,
                command=binary,
                args=args,
                timeout_ms=timeout_ms,
                cwd=cwd if os.path.exists(cwd) else None,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.exit_code
            timed_out = proc.timed_out
            duration_ms = proc.duration_ms

        if timed_out:
            status = "timeout"
        elif exit_code == 0:
            status = "success"
        else:
            status = "error"

        meta = {
            "inputs": inputs,
            "args": args,
            "binary": binary,
            "target": target,
            "timed_out": timed_out,
        }

        try:
            observation = self.parse(stdout, stderr, exit_code, meta)
        except Exception as e:
            logger.error(f"[{self.tool_id}] Parser failed: {e}")
            observation = {"parse_error": str(e), "raw": stdout[:2000]}

        artifacts = observation.pop("_artifacts", [])

        return ToolObservation(
            tool_id=self.tool_id,
            tool_version=self.tool_version,
            task_id=task_id,
            status=status,
            exit_code=exit_code,
            raw_stdout=stdout,
            raw_stderr=stderr,
            duration_ms=duration_ms,
            observation=observation,
            artifacts=artifacts,
            error=stderr.strip() if status == "error" else None,
        )

    def _binary(self) -> str:
        """Return the tool binary from the spec or a sensible default."""
        return self.tool_id.split(".")[0]
