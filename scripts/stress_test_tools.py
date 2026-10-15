import urllib.request
import urllib.error
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8000"

TEST_CASES = [
    # 1. Nmap
    {
        "name": "nmap_standard",
        "tool": "nmap.scan.v1",
        "args": {"target": "127.0.0.1", "ports": "80,443", "scan_type": "sT", "timing": 4},
        "goal": "Scan 127.0.0.1 with nmap",
    },
    {
        "name": "nmap_edge_malformed",
        "tool": "nmap.scan.v1",
        "args": {"target": "invalid_host_that_does_not_exist_xyz.test", "ports": "80"},
        "goal": "Scan invalid host with nmap",
    },
    # 2. Metasploit
    {
        "name": "metasploit_portscan",
        "tool": "metasploit.rpc.v1",
        "args": {"module": "auxiliary/scanner/portscan/tcp", "rhosts": "127.0.0.1", "rport": "8000"},
        "goal": "Scan ports with metasploit",
    },
    {
        "name": "metasploit_invalid_module",
        "tool": "metasploit.rpc.v1",
        "args": {"module": "auxiliary/does/not/exist", "rhosts": "127.0.0.1"},
        "goal": "Run invalid metasploit module",
    },
    # 3. Gobuster
    {
        "name": "gobuster_standard",
        "tool": "gobuster.dir.v1",
        "args": {"url": "http://127.0.0.1:8000", "wordlist": "/usr/share/wordlists/dirb/common.txt"},
        "goal": "Enumerate directories on http://127.0.0.1:8000 with gobuster",
    },
    {
        "name": "gobuster_unreachable",
        "tool": "gobuster.dir.v1",
        "args": {"url": "http://127.0.0.1:59999", "wordlist": "/nonexistent/wordlist.txt"},
        "goal": "Run gobuster on unreachable port",
    },
    # 4. Ffuf
    {
        "name": "ffuf_standard",
        "tool": "ffuf.fuzz.v1",
        "args": {"url": "http://127.0.0.1:8000/FUZZ", "wordlist": "/usr/share/wordlists/dirb/common.txt"},
        "goal": "Fuzz endpoints on http://127.0.0.1:8000 with ffuf",
    },
    {
        "name": "ffuf_unreachable",
        "tool": "ffuf.fuzz.v1",
        "args": {"url": "http://127.0.0.1:59999/FUZZ", "wordlist": "/usr/share/wordlists/dirb/common.txt"},
        "goal": "Fuzz unreachable port with ffuf",
    },
    # 5. Nikto
    {
        "name": "nikto_standard",
        "tool": "nikto.scan.v1",
        "args": {"target": "127.0.0.1", "port": 8000},
        "goal": "Audit web server on 127.0.0.1:8000 with nikto",
    },
    {
        "name": "nikto_unreachable",
        "tool": "nikto.scan.v1",
        "args": {"target": "target.local", "port": 80},
        "goal": "Audit target.local with nikto",
    },
    # 6. WhatWeb
    {
        "name": "whatweb_standard",
        "tool": "whatweb.scan.v1",
        "args": {"url": "http://127.0.0.1:8000"},
        "goal": "Fingerprint technologies on http://127.0.0.1:8000 with whatweb",
    },
    {
        "name": "whatweb_unreachable",
        "tool": "whatweb.scan.v1",
        "args": {"url": "http://127.0.0.1:59999"},
        "goal": "Fingerprint unreachable port with whatweb",
    },
    # 7. Sqlmap
    {
        "name": "sqlmap_standard",
        "tool": "sqlmap.scan.v1",
        "args": {"url": "http://127.0.0.1:8000/api/v1/health?id=1", "batch": True},
        "goal": "Test SQL injection on http://127.0.0.1:8000 with sqlmap",
    },
    {
        "name": "sqlmap_unreachable",
        "tool": "sqlmap.scan.v1",
        "args": {"url": "http://127.0.0.1:59999/test?id=1", "batch": True},
        "goal": "Test SQL injection on unreachable port with sqlmap",
    },
    # 8. Hydra
    {
        "name": "hydra_standard",
        "tool": "hydra.brute.v1",
        "args": {"target": "127.0.0.1", "protocol": "ssh", "username": "testuser", "wordlist": "/usr/share/wordlists/dirb/common.txt"},
        "goal": "Brute-force SSH on 127.0.0.1 with hydra",
    },
    {
        "name": "hydra_empty_inputs",
        "tool": "hydra.brute.v1",
        "args": {"target": "127.0.0.1"},
        "goal": "Run hydra with minimal inputs",
    },
    # 9. SearchSploit
    {
        "name": "searchsploit_standard",
        "tool": "searchsploit.search.v1",
        "args": {"query": "Apache 2.4", "json_output": True},
        "goal": "Search exploits for Apache 2.4 with searchsploit",
    },
    {
        "name": "searchsploit_empty",
        "tool": "searchsploit.search.v1",
        "args": {"query": "nonexistent_exploit_query_xyz_12345"},
        "goal": "Search non-existent exploit query",
    },
    # 10. Whois
    {
        "name": "whois_standard",
        "tool": "whois.lookup.v1",
        "args": {"target": "127.0.0.1"},
        "goal": "Lookup whois for 127.0.0.1",
    },
    {
        "name": "whois_edge",
        "tool": "whois.lookup.v1",
        "args": {"target": "invalid..domain..format"},
        "goal": "Lookup whois for malformed domain",
    },
    # 11. Dig
    {
        "name": "dig_standard",
        "tool": "dig.lookup.v1",
        "args": {"target": "localhost", "record_type": "A"},
        "goal": "DNS lookup for localhost with dig",
    },
    {
        "name": "dig_edge",
        "tool": "dig.lookup.v1",
        "args": {"target": "invalid_domain_that_does_not_exist_xyz.com", "record_type": "AAAA"},
        "goal": "DNS lookup for non-existent domain with dig",
    },
    # 12. Dnsenum
    {
        "name": "dnsenum_standard",
        "tool": "dnsenum.enum.v1",
        "args": {"target": "localhost", "noreverse": True},
        "goal": "DNS enumeration for localhost with dnsenum",
    },
    {
        "name": "dnsenum_edge",
        "tool": "dnsenum.enum.v1",
        "args": {"target": "target.local", "noreverse": True},
        "goal": "DNS enumeration for target.local with dnsenum",
    },
    # 13. Tcpdump
    {
        "name": "tcpdump_standard",
        "tool": "tcpdump.capture.v1",
        "args": {"interface": "eth0", "count": 5, "duration_s": 2},
        "goal": "Capture 5 packets on eth0 with tcpdump",
    },
    {
        "name": "tcpdump_bad_interface",
        "tool": "tcpdump.capture.v1",
        "args": {"interface": "nonexistent_iface_99", "count": 5},
        "goal": "Run tcpdump on invalid interface",
    },
    # 14. Exiftool
    {
        "name": "exiftool_standard",
        "tool": "exiftool.extract.v1",
        "args": {"file_path": "/etc/passwd"},
        "goal": "Extract metadata from /etc/passwd with exiftool",
    },
    {
        "name": "exiftool_missing_file",
        "tool": "exiftool.extract.v1",
        "args": {"file_path": "/path/to/missing/nonexistent_file.png"},
        "goal": "Extract metadata from missing file with exiftool",
    },
    # 15. Hashid
    {
        "name": "hashid_standard",
        "tool": "hashid.identify.v1",
        "args": {"hash": "5f4dcc3b5aa765d61d8327deb882cf99", "hashcat_check": True},
        "goal": "Identify MD5 hash with hashid and hashcat check",
    },
    {
        "name": "hashid_invalid",
        "tool": "hashid.identify.v1",
        "args": {"hash": "not_a_valid_hash_at_all!!"},
        "goal": "Identify non-hash string with hashid",
    },
]

def run_tests():
    print(f"=== Starting Comprehensive Tool & Resilience Suite ({len(TEST_CASES)} tests) ===")
    results = []

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] Testing {tc['name']} ({tc['tool']})...", end=" ", flush=True)
        payload = {
            "session_id": f"stress_test_{int(time.time())}_{i}",
            "message": tc["goal"],
            "explicit_tool": tc["tool"],
            "explicit_args": tc["args"],
        }
        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"{BASE_URL}/run",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                dur = round(time.time() - t0, 2)
                status_code = resp.status
                body = json.loads(resp.read().decode())
                exec_data = body.get("execution", {})
                exit_code = exec_data.get("exit_code")
                reply = body.get("reply", "")[:80].replace("\n", " ")
                
                print(f"HTTP {status_code} | Exit {exit_code} | {dur}s")
                results.append({
                    "name": tc["name"],
                    "tool": tc["tool"],
                    "http_code": status_code,
                    "exit_code": exit_code,
                    "duration": dur,
                    "status": "PASS",
                    "reply_snippet": reply,
                })
        except urllib.error.HTTPError as e:
            dur = round(time.time() - t0, 2)
            err_body = e.read().decode()[:300]
            print(f"HTTP ERROR {e.code}: {err_body}")
            results.append({
                "name": tc["name"],
                "tool": tc["tool"],
                "http_code": e.code,
                "exit_code": None,
                "duration": dur,
                "status": "FAIL_HTTP",
                "error": err_body,
            })
        except Exception as e:
            dur = round(time.time() - t0, 2)
            print(f"EXCEPTION: {type(e).__name__} - {e}")
            results.append({
                "name": tc["name"],
                "tool": tc["tool"],
                "http_code": None,
                "exit_code": None,
                "duration": dur,
                "status": "FAIL_EXCEPTION",
                "error": str(e),
            })

    # Verify server health after entire battery
    print("\n=== Checking System Health After Stress Suite ===")
    services = {
        "Orchestrator": f"{BASE_URL}/vm/status",
        "Gateway": "http://127.0.0.1:4000/health",
        "Next.js UI": "http://127.0.0.1:3005",
    }
    healthy_count = 0
    for s_name, s_url in services.items():
        try:
            with urllib.request.urlopen(s_url, timeout=5) as r:
                print(f"  {s_name}: HTTP {r.status} (HEALTHY)")
                if r.status == 200:
                    healthy_count += 1
        except Exception as e:
            print(f"  {s_name}: UNHEALTHY ({e})")

    print("\n=== Test Suite Summary ===")
    passes = sum(1 for r in results if r["status"] == "PASS")
    fails = len(results) - passes
    print(f"Total Tests: {len(results)} | Passed: {passes} | Failed: {fails}")
    
    if fails > 0:
        print("\nFailures:")
        for r in results:
            if r["status"] != "PASS":
                print(f"  - {r['name']} ({r['tool']}): {r['status']} | Error: {r.get('error')}")

if __name__ == "__main__":
    run_tests()
