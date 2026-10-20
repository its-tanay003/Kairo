"""
Trustworthy Finding Verification Engine for Kairo.

Performs authorized, scope-gated active verification of discovered security findings:
- Enforces active ScopeContract boundary before emitting verification probes.
- Executes TCP handshake probes to confirm open ports without relying on hearsay.
- Probes HTTP/HTTPS endpoints for service reachability, headers, and status codes.
- Captures service banners directly from sockets.
- Updates finding verification status, confidence score, and attaches AnalyticEvidence artifacts.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from events.db import (
    DEFAULT_DB_PATH,
    extract_host_from_target,
    get_active_scope_contract,
    is_target_in_scope,
)
from orchestrator.evidence_store import (
    EvidenceStore,
    Finding,
)

logger = logging.getLogger("orchestrator.finding_verifier")


class FindingVerifier:
    """
    Authorized finding verification engine.
    Ensures findings are confirmed via real network checks, not assumed or fabricated.
    """

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        evidence_store: Optional[EvidenceStore] = None,
        default_timeout: float = 3.0,
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.evidence_store = evidence_store or EvidenceStore(db_path=self.db_path)
        self.default_timeout = default_timeout

    def is_authorized_target(
        self,
        target: str,
        allowed_targets: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Validates target against authorized ScopeContract boundary.
        Returns (is_allowed, reason).
        """
        if not target:
            return False, "Target is empty or undefined"

        if allowed_targets is None:
            active_contract = get_active_scope_contract(self.db_path)
            if active_contract and "targets" in active_contract:
                allowed_targets = active_contract.get("targets", [])
            else:
                # Default permitted targets if no strict contract loaded
                allowed_targets = ["127.0.0.1", "localhost", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]

        clean_host = extract_host_from_target(target) or target
        if is_target_in_scope(clean_host, allowed_targets):
            return True, f"Target '{clean_host}' is permitted within active ScopeContract."
        return False, f"Target '{clean_host}' is outside authorized ScopeContract {allowed_targets}."

    def verify_open_port(
        self,
        host: str,
        port: int,
        timeout: Optional[float] = None,
        allowed_targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Verifies whether a TCP port is truly listening via a live socket connection.
        """
        timeout = timeout or self.default_timeout
        clean_host = extract_host_from_target(host) or host

        # Scope Check
        is_auth, auth_msg = self.is_authorized_target(clean_host, allowed_targets)
        if not is_auth:
            return {
                "verified": False,
                "verification_status": "blocked_out_of_scope",
                "method": "tcp_syn_handshake",
                "host": clean_host,
                "port": port,
                "reason": auth_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        t0 = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((clean_host, int(port)))
            latency_ms = round((time.time() - t0) * 1000, 2)
            s.close()
            return {
                "verified": True,
                "verification_status": "verified",
                "method": "tcp_syn_handshake",
                "host": clean_host,
                "port": int(port),
                "latency_ms": latency_ms,
                "details": f"TCP connection successfully established to {clean_host}:{port} in {latency_ms}ms.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except (ConnectionRefusedError, socket.timeout, OSError) as e:
            latency_ms = round((time.time() - t0) * 1000, 2)
            try:
                s.close()
            except Exception:
                pass
            return {
                "verified": False,
                "verification_status": "refuted",
                "method": "tcp_syn_handshake",
                "host": clean_host,
                "port": int(port),
                "latency_ms": latency_ms,
                "details": f"Port {port} connection refused or timed out ({e}).",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def verify_web_endpoint(
        self,
        url: str,
        timeout: Optional[float] = None,
        expected_status: Optional[int] = None,
        allowed_targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Verifies web service reachability and inspects HTTP response status & headers.
        """
        timeout = timeout or self.default_timeout
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"http://{url}"

        parsed = urllib.parse.urlparse(url)
        clean_host = parsed.hostname or url

        # Scope Check
        is_auth, auth_msg = self.is_authorized_target(clean_host, allowed_targets)
        if not is_auth:
            return {
                "verified": False,
                "verification_status": "blocked_out_of_scope",
                "method": "http_probe",
                "url": url,
                "reason": auth_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        t0 = time.time()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Kairo-Verification-Engine/1.0 (Authorized Audit)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.getcode()
                headers = dict(resp.headers)
                latency_ms = round((time.time() - t0) * 1000, 2)
                is_match = (expected_status is None) or (status_code == expected_status)
                return {
                    "verified": is_match,
                    "verification_status": "verified" if is_match else "inconclusive",
                    "method": "http_probe",
                    "url": url,
                    "status_code": status_code,
                    "headers": {k: str(v) for k, v in list(headers.items())[:10]},
                    "latency_ms": latency_ms,
                    "details": f"HTTP {status_code} received from {url} in {latency_ms}ms.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        except urllib.error.HTTPError as e:
            # An HTTP response (401, 403, 404, 500) proves the web server is alive and operating!
            latency_ms = round((time.time() - t0) * 1000, 2)
            headers = dict(e.headers) if hasattr(e, "headers") else {}
            is_match = (expected_status is None) or (e.code == expected_status)
            return {
                "verified": is_match,
                "verification_status": "verified" if is_match else "inconclusive",
                "method": "http_probe",
                "url": url,
                "status_code": e.code,
                "headers": {k: str(v) for k, v in list(headers.items())[:10]},
                "latency_ms": latency_ms,
                "details": f"HTTP error {e.code} ({e.reason}) confirmed active endpoint at {url}.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except (urllib.error.URLError, socket.timeout, ConnectionRefusedError, OSError) as e:
            latency_ms = round((time.time() - t0) * 1000, 2)
            return {
                "verified": False,
                "verification_status": "refuted",
                "method": "http_probe",
                "url": url,
                "latency_ms": latency_ms,
                "details": f"Failed to connect to web endpoint {url}: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def verify_service_banner(
        self,
        host: str,
        port: int,
        expected_service: Optional[str] = None,
        timeout: Optional[float] = None,
        allowed_targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Connects to a service and captures its raw introductory banner.
        """
        timeout = timeout or self.default_timeout
        clean_host = extract_host_from_target(host) or host

        # Scope Check
        is_auth, auth_msg = self.is_authorized_target(clean_host, allowed_targets)
        if not is_auth:
            return {
                "verified": False,
                "verification_status": "blocked_out_of_scope",
                "method": "service_banner",
                "host": clean_host,
                "port": port,
                "reason": auth_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        t0 = time.time()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        banner = ""
        try:
            s.connect((clean_host, int(port)))
            # If standard web port, send minimal HTTP request
            if int(port) in (80, 8080, 8000, 3000, 5000):
                s.sendall(f"HEAD / HTTP/1.0\r\nHost: {clean_host}\r\n\r\n".encode("utf-8"))
            raw = s.recv(1024)
            banner = raw.decode("utf-8", errors="replace").strip()
            latency_ms = round((time.time() - t0) * 1000, 2)
            s.close()

            matches = True
            if expected_service and expected_service.lower() not in banner.lower():
                matches = False

            return {
                "verified": matches,
                "verification_status": "verified" if matches else "inconclusive",
                "method": "service_banner",
                "host": clean_host,
                "port": int(port),
                "banner": banner[:250],
                "expected_service": expected_service,
                "latency_ms": latency_ms,
                "details": f"Captured banner: {banner[:100]}...",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            try:
                s.close()
            except Exception:
                pass
            return {
                "verified": False,
                "verification_status": "refuted",
                "method": "service_banner",
                "host": clean_host,
                "port": int(port),
                "details": f"Banner capture failed: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def verify_finding(
        self,
        finding: Optional[Union[Finding, str]] = None,
        allowed_targets: Optional[List[str]] = None,
        finding_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes targeted, authorized verification check for a finding and records result.
        Updates the finding in EvidenceStore and stores AnalyticEvidence proof.
        """
        target_f = finding or finding_id
        if target_f is None:
            return {"error": "No finding or finding_id provided for verification", "status": "error"}

        if isinstance(target_f, str):
            f_obj = self.evidence_store.get_finding(target_f)
            if not f_obj:
                return {
                    "error": f"Finding '{target_f}' not found in evidence store",
                    "status": "not_found",
                }
        else:
            f_obj = target_f

        asset = f_obj.affected_asset or "127.0.0.1"
        tool = (f_obj.discovering_tool or "").lower()
        title = (f_obj.title or "").lower()
        desc = (f_obj.description or "").lower()

        # Scope Check
        clean_host = extract_host_from_target(asset) or asset
        is_auth, auth_msg = self.is_authorized_target(clean_host, allowed_targets)
        if not is_auth:
            f_obj.verified = False
            f_obj.verification_status = "blocked_out_of_scope"
            f_obj.verification_details = {
                "reason": auth_msg,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            f_obj.verified_at = datetime.now(timezone.utc).isoformat()
            self.evidence_store.store_finding(f_obj)
            return {
                "finding_id": f_obj.id,
                "verified": False,
                "verification_status": "blocked_out_of_scope",
                "reason": auth_msg,
            }

        # Determine Verification Method
        port_match = re.search(r":(\d+)", asset) or re.search(r"port\s+(\d+)", title) or re.search(r"port\s+(\d+)", desc)
        extracted_port = int(port_match.group(1)) if port_match else None

        probe_result: Dict[str, Any]

        if "http" in asset or "url" in asset or "web" in tool or "zap" in tool or "nikto" in tool or "burp" in tool:
            probe_result = self.verify_web_endpoint(asset, allowed_targets=allowed_targets)
        elif extracted_port:
            probe_result = self.verify_open_port(clean_host, extracted_port, allowed_targets=allowed_targets)
        elif "nmap" in tool or "port" in title:
            # Check port 80 as baseline if no port parsed
            probe_result = self.verify_open_port(clean_host, extracted_port or 80, allowed_targets=allowed_targets)
        else:
            # Fallback to ICMP/TCP probe on host
            probe_result = self.verify_open_port(clean_host, 80, timeout=1.5, allowed_targets=allowed_targets)
            if not probe_result["verified"]:
                probe_result = self.verify_open_port(clean_host, 443, timeout=1.5, allowed_targets=allowed_targets)

        # Update finding status & confidence score based on verification proof
        verified = bool(probe_result.get("verified"))
        status = str(probe_result.get("verification_status", "inconclusive"))

        if verified:
            confidence = min(1.0, f_obj.confidence_score + 0.15) if f_obj.confidence_score < 1.0 else 0.99
        elif status == "refuted":
            confidence = max(0.1, f_obj.confidence_score - 0.5)
        else:
            confidence = f_obj.confidence_score

        f_obj.verified = verified
        f_obj.verification_status = status
        f_obj.verification_details = probe_result
        f_obj.confidence_score = confidence
        f_obj.verified_at = datetime.now(timezone.utc).isoformat()

        # Persist Analytic Evidence Artifact
        try:
            ev = self.evidence_store.store_analytic_evidence(
                task_id=f_obj.task_id or f"verif_{f_obj.id}",
                analytic_type="independent_verification",
                facts=probe_result,
                confidence=confidence,
                critique_verdict="CONFIRMED" if verified else ("REFUTED" if status == "refuted" else "INCONCLUSIVE"),
                title=f"Verification: {f_obj.title[:30]} ({status})",
                session_id=f_obj.session_id,
                plan_id=f_obj.plan_id,
            )
            if ev.sha256 and ev.sha256 not in f_obj.evidence_references:
                f_obj.evidence_references.append(ev.sha256)
        except Exception as e:
            logger.warning(f"Could not persist analytic verification evidence: {e}")

        # Update Finding in Database
        self.evidence_store.store_finding(f_obj)

        return {
            "finding_id": f_obj.id,
            "title": f_obj.title,
            "affected_asset": f_obj.affected_asset,
            "verified": verified,
            "verification_status": status,
            "confidence_score": round(confidence, 2),
            "verification_details": probe_result,
            "verified_at": f_obj.verified_at,
        }
