"""
Process manager for llama.cpp server mode.
Allows starting, stopping, and verifying the local llama-server instance.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
import urllib.request

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = ROOT_DIR / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"


def find_llama_server_binary() -> Optional[str]:
    # 1. Environment override
    if "LLAMA_SERVER_BIN" in os.environ and os.path.exists(os.environ["LLAMA_SERVER_BIN"]):
        return os.environ["LLAMA_SERVER_BIN"]

    # 2. Check PATH
    which_path = shutil.which("llama-server")
    if which_path:
        return which_path

    # 3. Check common WinGet package location
    winget_pkg_dir = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget_pkg_dir.exists():
        for exe in winget_pkg_dir.glob("**/llama-server.exe"):
            if exe.is_file():
                return str(exe)

    return None


class LlamaServerManager:
    def __init__(
        self,
        model_path: Optional[Path | str] = None,
        port: int = 8080,
        host: str = "127.0.0.1",
        gpu_layers: int = 99,
        ctx_size: int = 2048,
    ):
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL
        self.port = port
        self.host = host
        self.gpu_layers = gpu_layers
        self.ctx_size = ctx_size
        self.server_bin = find_llama_server_binary()
        self.process: Optional[subprocess.Popen] = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def is_running(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def start(self, wait_seconds: int = 15) -> bool:
        if self.is_running():
            return True

        if not self.server_bin:
            raise FileNotFoundError("Could not locate llama-server executable.")

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found at {self.model_path}")

        cmd = [
            self.server_bin,
            "-m", str(self.model_path),
            "--host", self.host,
            "--port", str(self.port),
            "-c", str(self.ctx_size),
            "-ngl", str(self.gpu_layers),
        ]

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        # Wait for server to become healthy
        start_time = time.time()
        while time.time() - start_time < wait_seconds:
            if self.is_running():
                return True
            time.sleep(0.5)

        return self.is_running()

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
