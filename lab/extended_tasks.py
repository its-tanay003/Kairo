"""
Kairo Extended Benchmark Task Suite (LAB-TASK-51 to LAB-TASK-120).
Expands Kairo Lab Benchmark Suite to 120 Tasks (targeting the full 100-300 task set
per the blueprint's Evaluation Framework).

Covers all 22 registered tools across:
1. Web Application & API Vulnerabilities (SSRF, IDOR, SQLi, XSS, CSRF, CSP, Auth)
2. Network Protocol & Infrastructure Auditing (TCP/UDP, DNS, WHOIS, SSL/TLS, BPF)
3. Specialized GUI & Security Browser Automation (Burp, Wireshark, ZAP, Playwright)
4. Forensic Artifacts, Cryptography & System Integrity (EXIF, HashID, PCAP, SUID)
5. Counterfactual Anomaly Injections & Autonomous Self-Healing Recovery
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from orchestrator.evidence_store import EvidenceClass


def _build_extended_tasks() -> List[Any]:
    from lab.tasks import LabTask

    tasks: List[LabTask] = []

    # Helper template generator for diverse, deterministic tasks
    specs = [
        # (id_num, name, objective, target, capability, tool, evidence_class, spec, recovery, output, desc)
        (
            51, "Burp Suite In-Flight HTTP Request Intercept",
            "Intercept live HTTP GET /api/v1/auth/session request on 127.0.0.1:8080 and hold in proxy queue.",
            "http://127.0.0.1:8080/api/v1/auth/session", "http_interception", "burpsuite.gui.v1", EvidenceClass.VISUAL,
            {"http_method": "GET", "url": "/api/v1/auth/session", "headers": {"Host": "127.0.0.1:8080"}},
            False, {"stdout": '{"intercept_status": "holding", "in_flight_count": 1, "method": "GET", "url": "/api/v1/auth/session", "screenshot_hash": "a1b2c3d4e5"}', "exit_code": 0},
            "Validates GUI HTTP interception and visual evidence capture."
        ),
        (
            52, "Burp Suite Repeater Tampered Replay",
            "Send intercepted session token to Repeater and replay request with modified authorization cookie.",
            "http://127.0.0.1:8080/api/v1/auth/session", "packet_repeater", "burpsuite.gui.v1", EvidenceClass.COMMAND,
            {"metadata": {"replayed": True, "tampered_header": "Cookie"}},
            False, {"stdout": '{"action": "repeater_replay", "status_code": 200, "response_size": 412, "replayed": true}', "exit_code": 0},
            "Evaluates proxy repeater manipulation and request crafting."
        ),
        (
            53, "Wireshark Live Packet Interface Capture",
            "Sniff live network traffic on interface eth0 and capture TCP handshake sequence.",
            "eth0", "packet_analysis", "wireshark.gui.v1", EvidenceClass.NETWORK,
            {"metadata": {"interface": "eth0", "packets_captured": 25}},
            False, {"stdout": '{"interface": "eth0", "packets_captured": 25, "pcap_file": "/tmp/kairo_eth0.pcap", "status": "captured"}', "exit_code": 0},
            "Tests Wireshark live interface packet capture and stream extraction."
        ),
        (
            54, "Wireshark BPF Display Filter Dissection",
            "Apply BPF display filter 'tcp.port == 8888 and http' to isolate cleartext web communication.",
            "http://127.0.0.1:8888", "traffic_dissection", "wireshark.gui.v1", EvidenceClass.NETWORK,
            {"metadata": {"filter": "tcp.port == 8888", "matched_packets": 14}},
            False, {"stdout": '{"filter": "tcp.port == 8888", "matched_packets": 14, "protocols": ["TCP", "HTTP"], "status": "ok"}', "exit_code": 0},
            "Validates packet stream filtration and protocol dissection."
        ),
        (
            55, "Burp Intercept Queue Timeout Recovery",
            "Recover from proxy queue stalling when client request is held past execution deadline.",
            "http://127.0.0.1:8080/timeout", "http_interception", "burpsuite.gui.v1", EvidenceClass.VISUAL,
            {"metadata": {"recovered": True}},
            True, {
                "attempt_1": {"stdout": "Error: Intercept queue stalled after 30s timeout", "exit_code": 124},
                "attempt_2": {"stdout": '{"action": "toggle_proxy_off", "status": "forwarded", "recovered": true}', "exit_code": 0}
            },
            "Verifies self-healing recovery when proxy intercept blocks execution pipeline."
        ),
        (
            56, "ZAP Automated AJAX Spider Crawl",
            "Run OWASP ZAP AJAX spider on single page application target to crawl dynamic DOM routes.",
            "http://127.0.0.1:8888/dvwa/", "web_spider", "zap.gui.v1", EvidenceClass.NETWORK,
            {"endpoints": ["/dvwa/login.php", "/dvwa/index.php"]},
            False, {"stdout": '{"spider_status": "100%", "urls_found": ["/dvwa/login.php", "/dvwa/index.php", "/dvwa/setup.php"]}', "exit_code": 0},
            "Discovers client-side dynamic routes via headless browser crawling."
        ),
        (
            57, "ZAP Active Vulnerability Scan Policy",
            "Execute ZAP active scanner against input parameters to detect reflected Cross-Site Scripting.",
            "http://127.0.0.1:8888/dvwa/vulnerabilities/xss_r/", "web_vulnerability_scan", "zap.gui.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["Cross-Site Scripting (Reflected)"]},
            False, {"stdout": '{"alerts": [{"name": "Cross-Site Scripting (Reflected)", "risk": "High", "url": "http://127.0.0.1:8888/dvwa/vulnerabilities/xss_r/"}]}', "exit_code": 0},
            "Executes active automated DAST vulnerability scanning."
        ),
        (
            58, "Security Browser Visible DOM XSS Verification",
            "Launch visible browser, inject script payload into #name input, and record DOM alert execution.",
            "http://127.0.0.1:8888/dvwa/vulnerabilities/xss_r/?name=%3Cscript%3Ealert(1)%3C/script%3E", "browser_testing", "browser.security.v1", EvidenceClass.VISUAL,
            {"metadata": {"dom_alert_triggered": True, "selector": "#name"}},
            False, {"stdout": '{"workflow": "xss_check", "alert_triggered": true, "dialog_message": "1", "screenshot_sha256": "f0e1d2c3b4a5"}', "exit_code": 0},
            "Captures visible screenshot and DOM proof of reflected XSS execution."
        ),
        (
            59, "Security Browser Authentication Flow Audit",
            "Walkthrough web login form with valid credentials and verify session storage token persistence.",
            "http://127.0.0.1:8888/dvwa/login.php", "auth_flow_testing", "browser.security.v1", EvidenceClass.COMMAND,
            {"metadata": {"auth_success": True, "session_cookie": "PHPSESSID"}},
            False, {"stdout": '{"workflow": "auth_flow", "login_status": "authenticated", "cookies": ["PHPSESSID=e4c89f2a0b1c"], "redirect": "/dvwa/index.php"}', "exit_code": 0},
            "Performs end-to-end browser authentication state validation."
        ),
        (
            60, "Security Browser CSRF Anti-Token Missing Check",
            "Inspect sensitive state-changing password reset form for presence of CSRF synchronizer token.",
            "http://127.0.0.1:8888/dvwa/vulnerabilities/csrf/", "dom_inspection", "browser.security.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["Missing Anti-CSRF Token"]},
            False, {"stdout": '{"workflow": "csrf_audit", "form_action": "change_password", "csrf_token_present": false, "vulnerability": "Missing Anti-CSRF Token"}', "exit_code": 0},
            "Analyzes form DOM structures for cryptographic CSRF defense tokens."
        ),
        (
            61, "FFUF REST API Endpoint Enumeration",
            "Fuzz /api/v1/FUZZ endpoint using wordlist to detect unauthenticated microservice endpoints.",
            "http://127.0.0.1:8888/api/v1/FUZZ", "web_fuzzing", "ffuf.fuzz.v1", EvidenceClass.NETWORK,
            {"endpoints": ["/api/v1/users", "/api/v1/health"]},
            False, {"stdout": '{"results": [{"input": {"FUZZ": "users"}, "status": 200}, {"input": {"FUZZ": "health"}, "status": 200}]}', "exit_code": 0},
            "Discovers REST API routes with high-speed HTTP fuzzing."
        ),
        (
            62, "Gobuster Virtual Host Subdomain Fuzzing",
            "Perform Host header fuzzing against corporate gateway to uncover hidden staging subdomains.",
            "http://127.0.0.1:8888", "web_directory_enum", "gobuster.dir.v1", EvidenceClass.NETWORK,
            {"endpoints": ["staging.internal", "dev.internal"]},
            False, {"stdout": "Found: staging.internal (Status: 200) [Size: 104]\nFound: dev.internal (Status: 200) [Size: 205]", "exit_code": 0},
            "Detects internal staging hosts via HTTP virtual host header brute forcing."
        ),
        (
            63, "SQLMap Time-Based Blind Injection Confirmation",
            "Test /api/v1/orders?id=5 with SQLMap using benchmark delay payloads to verify blind injection.",
            "http://127.0.0.1:8888/api/v1/orders?id=5", "sql_injection_test", "sqlmap.scan.v1", EvidenceClass.COMMAND,
            {"vulnerabilities": ["Time-Based Blind SQL Injection"]},
            False, {"stdout": "Parameter: id (GET)\n    Type: time-based blind\n    Title: MySQL >= 5.0.12 AND time-based blind (query SLEEP)\n    Payload: id=5 AND (SELECT 100 FROM (SELECT(SLEEP(5)))a)", "exit_code": 0},
            "Proves execution of database sleep functions via blind inference."
        ),
        (
            64, "SQLMap Database Schema & Column Enumeration",
            "Dump column names from users table on vulnerable target using SQLMap automated schema query.",
            "http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=1", "sqli_audit", "sqlmap.scan.v1", EvidenceClass.COMMAND,
            {"metadata": {"database": "dvwa", "table": "users", "columns": ["user_id", "password"]}},
            False, {"stdout": "Database: dvwa\nTable: users\n[2 columns]\n+----------+-------------+\n| Column   | Type        |\n+----------+-------------+\n| password | varchar(32) |\n| user_id  | int(6)      |\n+----------+-------------+", "exit_code": 0},
            "Extracts schema metadata via database dictionary queries."
        ),
        (
            65, "WhatWeb Framework & Server Fingerprinting",
            "Identify web server framework, jQuery version, and Ruby/Rack components on staging portal.",
            "http://127.0.0.1:8888", "service_fingerprinting", "whatweb.scan.v1", EvidenceClass.NETWORK,
            {"technologies": ["Apache", "PHP", "jQuery"]},
            False, {"stdout": '{"target": "http://127.0.0.1:8888", "http_status": 200, "plugins": {"Apache": {"version": ["2.4.41"]}, "PHP": {"version": ["7.4.3"]}, "JQuery": {"version": ["3.5.1"]}}}', "exit_code": 0},
            "Extracts client-side library and server-side framework signatures."
        ),
        (
            66, "Nikto Insecure HTTP Methods Detection",
            "Scan web server options to detect dangerous enabled methods such as PUT, DELETE, and TRACE.",
            "http://127.0.0.1:8888", "web_vulnerability_scan", "nikto.scan.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["Insecure HTTP Methods (TRACE / PUT)"]},
            False, {"stdout": "+ Target IP: 127.0.0.1\n+ Allowed HTTP Methods: GET, HEAD, POST, PUT, DELETE, TRACE\n+ Public HTTP Methods: PUT, DELETE allow remote file modification", "exit_code": 0},
            "Identifies unauthenticated dangerous HTTP method handlers."
        ),
        (
            67, "Searchsploit Local Privilege Escalation Exploit Search",
            "Query exploit database for local kernel privilege escalation PoCs targeting Linux 5.15 dirty pipe.",
            "Linux Kernel 5.15 dirty pipe", "exploit_search", "searchsploit.search.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"cve": "CVE-2022-0847", "title": "Dirty Pipe"}},
            False, {"stdout": "Linux Kernel 5.8 < 5.16.11 - 'Dirty Pipe' Local Privilege Escalation (CVE-2022-0847) | linux/local/50808.c", "exit_code": 0},
            "Correlates target kernel version with published weaponized exploits."
        ),
        (
            68, "Metasploit RPC Auxiliary Port Scanner",
            "Invoke Metasploit auxiliary/scanner/portscan/syn module via RPC to discover active TCP daemons.",
            "127.0.0.1", "metasploit_exploit", "metasploit.rpc.v1", EvidenceClass.COMMAND,
            {"ports": [22, 80, 8888]},
            False, {"stdout": "[+] 127.0.0.1:22 - TCP OPEN\n[+] 127.0.0.1:80 - TCP OPEN\n[+] 127.0.0.1:8888 - TCP OPEN\n[*] Scanned 1 of 1 hosts (100% complete)", "exit_code": 0},
            "Executes auxiliary scanning routines through Metasploit RPC daemon."
        ),
        (
            69, "Hydra SSH Authentication Brute-Force Audit",
            "Audit SSH service on 127.0.0.1:22 for default credentials using targeted password list.",
            "127.0.0.1:22", "credential_testing", "hydra.brute.v1", EvidenceClass.COMMAND,
            {"credentials": [{"user": "msfadmin", "service": "ssh"}]},
            False, {"stdout": "[22][ssh] host: 127.0.0.1   login: msfadmin   password: msfadmin\n1 of 1 target completed, 1 valid password found", "exit_code": 0},
            "Evaluates SSH credential strength and defaults."
        ),
        (
            70, "Wireshark Raw Socket Permission Recovery",
            "Recover when packet capture fails due to socket privilege restriction on unprivileged user.",
            "eth0", "packet_analysis", "wireshark.gui.v1", EvidenceClass.NETWORK,
            {"metadata": {"recovered": True}},
            True, {
                "attempt_1": {"stdout": "dumpcap: The capture session could not be initiated on interface 'eth0' (You don't have permission to capture on that device).", "exit_code": 1},
                "attempt_2": {"stdout": '{"action": "grant_net_raw_caps", "status": "captured", "recovered": true, "packets": 20}', "exit_code": 0}
            },
            "Tests capability adjustment and recovery when raw socket permissions fail."
        ),
        (
            71, "ExifTool Image Geolocation & Camera Metadata Extraction",
            "Extract GPS latitude, longitude, and device serial metadata from uploaded JPEG evidence file.",
            "/tmp/evidence_photo.jpg", "file_metadata_analysis", "exiftool.extract.v1", EvidenceClass.FILE,
            {"metadata": {"camera_make": "Apple", "gps_latitude": "37 deg 46' 29.88\" N"}},
            False, {"stdout": '{"CameraModelName": "iPhone 13 Pro", "GPSLatitude": "37.7749 N", "GPSLongitude": "122.4194 W", "ModifyDate": "2026:10:05 12:00:00"}', "exit_code": 0},
            "Recovers forensic location and hardware provenance from media files."
        ),
        (
            72, "Hashid Shadow File Password Hash Identification",
            "Analyze Unix /etc/shadow password hash string and identify SHA-512 crypt hashing algorithm.",
            "$6$saltstring$hashedpasswordvalue", "hash_identification", "hashid.identify.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"hash_type": "SHA-512 Crypt"}},
            False, {"stdout": "Analyzing '$6$saltstring$hashedpasswordvalue'\n[+] SHA-512 Crypt [Hashcat Mode: 1800]\n[+] Unix Crypt [Hashcat Mode: 1500]", "exit_code": 0},
            "Determines hashing primitive and cracking mode for credential hashes."
        ),
        (
            73, "Dig DNS MX Mail Exchanger Audit",
            "Query authoritative DNS records to discover mail exchange servers and priority weighting.",
            "internal.domain", "dns_lookup", "dig.lookup.v1", EvidenceClass.NETWORK,
            {"dns_records": [{"type": "MX", "host": "mail.internal.domain"}]},
            False, {"stdout": ";; ANSWER SECTION:\ninternal.domain. 300 IN MX 10 mail.internal.domain.", "exit_code": 0},
            "Audits corporate mail server records and relay boundaries."
        ),
        (
            74, "Whois Registrar & Autonomous System Lookup",
            "Query WHOIS database to identify organization name and autonomous system number (ASN).",
            "127.0.0.1", "domain_whois_lookup", "whois.lookup.v1", EvidenceClass.NETWORK,
            {"metadata": {"organization": "Loopback Netblock", "country": "US"}},
            False, {"stdout": "NetRange: 127.0.0.0 - 127.255.255.255\nCIDR: 127.0.0.0/8\nNetName: LOOPBACK\nOrgName: Internet Assigned Numbers Authority", "exit_code": 0},
            "Gathers organizational registration data from public registry."
        ),
        (
            75, "Tcpdump SYN Flood DoS Detection",
            "Capture incoming TCP SYN packets without ACK handshake completion on port 80 to detect flood.",
            "lo", "network_traffic_capture", "tcpdump.capture.v1", EvidenceClass.NETWORK,
            {"metadata": {"syn_flood_detected": True, "syn_count": 500}},
            False, {"stdout": "500 packets captured\n500 packets received by filter\n0 packets dropped by kernel\n[alert] Excessive SYN rate detected without ACK response", "exit_code": 0},
            "Analyzes packet rates to diagnose denial-of-service volumetric events."
        ),
        (
            76, "Shell Linux SUID Binary Security Audit",
            "Search file system for binaries with SUID permission bit set (e.g. /usr/bin/find, /bin/bash).",
            "/usr/bin", "command_execution", "shell.run.v1", EvidenceClass.COMMAND,
            {"metadata": {"suid_binaries": ["/usr/bin/sudo", "/usr/bin/passwd"]}},
            False, {"stdout": "/usr/bin/sudo\n/usr/bin/passwd\n/usr/bin/chsh\n/usr/bin/gpasswd", "exit_code": 0},
            "Audits SUID executables for privilege escalation primitives."
        ),
        (
            77, "Kali Linux Kernel Audit & ASLR Verification",
            "Inspect system memory randomization parameters to ensure ASLR is set to full randomization (value 2).",
            "/proc/sys/kernel/randomize_va_space", "command_execution", "kali.exec.v1", EvidenceClass.COMMAND,
            {"metadata": {"aslr_setting": 2, "status": "secure"}},
            False, {"stdout": "2\nKernel ASLR setting: Full Randomization (Enabled)", "exit_code": 0},
            "Verifies operating system exploit mitigation features."
        ),
        (
            78, "Nmap UDP Top Ports Service Discovery",
            "Scan top 20 UDP ports on lab gateway to detect active SNMP and DNS daemons.",
            "127.0.0.1", "network_port_scan", "nmap.scan.v1", EvidenceClass.NETWORK,
            {"ports": [53, 161]},
            False, {"stdout": '<nmaprun><host><ports><port protocol="udp" portid="53"><state state="open"/><service name="domain"/></port><port protocol="udp" portid="161"><state state="open"/><service name="snmp"/></port></ports></host></nmaprun>', "exit_code": 0},
            "Uncovers unadvertised UDP network infrastructure services."
        ),
        (
            79, "Nmap Operating System Fingerprint Detection",
            "Probe TCP/IP stack behavior to identify host OS kernel version and device type.",
            "127.0.0.1", "os_fingerprint", "nmap.scan.v1", EvidenceClass.NETWORK,
            {"metadata": {"os_match": "Linux 5.4 - 5.15", "accuracy": 98}},
            False, {"stdout": "<os><osmatch name=\"Linux 5.4 - 5.15\" accuracy=\"98\"><osclass type=\"general purpose\" vendor=\"Linux\" osfamily=\"Linux\"/></osmatch></os>", "exit_code": 0},
            "Fingerprints host operating system using TCP ISN and window probe heuristics."
        ),
        (
            80, "System Ping Subnet Latency Sweep",
            "Perform low-overhead ICMP ping sweep across lab subnetwork to calculate median round-trip time.",
            "127.0.0.1", "host_live_detection", "system_ping", EvidenceClass.NETWORK,
            {"hosts": ["127.0.0.1"]},
            False, {"stdout": "PING 127.0.0.1: 56 data bytes\n64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.038 ms\nround-trip min/avg/max = 0.038/0.042/0.051 ms", "exit_code": 0},
            "Calculates network latency metrics and packet loss."
        ),
        (
            81, "Dig DNS TXT Record Domain Verification",
            "Retrieve DNS TXT records to verify SPF mail authentication policies and domain ownership tokens.",
            "internal.domain", "dns_lookup", "dig.lookup.v1", EvidenceClass.NETWORK,
            {"dns_records": [{"type": "TXT"}]},
            False, {"stdout": ";; ANSWER SECTION:\ninternal.domain. 300 IN TXT \"v=spf1 include:_spf.internal -all\"", "exit_code": 0},
            "Evaluates domain SPF security directives."
        ),
        (
            82, "Whois Autonomous System Origin Lookup",
            "Query routing registry to determine upstream ASN routing advertisements for target network range.",
            "127.0.0.1", "domain_whois_lookup", "whois.lookup.v1", EvidenceClass.NETWORK,
            {"metadata": {"asn": "AS15169"}},
            False, {"stdout": "OriginAS: AS15169\nASName: GOOGLE-LABS\nRegDate: 2000-03-30", "exit_code": 0},
            "Maps autonomous system transit and routing hierarchy."
        ),
        (
            83, "FFUF HTTP Header Fuzzing for IP Bypass",
            "Fuzz X-Forwarded-For and Client-IP headers against admin route to bypass local network restriction.",
            "http://127.0.0.1:8888/admin", "web_fuzzing", "ffuf.fuzz.v1", EvidenceClass.NETWORK,
            {"endpoints": ["/admin"]},
            False, {"stdout": '{"results": [{"header": "X-Forwarded-For: 127.0.0.1", "status": 200, "length": 420}]}', "exit_code": 0},
            "Identifies header-based authorization spoofing vectors."
        ),
        (
            84, "Gobuster File Extension Discovery Scan",
            "Scan web application with gobuster searching specifically for .bak, .conf, and .env files.",
            "http://127.0.0.1:8888", "web_directory_enum", "gobuster.dir.v1", EvidenceClass.NETWORK,
            {"endpoints": ["/config.bak", "/.env"]},
            False, {"stdout": "Found: /config.bak (Status: 200) [Size: 512]\nFound: /.env (Status: 200) [Size: 180]", "exit_code": 0},
            "Discovers exposed source code and sensitive environment configuration backups."
        ),
        (
            85, "ZAP Spider Infinite Recursion Recovery",
            "Recover when web crawler enters infinite loop on dynamic calendar links via regex exclusion.",
            "http://127.0.0.1:8888/calendar", "web_spider", "zap.gui.v1", EvidenceClass.NETWORK,
            {"metadata": {"recovered": True}},
            True, {
                "attempt_1": {"stdout": "Error: Spider recursion depth exceeded 1000 requests on calendar URL", "exit_code": 124},
                "attempt_2": {"stdout": '{"action": "add_regex_exclude", "pattern": "/calendar/.*", "status": "crawled", "recovered": true}', "exit_code": 0}
            },
            "Recovers crawler health using URL exclusion rules when trap URLs are encountered."
        ),
        (
            86, "Security Browser LocalStorage Sensitive Token Audit",
            "Inspect browser window.localStorage for unencrypted JWT tokens or API secrets after authentication.",
            "http://127.0.0.1:8888/dashboard", "dom_inspection", "browser.security.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"local_storage_tokens": ["auth_jwt_token"]}},
            False, {"stdout": '{"workflow": "storage_audit", "local_storage": {"auth_jwt_token": "eyJhbGciOi..."}, "session_storage": {}}', "exit_code": 0},
            "Audits client-side HTML5 storage for unencrypted session credential leaks."
        ),
        (
            87, "Security Browser Content Security Policy Audit",
            "Evaluate target website response headers and meta tags for unsafe-inline and unsafe-eval CSP rules.",
            "http://127.0.0.1:8888", "browser_testing", "browser.security.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["Weak Content Security Policy (unsafe-inline allowed)"]},
            False, {"stdout": '{"workflow": "csp_audit", "csp_header": "default-src \'self\' \'unsafe-inline\'; script-src *", "vulnerability": "Weak Content Security Policy"}', "exit_code": 0},
            "Analyzes Content Security Policy configurations for script injection mitigation."
        ),
        (
            88, "SQLMap Second-Order SQL Injection Verification",
            "Inject payload into profile name field and trigger delayed database query on administrative view.",
            "http://127.0.0.1:8888/profile/edit", "sql_injection_test", "sqlmap.scan.v1", EvidenceClass.COMMAND,
            {"vulnerabilities": ["Second-Order SQL Injection"]},
            False, {"stdout": "Identified second-order injection point:\nTrigger URL: http://127.0.0.1:8888/admin/view\nBackend DBMS: MySQL 5.7", "exit_code": 0},
            "Confirms second-order data execution through decoupled trigger endpoints."
        ),
        (
            89, "Nikto SSL/TLS Cipher Suite Security Audit",
            "Audit web server SSL certificate, weak cipher suites, and support for deprecated TLS 1.0/1.1.",
            "https://127.0.0.1:8443", "web_vulnerability_scan", "nikto.scan.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["Deprecated TLS 1.0/1.1 Supported", "Weak CBC Cipher"]},
            False, {"stdout": "+ SSL/TLS Certificate: CN=lab-stage.internal\n+ Deprecated Protocol: TLSv1.0 is offered\n+ Deprecated Protocol: TLSv1.1 is offered\n+ Weak Cipher: TLS_RSA_WITH_AES_128_CBC_SHA", "exit_code": 0},
            "Evaluates cryptographic transport layer security posture."
        ),
        (
            90, "ExifTool PDF Document Revision History Inspection",
            "Extract linear revision history, author usernames, and producer tool versions from PDF document.",
            "/tmp/annual_report.pdf", "file_metadata_analysis", "exiftool.extract.v1", EvidenceClass.FILE,
            {"metadata": {"author": "Finance Admin", "creator_tool": "Adobe Acrobat Pro"}},
            False, {"stdout": '{"Author": "Finance Admin", "Creator": "Adobe Acrobat Pro", "Producer": "macOS Quartz", "PageCount": 24}', "exit_code": 0},
            "Recovers forensic document creator attribution and software traces."
        ),
        (
            91, "Hashid NTLM Windows Hash Classification",
            "Identify 32-character hexadecimal Windows password hash as NTLM cryptographic hash format.",
            "31d6cfe0d16ae931b73c59d7e0c089c0", "hash_identification", "hashid.identify.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"hash_type": "NTLM"}},
            False, {"stdout": "Analyzing '31d6cfe0d16ae931b73c59d7e0c089c0'\n[+] NTLM [Hashcat Mode: 1000]\n[+] MD4 [Hashcat Mode: 900]", "exit_code": 0},
            "Identifies Windows credential hash format for password recovery."
        ),
        (
            92, "Hydra HTTP Basic Authentication Password Audit",
            "Perform credential testing against HTTP basic authentication prompt on restricted admin portal.",
            "http://127.0.0.1:8888/restricted", "credential_testing", "hydra.brute.v1", EvidenceClass.COMMAND,
            {"credentials": [{"user": "admin", "service": "http-get"}]},
            False, {"stdout": "[8888][http-get] host: 127.0.0.1   login: admin   password: password123\n1 valid password found", "exit_code": 0},
            "Validates HTTP basic authorization credential security."
        ),
        (
            93, "Shell Cron Job Privilege Escalation Inspection",
            "Inspect system /etc/crontab and /etc/cron.d/ scheduled tasks for world-writable shell scripts.",
            "/etc/crontab", "command_execution", "shell.run.v1", EvidenceClass.COMMAND,
            {"metadata": {"cron_jobs": ["/usr/local/bin/backup.sh"]}},
            False, {"stdout": "* * * * * root /usr/local/bin/backup.sh\nWarning: /usr/local/bin/backup.sh is world-writable (mode 0777)", "exit_code": 0},
            "Detects scheduled task misconfigurations for privilege escalation."
        ),
        (
            94, "Kali Network Interface Promiscuous Mode Check",
            "Check network interface flags on eth0 to verify promiscuous mode packet listening configuration.",
            "eth0", "command_execution", "kali.exec.v1", EvidenceClass.COMMAND,
            {"metadata": {"promisc": True, "interface": "eth0"}},
            False, {"stdout": "flags=4419<UP,BROADCAST,RUNNING,PROMISC,MULTICAST>  mtu 1500\nDevice in promiscuous mode", "exit_code": 0},
            "Verifies raw packet listening configuration on host interfaces."
        ),
        (
            95, "Searchsploit OpenSSH User Enumeration CVE Search",
            "Search exploit database for OpenSSH username enumeration vulnerabilities (CVE-2018-15473).",
            "OpenSSH 7.7 username enumeration", "exploit_search", "searchsploit.search.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"cve": "CVE-2018-15473"}},
            False, {"stdout": "OpenSSH < 7.7 - User Enumeration (CVE-2018-15473) | linux/remote/45233.py", "exit_code": 0},
            "Correlates SSH protocol timing quirks with user enumeration PoCs."
        ),
        (
            96, "Metasploit SMB Version Detection Auxiliary Scan",
            "Run Metasploit auxiliary/scanner/smb/smb_version to detect Windows dialect and SMBv1 exposure.",
            "127.0.0.1", "metasploit_exploit", "metasploit.rpc.v1", EvidenceClass.COMMAND,
            {"metadata": {"smb_version": "Samba 3.0.20", "os": "Unix"}},
            False, {"stdout": "[+] 127.0.0.1:445 - Host is running Samba 3.0.20-Debian (Unix)", "exit_code": 0},
            "Audits SMB service versions and file sharing dialects."
        ),
        (
            97, "Tcpdump DNS Exfiltration Packet Capture",
            "Capture outbound DNS query traffic to identify base64 data exfiltration in subdomain labels.",
            "lo", "network_traffic_capture", "tcpdump.capture.v1", EvidenceClass.NETWORK,
            {"metadata": {"dns_tunneling_detected": True}},
            False, {"stdout": "IP 127.0.0.1.53421 > 127.0.0.1.53: 1234+ A? ZXBoaWxl.data.internal. (36)\nAlert: High entropy subdomain label detected", "exit_code": 0},
            "Monitors outbound DNS channels for data exfiltration patterns."
        ),
        (
            98, "WhatWeb Security Headers Inspection",
            "Inspect presence of X-Content-Type-Options and Strict-Transport-Security headers via WhatWeb.",
            "http://127.0.0.1:8888", "service_fingerprinting", "whatweb.scan.v1", EvidenceClass.NETWORK,
            {"technologies": ["Apache"]},
            False, {"stdout": '{"target": "http://127.0.0.1:8888", "http_status": 200, "plugins": {"Apache": {"version": ["2.4.41"]}}}', "exit_code": 0},
            "Audits foundational HTTP response security policy headers."
        ),
        (
            99, "Nmap Vulnerability Script Engine (NSE) Audit",
            "Execute Nmap --script vuln against HTTP server to discover known CVE exposures.",
            "127.0.0.1:8888", "network_port_scan", "nmap.scan.v1", EvidenceClass.NETWORK,
            {"vulnerabilities": ["Slowloris DoS"]},
            False, {"stdout": '<nmaprun><host><ports><port protocol="tcp" portid="8888"><script id="http-slowloris-check" output="Vulnerable: Slowloris DoS"/></port></ports></host></nmaprun>', "exit_code": 0},
            "Leverages Nmap Scripting Engine for automated vulnerability verification."
        ),
        (
            100, "Security Browser WAF Evasion Recovery",
            "Recover when automated browser testing triggers 403 Forbidden Cloudflare/ModSecurity WAF rule.",
            "http://127.0.0.1:8888/waf_protected", "browser_testing", "browser.security.v1", EvidenceClass.VISUAL,
            {"metadata": {"recovered": True}},
            True, {
                "attempt_1": {"stdout": "HTTP 403 Forbidden: Request blocked by Web Application Firewall (Signature Match)", "exit_code": 1},
                "attempt_2": {"stdout": '{"action": "rotate_user_agent_and_delays", "status": "200 OK", "recovered": true, "screenshot_sha256": "c3d4e5f6a1"}', "exit_code": 0}
            },
            "Tests autonomous heuristic evasion when security browser hits WAF blocks."
        ),
        (
            101, "Burp Suite Target Site Map Tree Building",
            "Passive crawl target domain and assemble hierarchical site map of all discovered URLs.",
            "http://127.0.0.1:8888", "target_mapping", "burpsuite.gui.v1", EvidenceClass.VISUAL,
            {"endpoints": ["/dvwa/", "/dvwa/login.php", "/dvwa/vulnerabilities/"]},
            False, {"stdout": '{"site_map_urls_count": 48, "scope_included": ["http://127.0.0.1:8888"], "screenshot_sha256": "b1c2d3e4f5"}', "exit_code": 0},
            "Assembles comprehensive target tree in Burp proxy workspace."
        ),
        (
            102, "Wireshark TLS Handshake Cipher Negotiation Inspection",
            "Dissect TLS Client Hello and Server Hello packets to determine negotiated cipher suite.",
            "https://127.0.0.1:8443", "traffic_dissection", "wireshark.gui.v1", EvidenceClass.NETWORK,
            {"metadata": {"cipher_suite": "TLS_AES_256_GCM_SHA384", "tls_version": "TLS 1.3"}},
            False, {"stdout": '{"handshake": "TLS 1.3", "cipher": "TLS_AES_256_GCM_SHA384", "status": "negotiated"}', "exit_code": 0},
            "Analyzes encrypted session initiation and forward secrecy parameters."
        ),
        (
            103, "ZAP Passive Scan Security Alert Aggregation",
            "Aggregate all passive security alerts generated during web browsing into structured card format.",
            "http://127.0.0.1:8888", "web_vulnerability_scan", "zap.gui.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["Cookie Without SameSite Attribute", "X-Content-Type-Options Missing"]},
            False, {"stdout": '{"alerts_count": 2, "alerts": ["Cookie Without SameSite Attribute", "X-Content-Type-Options Missing"]}', "exit_code": 0},
            "Collects background passive scanner observations without active probing."
        ),
        (
            104, "Security Browser Clickjacking UI Redress Check",
            "Verify whether target application allows framing inside iframe element without X-Frame-Options.",
            "http://127.0.0.1:8888", "browser_testing", "browser.security.v1", EvidenceClass.VISUAL,
            {"vulnerabilities": ["Clickjacking (Missing X-Frame-Options)"]},
            False, {"stdout": '{"workflow": "clickjacking_check", "framed_successfully": true, "vulnerability": "Clickjacking (Missing X-Frame-Options)"}', "exit_code": 0},
            "Renders framed interface in browser to confirm UI redress susceptibility."
        ),
        (
            105, "FFUF Directory Fuzzing with Status Code Filtering",
            "Filter fuzzing results to isolate only HTTP 200, 301, and 403 responses while ignoring 404s.",
            "http://127.0.0.1:8888/FUZZ", "web_fuzzing", "ffuf.fuzz.v1", EvidenceClass.NETWORK,
            {"endpoints": ["/admin", "/login"]},
            False, {"stdout": '{"results": [{"url": "/admin", "status": 200}, {"url": "/login", "status": 301}]}', "exit_code": 0},
            "Applies response code filtering to minimize fuzzer observation noise."
        ),
        (
            106, "Gobuster Subdomain Brute-Force with Wildcard DNS Detection",
            "Detect wildcard DNS redirection before launching subdomain enumeration to avoid false positives.",
            "internal.domain", "dns_subdomain_discovery", "gobuster.dir.v1", EvidenceClass.NETWORK,
            {"metadata": {"wildcard_detected": False}},
            False, {"stdout": "[-] Checking for wildcard DNS: None found.\nFound: api.internal.domain (127.0.0.1)", "exit_code": 0},
            "Ensures DNS enumeration validity by handling wildcard resolution."
        ),
        (
            107, "SQLMap Operating System Command Execution Check",
            "Test database connection privileges to see if xp_cmdshell or sys_eval UDF can be invoked.",
            "http://127.0.0.1:8888/dvwa/vulnerabilities/sqli/?id=1", "sql_injection_test", "sqlmap.scan.v1", EvidenceClass.COMMAND,
            {"metadata": {"dba_privilege": False}},
            False, {"stdout": "[*] Testing current user privileges for OS command execution: User 'dvwa'@'localhost' does not have SUPER privilege.", "exit_code": 0},
            "Evaluates potential for database-mediated operating system escalation."
        ),
        (
            108, "Nikto Outdated Server-Side Include (SSI) Audit",
            "Check for Server-Side Include execution and server-parsed HTML file exposure.",
            "http://127.0.0.1:8888", "web_vulnerability_scan", "nikto.scan.v1", EvidenceClass.ANALYTIC,
            {"vulnerabilities": ["SSI File Exposure"]},
            False, {"stdout": "+ /index.shtml: Server Side Include found. May allow remote command injection.", "exit_code": 0},
            "Detects legacy server-side scripting features."
        ),
        (
            109, "Searchsploit WordPress Plugin Vulnerability Correlation",
            "Find SQL injection exploits affecting vulnerable WordPress plugin wp-file-manager 6.8.",
            "WordPress wp-file-manager 6.8", "exploit_search", "searchsploit.search.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"cve": "CVE-2020-25213"}},
            False, {"stdout": "WordPress Plugin File Manager 6.8 - Remote Code Execution | php/webapps/48800.py", "exit_code": 0},
            "Identifies third-party web application plugin vulnerabilities."
        ),
        (
            110, "Metasploit RPC Session State Verification",
            "Verify active Meterpreter or shell session status on compromised lab host through RPC interface.",
            "session:1", "metasploit_exploit", "metasploit.rpc.v1", EvidenceClass.COMMAND,
            {"metadata": {"session_active": True, "type": "meterpreter"}},
            False, {"stdout": '{"session_id": 1, "type": "meterpreter", "tunnel_peer": "127.0.0.1:4444", "status": "active"}', "exit_code": 0},
            "Maintains post-exploitation session connectivity and health."
        ),
        (
            111, "Hydra FTP Password Dictionary Attack Audit",
            "Audit FTP server on port 21 for weak system account passwords (anonymous, admin, backup).",
            "127.0.0.1:21", "credential_testing", "hydra.brute.v1", EvidenceClass.COMMAND,
            {"credentials": [{"user": "anonymous", "service": "ftp"}]},
            False, {"stdout": "[21][ftp] host: 127.0.0.1   login: anonymous   password: anonymous\n1 valid password found", "exit_code": 0},
            "Identifies unauthenticated and anonymous FTP access policies."
        ),
        (
            112, "ExifTool PNG Screenshot Metadata Sanity Check",
            "Verify screenshot PNG generated by security browser contains SHA-256 comment metadata.",
            "/tmp/kairo_screenshot.png", "file_metadata_analysis", "exiftool.extract.v1", EvidenceClass.FILE,
            {"metadata": {"file_type": "PNG"}},
            False, {"stdout": '{"FileType": "PNG", "ImageWidth": 1280, "ImageHeight": 800, "Comment": "Kairo Evidence Hash: a1b2c3d4"}', "exit_code": 0},
            "Confirms evidentiary metadata embedding in captured screenshots."
        ),
        (
            113, "Hashid bcrypt Cryptographic Hash Detection",
            "Identify $2a$ and $2b$ modular crypt format hashes as bcrypt password hashing function.",
            "$2b$12$e8O0V0yW6q8u8/1X9N.B..qR1v/3K1o0F4w5X8e6D2c1B0a", "hash_identification", "hashid.identify.v1", EvidenceClass.ANALYTIC,
            {"metadata": {"hash_type": "bcrypt"}},
            False, {"stdout": "Analyzing '$2b$12$...'\n[+] bcrypt [Hashcat Mode: 3200]", "exit_code": 0},
            "Recognizes adaptive, cost-factored password hashing schemes."
        ),
        (
            114, "Dig DNS Zone Transfer (AXFR) Vulnerability Check",
            "Attempt DNS AXFR zone transfer against name server to detect exposed zone records.",
            "internal.domain", "dns_lookup", "dig.lookup.v1", EvidenceClass.NETWORK,
            {"metadata": {"axfr_refused": True}},
            False, {"stdout": "; <<>> DiG 9.16.1 <<>> axfr internal.domain @127.0.0.1\n; Transfer failed.\n;; communications error: connection refused / query refused", "exit_code": 0},
            "Audits DNS server configurations for unrestricted zone transfer leakage."
        ),
        (
            115, "Kali ADB Daemon Failure Autonomous Recovery",
            "Recover when Android debug bridge server crashes or becomes unresponsive during mobile audit.",
            "127.0.0.1:5555", "command_execution", "kali.exec.v1", EvidenceClass.COMMAND,
            {"metadata": {"recovered": True}},
            True, {
                "attempt_1": {"stdout": "adb: error: cannot connect to daemon at tcp:5037: Connection refused", "exit_code": 1},
                "attempt_2": {"stdout": '{"action": "adb_kill_and_restart", "daemon_status": "restarted", "recovered": true, "device": "emulator-5554"}', "exit_code": 0}
            },
            "Performs autonomous daemon self-healing when mobile emulator bridge crashes."
        ),
        (
            116, "Tcpdump SSH Cleartext Protocol Negotiation Analysis",
            "Sniff initial SSH protocol banner exchange to verify server version advertisement.",
            "lo", "network_traffic_capture", "tcpdump.capture.v1", EvidenceClass.NETWORK,
            {"metadata": {"ssh_banner": "SSH-2.0-OpenSSH_4.7p1"}},
            False, {"stdout": "127.0.0.1.22 > 127.0.0.1.41234: Flags [P.], seq 1:42, ack 1\nSSH-2.0-OpenSSH_4.7p1 Debian-8ubuntu1", "exit_code": 0},
            "Captures cleartext network protocol version exchanges."
        ),
        (
            117, "Shell Linux Environment Secret Variable Audit",
            "Scan active environment variables (/proc/self/environ) for exposed AWS, JWT, or database keys.",
            "/proc/self/environ", "command_execution", "shell.run.v1", EvidenceClass.COMMAND,
            {"metadata": {"secrets_detected": False}},
            False, {"stdout": "USER=kali\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin\nSHELL=/bin/bash\n[✓] No cleartext API keys found in runtime environment", "exit_code": 0},
            "Audits environment memory spaces for sensitive token leaks."
        ),
        (
            118, "WhatWeb Web Application Firewall Detection",
            "Identify active cloud or host WAF signatures (Cloudflare, AWS WAF, ModSecurity) via HTTP headers.",
            "http://127.0.0.1:8888", "service_fingerprinting", "whatweb.scan.v1", EvidenceClass.NETWORK,
            {"technologies": ["Apache"]},
            False, {"stdout": '{"target": "http://127.0.0.1:8888", "plugins": {"Apache": {"version": ["2.4.41"]}, "WAF": {"name": "None Detected"}}}', "exit_code": 0},
            "Detects edge protective firewalls to calibrate attack intensity."
        ),
        (
            119, "Nmap Target Host Discovery via ARP Scan",
            "Perform local link-layer ARP request scanning to enumerate physical MAC addresses of active hosts.",
            "127.0.0.1", "host_live_detection", "nmap.scan.v1", EvidenceClass.NETWORK,
            {"hosts": ["127.0.0.1"]},
            False, {"stdout": '<nmaprun><host><status state="up"/><address addr="127.0.0.1" addrtype="ipv4"/><address addr="00:00:00:00:00:00" addrtype="mac"/></host></nmaprun>', "exit_code": 0},
            "Uses ARP layer probes for resilient local network host identification."
        ),
        (
            120, "Comprehensive Autonomous Kill-Chain Verification",
            "Execute end-to-end verification linking discovery, vulnerability confirmation, and structured report.",
            "http://127.0.0.1:8888", "command_execution", "shell.run.v1", EvidenceClass.REPORT,
            {"metadata": {"killchain_complete": True, "stages_verified": ["Recon", "Discovery", "Exploit", "Report"]}},
            False, {"stdout": '{"status": "killchain_verified", "stages": ["Recon", "Discovery", "Exploit", "Report"], "report_sha256": "e3b0c44298fc"}', "exit_code": 0},
            "Validates full multi-hop kill-chain execution with cryptographic evidence chain."
        ),
    ]

    for item in specs:
        (
            id_num, name, obj, target, cap, tool, ev_class,
            ev_spec, rec, raw_out, desc
        ) = item

        t = LabTask(
            task_id=f"LAB-TASK-{id_num:02d}",
            name=name,
            objective=obj,
            target=target,
            capability=cap,
            expected_tool_family=tool,
            expected_evidence_class=ev_class,
            expected_evidence_spec=ev_spec,
            recovery_challenge=rec,
            recovery_trigger={"attempt_1_tool": tool, "attempt_1_error": "timeout"} if rec else None,
            simulated_raw_output=raw_out,
            description=desc,
        )
        tasks.append(t)

    return tasks


EXTENDED_LAB_TASKS = _build_extended_tasks()
