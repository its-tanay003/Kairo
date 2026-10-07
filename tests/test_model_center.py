"""
Test Model Center configuration, system resource detection (VRAM/RAM), and API endpoint.
"""

from pathlib import Path
import sys
import requests

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from orchestrator.model_center import model_center


def test_model_center_unit():
    print("[1/3] Testing ModelCenter unit logic...")
    status = model_center.get_status()
    print(f"Loaded Active Model: {status['model_id']}")
    print(f"Runtime: {status['runtime']}")
    print(f"Quantization: {status['quantization']}")
    print(f"Context Length: {status['context_length']}")
    print(f"Role: {status['role']}")
    print(f"VRAM: {status['vram']}")
    print(f"RAM: {status['ram']}")
    print(f"Server Status: {status['server_status']}")

    assert status["model_id"] == "Qwen3-Coder-30B-A3B-Instruct"
    assert status["runtime"] == "llama.cpp"
    assert status["quantization"] == "Q4_K_M"
    assert status["context_length"] == 32768
    assert status["role"] == "primary"
    assert "total_mb" in status["vram"]
    assert "total_mb" in status["ram"]

    fallback = next((m for m in status["models_catalog"] if m.get("role") == "fallback"), None)
    assert fallback is not None, "Missing fallback model in models_catalog"
    assert fallback["model_id"] == "Qwen2.5-0.5B-Instruct"
    print("PASS: ModelCenter unit tests passed.")


def test_model_center_endpoints():
    print("[2/3] Testing Orchestrator /model-center endpoint...")
    orch_res = requests.get("http://127.0.0.1:8000/model-center", timeout=3.0)
    assert orch_res.status_code == 200, f"Orchestrator returned {orch_res.status_code}: {orch_res.text}"
    orch_data = orch_res.json()
    assert orch_data["model_id"] == "Qwen3-Coder-30B-A3B-Instruct"
    assert "vram" in orch_data
    assert "ram" in orch_data
    print(f"PASS: Orchestrator /model-center returned 200: {orch_data['model_id']}")

    print("[3/3] Testing Gateway /model-center endpoint...")
    gw_res = requests.get("http://127.0.0.1:4000/model-center", timeout=3.0)
    assert gw_res.status_code == 200, f"Gateway returned {gw_res.status_code}: {gw_res.text}"
    gw_data = gw_res.json()
    assert gw_data["model_id"] == "Qwen3-Coder-30B-A3B-Instruct"
    print(f"PASS: Gateway /model-center proxy returned 200: {gw_data['model_id']}")


def test_model_center_websocket():
    import asyncio
    import json
    import websockets

    async def _test():
        print("[4/4] Testing Gateway WebSocket get_model_center message...")
        async with websockets.connect("ws://127.0.0.1:4000") as ws:
            handshake = await ws.recv()
            await ws.send(json.dumps({"type": "get_model_center"}))
            msg = await ws.recv()
            data = json.loads(msg)
            assert data["type"] == "model_center_status"
            assert data["data"]["model_id"] == "Qwen3-Coder-30B-A3B-Instruct"
            assert "vram" in data["data"]
            assert "ram" in data["data"]
            print(f"PASS: WebSocket received model_center_status for {data['data']['model_id']}")

    asyncio.run(_test())


if __name__ == "__main__":
    test_model_center_unit()
    test_model_center_endpoints()
    test_model_center_websocket()
    print("ALL MODEL CENTER TESTS (UNIT + HTTP + WS) PASSED SUCCESSFULLY!")
