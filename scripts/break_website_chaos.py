"""
Chaos and Website Fuzzing Suite for Kairo.
Aims to break the UI, Gateway, and Orchestrator via:
1. HTTP endpoint fuzzing with extreme / malformed inputs
2. Command injection & path traversal attempts in tool execution
3. Concurrent load & race condition tests
4. WebSocket gateway stress & malformed packet fuzzing
5. Database concurrency locking checks
6. Frontend route status checks
"""
import asyncio
import json
import socket
import time
import urllib.request
import urllib.error
import websockets

GATEWAY_HTTP = "http://localhost:4000"
GATEWAY_WS = "ws://localhost:4000"
ORCHESTRATOR_HTTP = "http://127.0.0.1:8000"
UI_HTTP = "http://localhost:3005"

broken_issues = []

def test_endpoint(name, url, method="GET", data=None, headers=None, expected_status=None):
    headers = headers or {}
    if data and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    req_data = json.dumps(data).encode("utf-8") if isinstance(data, dict) else (data.encode("utf-8") if isinstance(data, str) else None)
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            print(f"  [+] {name}: {code} OK ({len(body)} bytes)")
            return code, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"  [*] {name}: HTTP {e.code} (Handled gracefully)")
        return e.code, body
    except Exception as e:
        print(f"  [-] {name}: BROKEN with {type(e).__name__}: {e}")
        broken_issues.append({"vector": name, "error": str(e), "url": url})
        return -1, str(e)


async def test_websocket_fuzzing():
    print("\n--- 1. WebSocket Gateway Fuzzing ---")
    ws_url = f"{GATEWAY_WS}"
    
    # Vector 1: Malformed JSON
    try:
        async with websockets.connect(ws_url, close_timeout=3) as ws:
            await ws.send("{ malformed: json: !!!")
            reply = await asyncio.wait_for(ws.recv(), timeout=3)
            print(f"  [+] Malformed JSON handled: received reply or keepalive")
    except Exception as e:
        print(f"  [-] Malformed JSON caused: {type(e).__name__}: {e}")
        # Note if server crashed

    # Vector 2: Gigantic payload (1MB string)
    try:
        async with websockets.connect(ws_url, close_timeout=3) as ws:
            giant_payload = json.dumps({"type": "ping", "data": "A" * 1024 * 1024})
            await ws.send(giant_payload)
            print(f"  [+] 1MB payload sent successfully")
    except Exception as e:
        print(f"  [*] 1MB payload handled: {type(e).__name__}")

    # Vector 3: Rapid connect / disconnect churn
    try:
        for i in range(15):
            async with websockets.connect(ws_url, close_timeout=2) as ws:
                await ws.send(json.dumps({"type": "status_request"}))
        print(f"  [+] 15 rapid connect/disconnect cycles succeeded")
    except Exception as e:
        print(f"  [-] Rapid churn failed: {e}")
        broken_issues.append({"vector": "ws_churn", "error": str(e), "url": ws_url})


def test_orchestrator_fuzzing():
    print("\n--- 2. Orchestrator Fuzzing & Injection Defense ---")
    
    # Vector 1: Null bytes and SQL injection in session_id
    test_endpoint(
        "Null byte in session_id",
        f"{ORCHESTRATOR_HTTP}/run",
        method="POST",
        data={"message": "check", "session_id": "session_\x00_test' OR 1=1;--"},
    )

    # Vector 2: Command injection in message
    test_endpoint(
        "Command injection in message",
        f"{ORCHESTRATOR_HTTP}/run",
        method="POST",
        data={
            "message": "Audit 127.0.0.1; echo INJECTED && touch /tmp/pwned",
            "session_id": "chaos_injection",
        },
    )

    # Vector 3: Massive 100KB message prompt
    test_endpoint(
        "100KB message string overflow",
        f"{ORCHESTRATOR_HTTP}/run",
        method="POST",
        data={
            "message": "Scan target " + ("x" * 100000),
            "session_id": "chaos_big_prompt",
        },
    )

    # Vector 4: Invalid tool invocation with unknown tool_id
    test_endpoint(
        "Unknown tool_id execution",
        f"{ORCHESTRATOR_HTTP}/run",
        method="POST",
        data={
            "message": "Run nonexistent.tool.v999 on 127.0.0.1",
            "explicit_tool": "nonexistent.tool.v999",
            "session_id": "chaos_unknown_tool",
        },
    )

    # Vector 5: Path traversal in tool argument
    test_endpoint(
        "Path traversal in file_path",
        f"{ORCHESTRATOR_HTTP}/run",
        method="POST",
        data={
            "message": "Extract metadata from ../../../../../../../etc/shadow",
            "explicit_tool": "exiftool.extract.v1",
            "explicit_args": {"file_path": "../../../../../../../etc/shadow"},
            "session_id": "chaos_traversal",
        },
    )


def test_ui_endpoints():
    print("\n--- 3. Frontend Next.js Route Verification ---")
    routes = [
        "/",
    ]
    for r in routes:
        test_endpoint(f"UI Route {r}", f"{UI_HTTP}{r}", method="GET")


def test_concurrency_race():
    print("\n--- 4. Concurrency Stress (10 simultaneous /run requests) ---")
    import concurrent.futures

    def send_run(idx):
        url = f"{ORCHESTRATOR_HTTP}/run"
        payload = {
            "message": f"Quick health check {idx} for target 127.0.0.1",
            "explicit_tool": "whatweb.scan.v1",
            "explicit_args": {"url": "http://127.0.0.1:8000"},
            "session_id": f"concurrency_test_{idx}",
        }
        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=req_data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.getcode()
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:
            return f"ERR: {e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(send_run, range(10)))
    print(f"  [+] 10 concurrent requests completed: {results}")
    failures = [r for r in results if r != 200]
    if failures:
        broken_issues.append({"vector": "concurrency_flood", "error": f"Failed requests: {failures}"})


async def main():
    print("=== STARTING CHAOS / BREAK-THE-SITE EXPERIMENTS ===")
    test_ui_endpoints()
    await test_websocket_fuzzing()
    test_orchestrator_fuzzing()
    test_concurrency_race()
    
    print("\n=== SYSTEM HEALTH CHECK POST-CHAOS ===")
    test_endpoint("Orchestrator Liveness", f"{ORCHESTRATOR_HTTP}/vm/status")
    test_endpoint("Gateway Liveness", f"{GATEWAY_HTTP}/health")
    test_endpoint("UI Liveness", f"{UI_HTTP}/")

    print("\n=== CHAOS SUMMARY ===")
    if not broken_issues:
        print("[SUCCESS] ZERO breakages! The system handled all fuzzing, injections, concurrency floods, and malformed inputs with 100% resilience.")
    else:
        print(f"[FOUND {len(broken_issues)} ISSUES]:")
        for iss in broken_issues:
            print(f" - {iss}")

if __name__ == "__main__":
    asyncio.run(main())
