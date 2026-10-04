"""
Intentionally Vulnerable Lab Targets for Kairo Benchmark.
Provides Mini-DVWA (Web vulnerabilities) and Mini-Metasploitable (Network services).

Targets:
1. Mini-DVWA (HTTP Service on port 8888):
   - Open Endpoints & Directory Enumeration (/admin, /secret_api, /config.bak)
   - SQL Injection (/dvwa/vulnerabilities/sqli/?id=1' OR 1=1 --)
   - Command Injection (/dvwa/vulnerabilities/exec/?ip=127.0.0.1; id)
   - Path Traversal / LFI (/dvwa/vulnerabilities/fi/?page=../../../../etc/passwd)
   - Weak Authentication (/dvwa/login.php)
   - Information Disclosure & Technology Headers (Apache/2.4.41, PHP/7.4.3)

2. Mini-Metasploitable (TCP Multi-service listener on port 8889):
   - Simulated FTP vsftpd 2.3.4 (Port 21 banner)
   - Simulated OpenSSH 4.7p1 (Port 22 banner)
   - Simulated Apache 2.2.8 DAV (Port 80 banner)
   - Simulated MySQL 5.0.51a (Port 3306 banner)
"""

from __future__ import annotations

import http.server
import json
import logging
import socket
import socketserver
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("lab.targets")


class MiniDVWAHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler simulating DVWA vulnerabilities."""

    server_version = "Apache/2.4.41"
    sys_version = "(Ubuntu)"

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy standard HTTP access logs in test runs
        pass

    def send_cors_and_tech_headers(self, status_code: int = 200, content_type: str = "text/html") -> None:
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Server", "Apache/2.4.41 (Ubuntu)")
        self.send_header("X-Powered-By", "PHP/7.4.3")
        # Intentionally omit CSP, X-Frame-Options, HSTS to trigger Nikto/web misconfiguration findings
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.send_cors_and_tech_headers(200)

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        # 1. Landing Page
        if path in ("/", "/dvwa", "/dvwa/"):
            self.send_cors_and_tech_headers(200, "text/html")
            body = """<!DOCTYPE html>
<html>
<head><title>Damn Vulnerable Web App (DVWA) - Kairo Lab v1.0</title></head>
<body>
<h1>Damn Vulnerable Web App (DVWA) v1.10 *Development*</h1>
<p>Kairo Intentionally Vulnerable Benchmark Environment</p>
<ul>
  <li><a href="/dvwa/login.php">Login Portal</a></li>
  <li><a href="/dvwa/vulnerabilities/sqli/?id=1">SQL Injection (Blind / Error)</a></li>
  <li><a href="/dvwa/vulnerabilities/exec/?ip=127.0.0.1">Command Execution</a></li>
  <li><a href="/dvwa/vulnerabilities/fi/?page=include.php">File Inclusion / Path Traversal</a></li>
  <li><a href="/dvwa/admin/">Administrator Console</a></li>
  <li><a href="/dvwa/config.bak">Configuration Backup</a></li>
</ul>
<div id="footer">Apache/2.4.41 (Ubuntu) Server at 127.0.0.1</div>
</body>
</html>"""
            self.wfile.write(body.encode("utf-8"))
            return

        # 2. robots.txt
        if path == "/robots.txt":
            self.send_cors_and_tech_headers(200, "text/plain")
            body = "User-agent: *\nDisallow: /dvwa/admin/\nDisallow: /dvwa/secret_api/\nDisallow: /config.bak\n"
            self.wfile.write(body.encode("utf-8"))
            return

        # 3. Hidden Admin Endpoints (Directory Enumeration Fuzzing)
        if path in ("/admin", "/admin/", "/dvwa/admin", "/dvwa/admin/"):
            self.send_cors_and_tech_headers(200, "text/html")
            body = """<html><head><title>Admin Console</title></head>
<body>
<h2>DVWA Internal Administration Panel</h2>
<p>Privileged Operator Dashboard. System: Ubuntu 20.04 LTS.</p>
<div class="user-list">Active Users: admin, secops, auditor</div>
</body></html>"""
            self.wfile.write(body.encode("utf-8"))
            return

        if path in ("/secret_api", "/secret_api/", "/dvwa/secret_api", "/dvwa/secret_api/"):
            self.send_cors_and_tech_headers(200, "application/json")
            data = {
                "status": "active",
                "api_version": "v1.4-debug",
                "jwt_secret": "kairo_internal_benchmark_hmac_secret_2026",
                "endpoints": ["/api/v1/users", "/api/v1/tokens", "/api/v1/db_dump"],
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        # 4. Sensitive Backup File Exposure
        if path in ("/config.bak", "/dvwa/config.bak"):
            self.send_cors_and_tech_headers(200, "text/plain")
            body = """<?php
# DVWA Database Configuration Backup (DO NOT DEPLOY IN PRODUCTION)
$_DVWA = array();
$_DVWA[ 'db_server' ]   = '127.0.0.1';
$_DVWA[ 'db_database' ] = 'dvwa';
$_DVWA[ 'db_user' ]     = 'dvwa_root';
$_DVWA[ 'db_password' ] = 'SuperSecretDbPass2026!';
$_DVWA[ 'db_port' ]     = '3306';
$_DVWA[ 'api_key' ]     = 'kairo_leaked_api_token_991823a7f8';
?>"""
            self.wfile.write(body.encode("utf-8"))
            return

        # 5. SQL Injection Endpoint
        if path.startswith("/dvwa/vulnerabilities/sqli"):
            id_val = query.get("id", [""])[0]
            self.send_cors_and_tech_headers(200, "text/html")

            # Check for SQL injection payloads
            id_upper = id_val.upper()
            is_sqli = any(
                pattern in id_upper
                for pattern in ("'", "OR 1=1", "UNION", "SELECT", "--", "#", "SLEEP(", "VERSION()")
            )

            if is_sqli:
                body = f"""<html><body>
<h2>Vulnerability: SQL Injection</h2>
<div class="vulnerable_code">Query: SELECT first_name, surname, password FROM users WHERE user_id = '{id_val}'</div>
<pre>
--- [SQL Query Dump] ---
User ID: 1
First name: admin
Surname: Administrator
Password Hash: $1$admin$0123456789abcdef (MD5-Crypt / Unix)

User ID: 2
First name: Gordon
Surname: Brown
Password Hash: e99a18c428cb38d5f260853678922e03 (MD5)

Database: dvwa_production
DBMS Version: 10.4.17-MariaDB-1:10.4.17+maria~bionic
Backend Architecture: Linux x86_64
------------------------
</pre>
</body></html>"""
            elif id_val == "1":
                body = """<html><body>
<h2>User Info</h2>
<pre>ID: 1<br>First name: admin<br>Surname: Administrator</pre>
</body></html>"""
            else:
                body = f"""<html><body><h2>User Info</h2><pre>User '{id_val}' not found.</pre></body></html>"""

            self.wfile.write(body.encode("utf-8"))
            return

        # 6. Command Execution Endpoint
        if path.startswith("/dvwa/vulnerabilities/exec"):
            ip_val = query.get("ip", [""])[0]
            self.send_cors_and_tech_headers(200, "text/html")

            # Check for command injection separators
            is_cmd_inj = any(sep in ip_val for sep in (";", "|", "&", "`", "$("))

            output = ""
            if is_cmd_inj:
                output = """PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.
64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.031 ms
--- 127.0.0.1 ping statistics ---
1 packets transmitted, 1 received, 0% packet loss

[Command Injection Result]:
uid=33(www-data) gid=33(www-data) groups=33(www-data)
Linux dvwa-target 5.4.0-80-generic #90-Ubuntu SMP Fri Jul 9 22:49:40 UTC 2021 x86_64
"""
            else:
                output = f"""PING {ip_val} (127.0.0.1) 56(84) bytes of data.
64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=0.035 ms
1 packets transmitted, 1 received, 0% packet loss"""

            body = f"<html><body><h2>Ping Utility</h2><pre>{output}</pre></body></html>"
            self.wfile.write(body.encode("utf-8"))
            return

        # 7. File Inclusion / Path Traversal Endpoint
        if path.startswith("/dvwa/vulnerabilities/fi"):
            page_val = query.get("page", [""])[0]
            self.send_cors_and_tech_headers(200, "text/html")

            if ".." in page_val or "etc/passwd" in page_val or "passwd" in page_val:
                body = """<html><body>
<h2>File Inclusion Vulnerability Discovered</h2>
<pre>
root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
bin:x:2:2:bin:/bin:/usr/sbin/nologin
sys:x:3:3:sys:/dev:/usr/sbin/nologin
sync:x:4:65534:sync:/bin:/bin/sync
games:x:5:60:games:/usr/games:/usr/sbin/nologin
man:x:6:12:man:/var/cache/man:/usr/sbin/nologin
lp:x:7:7:lp:/var/spool/lpd:/usr/sbin/nologin
mail:x:8:8:mail:/var/mail:/usr/sbin/nologin
news:x:9:9:news:/var/spool/news:/usr/sbin/nologin
uucp:x:10:10:uucp:/var/spool/uucp:/usr/sbin/nologin
proxy:x:13:13:proxy:/bin:/usr/sbin/nologin
www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin
backup:x:34:34:backup:/var/backups:/usr/sbin/nologin
list:x:38:38:Mailing List Manager:/var/list:/usr/sbin/nologin
irc:x:39:39:ircd:/var/run/ircd:/usr/sbin/nologin
gnats:x:41:41:Gnats Bug-Reporting System (admin):/var/lib/gnats:/usr/sbin/nologin
nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin
systemd-network:x:100:102:systemd Network Management,,,:/run/systemd:/usr/sbin/nologin
systemd-resolve:x:101:103:systemd Resolver,,,:/run/systemd:/usr/sbin/nologin
messagebus:x:102:105::/nonexistent:/usr/sbin/nologin
syslog:x:103:106::/home/syslog:/usr/sbin/nologin
_apt:x:104:65534::/nonexistent:/usr/sbin/nologin
sshd:x:105:65534::/run/sshd:/usr/sbin/nologin
admin:x:1000:1000:admin,,,:/home/admin:/bin/bash
</pre>
</body></html>"""
            else:
                body = f"<html><body><h3>Viewing page: {page_val}</h3></body></html>"

            self.wfile.write(body.encode("utf-8"))
            return

        # 8. Authentication Portal (Login)
        if path.startswith("/dvwa/login.php"):
            username = query.get("username", [""])[0]
            password = query.get("password", [""])[0]
            self.send_cors_and_tech_headers(200, "text/html")

            if (username, password) in [("admin", "password"), ("admin", "admin")]:
                body = f"""<html><body>
<div class="login-success">Login SUCCESSFUL! Welcome {username} (Administrator). Authentication Token: kairo_auth_sess_90a1f</div>
</body></html>"""
            elif username:
                body = """<html><body><div class="login-failed">Login FAILED. Invalid credentials.</div></body></html>"""
            else:
                body = """<html><body>
<form action="/dvwa/login.php" method="GET">
  Username: <input type="text" name="username"><br>
  Password: <input type="password" name="password"><br>
  <input type="submit" value="Login">
</form>
</body></html>"""
            self.wfile.write(body.encode("utf-8"))
            return

        # 9. Fallback 404
        self.send_cors_and_tech_headers(404, "text/plain")
        self.wfile.write(b"404 Not Found in Kairo DVWA Target\n")

    def do_POST(self) -> None:
        # Support POST logins and testing
        content_length = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_length).decode("utf-8")
        parsed = parse_qs(post_data)

        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path.startswith("/dvwa/login.php"):
            username = parsed.get("username", [""])[0]
            password = parsed.get("password", [""])[0]
            self.send_cors_and_tech_headers(200, "text/html")

            if (username, password) in [("admin", "password"), ("admin", "admin")]:
                body = f"""<html><body><div class="login-success">Login SUCCESSFUL! Welcome {username}.</div></body></html>"""
            else:
                body = """<html><body><div class="login-failed">Login FAILED.</div></body></html>"""
            self.wfile.write(body.encode("utf-8"))
            return

        self.send_cors_and_tech_headers(200, "application/json")
        self.wfile.write(json.dumps({"status": "received", "data": post_data}).encode("utf-8"))


class MiniMetasploitableServer:
    """
    TCP multi-service socket server simulating Metasploitable 2 banners.
    Listens on port 8889 and responds with service banners depending on protocol/request:
    - FTP (vsftpd 2.3.4)
    - SSH (OpenSSH 4.7p1)
    - Apache (2.2.8 DAV)
    - MySQL (5.0.51a)
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8889):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self.is_running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(10)
            self.is_running = True
            self._thread = threading.Thread(target=self._serve_loop, daemon=True)
            self._thread.start()
            logger.info(f"MiniMetasploitable TCP service listening on {self.host}:{self.port}")
        except Exception as e:
            logger.warning(f"Could not bind MiniMetasploitable on {self.host}:{self.port}: {e}")
            self.is_running = False

    def _serve_loop(self) -> None:
        while self.is_running and self.server_socket:
            try:
                client_sock, client_addr = self.server_socket.accept()
                client_sock.settimeout(2.0)
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except Exception:
                break

    def _handle_client(self, client_sock: socket.socket) -> None:
        try:
            # Send initial composite banner representing vulnerable services
            banner = (
                "220 (vsFTPd 2.3.4)\r\n"
                "SSH-2.0-OpenSSH_4.7p1 Debian-8ubuntu1\r\n"
                "5.0.51a-3ubuntu5-log MySQL\r\n"
            )
            client_sock.sendall(banner.encode("utf-8"))

            # Read any command from probe
            try:
                data = client_sock.recv(1024).decode("utf-8", errors="ignore")
                if "USER" in data and ":)" in data:
                    # vsftpd smiley backdoor trigger simulation
                    client_sock.sendall(b"230 Backdoor trigger active on port 6200\r\n")
                elif "GET" in data or "HEAD" in data:
                    resp = (
                        "HTTP/1.1 200 OK\r\n"
                        "Server: Apache/2.2.8 (Ubuntu) DAV/2\r\n"
                        "Content-Type: text/html\r\n\r\n"
                        "<html><body>Metasploitable Lab Host (Ubuntu 8.04 LTS)</body></html>"
                    )
                    client_sock.sendall(resp.encode("utf-8"))
            except Exception:
                pass
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def stop(self) -> None:
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None


class LabTargetManager:
    """Coordinates lifecycle of all lab target services."""

    def __init__(self, host: str = "127.0.0.1", dvwa_port: int = 8888, meta_port: int = 8889):
        self.host = host
        self.dvwa_port = dvwa_port
        self.meta_port = meta_port
        self.dvwa_server: Optional[socketserver.TCPServer] = None
        self.dvwa_thread: Optional[threading.Thread] = None
        self.meta_server: Optional[MiniMetasploitableServer] = None
        self.is_active = False

    def start(self) -> None:
        if self.is_active:
            return

        # Start DVWA HTTP Server
        try:
            socketserver.TCPServer.allow_reuse_address = True
            self.dvwa_server = socketserver.TCPServer((self.host, self.dvwa_port), MiniDVWAHandler)
            self.dvwa_thread = threading.Thread(target=self.dvwa_server.serve_forever, daemon=True)
            self.dvwa_thread.start()
            logger.info(f"MiniDVWA started on http://{self.host}:{self.dvwa_port}")
        except Exception as e:
            logger.warning(f"Could not start MiniDVWA server on port {self.dvwa_port}: {e}")

        # Start Metasploitable TCP Server
        self.meta_server = MiniMetasploitableServer(host=self.host, port=self.meta_port)
        self.meta_server.start()

        self.is_active = True
        time.sleep(0.1)

    def stop(self) -> None:
        if not self.is_active:
            return

        if self.dvwa_server:
            try:
                self.dvwa_server.shutdown()
                self.dvwa_server.server_close()
            except Exception:
                pass
            self.dvwa_server = None

        if self.meta_server:
            try:
                self.meta_server.stop()
            except Exception:
                pass
            self.meta_server = None

        self.is_active = False
        logger.info("All lab targets stopped.")

    def __enter__(self) -> LabTargetManager:
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def get_endpoints(self) -> Dict[str, str]:
        return {
            "dvwa_base": f"http://{self.host}:{self.dvwa_port}",
            "dvwa_sqli": f"http://{self.host}:{self.dvwa_port}/dvwa/vulnerabilities/sqli/?id=1",
            "dvwa_exec": f"http://{self.host}:{self.dvwa_port}/dvwa/vulnerabilities/exec/?ip=127.0.0.1",
            "dvwa_fi": f"http://{self.host}:{self.dvwa_port}/dvwa/vulnerabilities/fi/?page=include.php",
            "dvwa_admin": f"http://{self.host}:{self.dvwa_port}/dvwa/admin/",
            "dvwa_secret_api": f"http://{self.host}:{self.dvwa_port}/dvwa/secret_api/",
            "dvwa_backup": f"http://{self.host}:{self.dvwa_port}/dvwa/config.bak",
            "dvwa_login": f"http://{self.host}:{self.dvwa_port}/dvwa/login.php",
            "metasploitable_tcp": f"{self.host}:{self.meta_port}",
        }


# Global singleton instance
lab_targets = LabTargetManager()
