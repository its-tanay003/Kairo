"""
Evidence Store Component for Kairo.

Implements the blueprint's Artifact classes:
- Command Evidence: CLI commands, execution timing, exit codes, stdout/stderr streams
- Network Evidence: Host, ports, banners, HTTP request/response details, headers, pcaps
- File Evidence: Target paths, filenames, hashes (SHA-256), MIME types, content excerpts
- Visual Evidence: Screenshots, DOM snapshots, visual UI states, terminal frames
- Analytic Evidence: Extracted facts, critic assessments, CVE correlations, risk scores
- Report Evidence: Synthesized security reports, reproducible workflows, provenance manifests

Findings Data Model:
Each finding is represented as a structured card:
- title: Short descriptive finding title
- affected_asset: Target host, IP, URL, or component
- evidence_references: List of SHA-256 hashes or artifact references
- confidence_score: Float between 0.0 and 1.0 (or percentage)
- recovery_path: Full attempt history / recovery lineage if Task 2.4/2.5 fired
"""

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from events.db import DEFAULT_DB_PATH, Artifact, compute_sha256, get_connection, init_db, insert_artifact


class EvidenceClass(str, Enum):
    COMMAND = "command"
    NETWORK = "network"
    FILE = "file"
    VISUAL = "visual"
    ANALYTIC = "analytic"
    REPORT = "report"


@dataclass
class BaseEvidence:
    """Base class for all evidence items in the Evidence Store."""
    evidence_id: str
    title: str
    task_id: str
    evidence_class: EvidenceClass = EvidenceClass.FILE
    session_id: Optional[str] = None
    plan_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sha256: str = ""
    mime_type: str = "application/json"
    size_bytes: int = 0
    filepath: Optional[str] = None
    filename: Optional[str] = None
    parent_event_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["evidence_class"] = self.evidence_class.value
        return d


@dataclass
class CommandEvidence(BaseEvidence):
    """Artifact class for command-line execution evidence."""
    evidence_class: EvidenceClass = EvidenceClass.COMMAND
    command_line: str = ""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    process_id: Optional[int] = None
    duration_ms: Optional[float] = None
    working_dir: Optional[str] = None

    def __post_init__(self):
        self.evidence_class = EvidenceClass.COMMAND
        self.mime_type = "application/x-sh"
        self.payload = {
            "command_line": self.command_line,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "process_id": self.process_id,
            "duration_ms": self.duration_ms,
            "working_dir": self.working_dir,
        }


@dataclass
class NetworkEvidence(BaseEvidence):
    """Artifact class for network interaction and protocol inspection evidence."""
    evidence_class: EvidenceClass = EvidenceClass.NETWORK
    host: str = ""
    port: Optional[int] = None
    protocol: str = "tcp"
    service: Optional[str] = None
    banner: Optional[str] = None
    http_method: Optional[str] = None
    http_url: Optional[str] = None
    http_status: Optional[int] = None
    http_headers: Optional[Dict[str, str]] = None
    http_body_preview: Optional[str] = None
    pcap_ref: Optional[str] = None

    def __post_init__(self):
        self.evidence_class = EvidenceClass.NETWORK
        self.mime_type = "application/json"
        self.payload = {
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "service": self.service,
            "banner": self.banner,
            "http_method": self.http_method,
            "http_url": self.http_url,
            "http_status": self.http_status,
            "http_headers": self.http_headers or {},
            "http_body_preview": self.http_body_preview,
            "pcap_ref": self.pcap_ref,
        }


@dataclass
class FileEvidence(BaseEvidence):
    """Artifact class for file system artifacts, discovery wordlists, or extracted data."""
    evidence_class: EvidenceClass = EvidenceClass.FILE
    target_filepath: str = ""
    target_filename: str = ""
    file_sha256: str = ""
    content_snippet: Optional[str] = None
    file_size_bytes: int = 0
    diff: Optional[str] = None

    def __post_init__(self):
        self.evidence_class = EvidenceClass.FILE
        self.mime_type = self.mime_type or "text/plain"
        self.payload = {
            "target_filepath": self.target_filepath,
            "target_filename": self.target_filename,
            "file_sha256": self.file_sha256,
            "content_snippet": self.content_snippet,
            "file_size_bytes": self.file_size_bytes,
            "diff": self.diff,
        }


@dataclass
class VisualEvidence(BaseEvidence):
    """Artifact class for visual evidence: screenshots, DOM trees, terminal captures."""
    evidence_class: EvidenceClass = EvidenceClass.VISUAL
    image_path: Optional[str] = None
    thumbnail_b64: Optional[str] = None
    dimensions: Optional[Dict[str, int]] = None
    caption: str = ""
    dom_snapshot: Optional[str] = None

    def __post_init__(self):
        self.evidence_class = EvidenceClass.VISUAL
        self.mime_type = self.mime_type or "image/png"
        self.payload = {
            "image_path": self.image_path,
            "thumbnail_b64": self.thumbnail_b64,
            "dimensions": self.dimensions or {},
            "caption": self.caption,
            "dom_snapshot": self.dom_snapshot,
        }


@dataclass
class AnalyticEvidence(BaseEvidence):
    """Artifact class for analytical deductions, parsed facts, and risk scoring."""
    evidence_class: EvidenceClass = EvidenceClass.ANALYTIC
    analytic_type: str = "critic_assessment"
    facts: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    critique_verdict: Optional[str] = None
    heuristics_matched: List[str] = field(default_factory=list)
    risk_score: Optional[float] = None

    def __post_init__(self):
        self.evidence_class = EvidenceClass.ANALYTIC
        self.mime_type = "application/json"
        self.payload = {
            "analytic_type": self.analytic_type,
            "facts": self.facts,
            "confidence": self.confidence,
            "critique_verdict": self.critique_verdict,
            "heuristics_matched": self.heuristics_matched,
            "risk_score": self.risk_score,
        }


@dataclass
class ReportEvidence(BaseEvidence):
    """Artifact class for synthesized security reports and workflow replay manifests."""
    evidence_class: EvidenceClass = EvidenceClass.REPORT
    report_title: str = ""
    format_type: str = "markdown"
    included_findings: List[str] = field(default_factory=list)
    reproducible_workflow: List[Dict[str, Any]] = field(default_factory=list)
    markdown_path: Optional[str] = None
    html_path: Optional[str] = None

    def __post_init__(self):
        self.evidence_class = EvidenceClass.REPORT
        self.mime_type = "text/markdown" if self.format_type == "markdown" else "text/html"
        self.payload = {
            "report_title": self.report_title,
            "format_type": self.format_type,
            "included_findings": self.included_findings,
            "reproducible_workflow": self.reproducible_workflow,
            "markdown_path": self.markdown_path,
            "html_path": self.html_path,
        }


@dataclass
class Finding:
    """
    Structured security finding card per blueprint specification:
    - title: Clear, concise vulnerability or finding title
    - affected_asset: Host, IP, domain, URL, or microservice
    - evidence_references: Linked evidence artifacts (SHA-256 hashes or IDs)
    - confidence_score: Reliability / validation confidence (0.0 to 1.0)
    - recovery_path: Full attempt history / recovery lineage if Task 2.4/2.5 fired
    """
    title: str
    affected_asset: str
    evidence_references: List[str] = field(default_factory=list)
    confidence_score: float = 1.0
    recovery_path: Optional[Union[str, List[Dict[str, Any]]]] = None
    id: str = field(default_factory=lambda: f"find_{uuid.uuid4().hex[:10]}")
    severity: str = "INFO"  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    description: str = ""
    remediation: str = ""
    discovering_tool: Optional[str] = None
    discovering_node_id: Optional[str] = None
    session_id: Optional[str] = None
    plan_id: Optional[str] = None
    task_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "affected_asset": self.affected_asset,
            "evidence_references": self.evidence_references,
            "confidence_score": round(self.confidence_score, 2),
            "recovery_path": self.recovery_path,
            "severity": self.severity.upper(),
            "description": self.description,
            "remediation": self.remediation,
            "discovering_tool": self.discovering_tool,
            "discovering_node_id": self.discovering_node_id,
            "session_id": self.session_id,
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Finding":
        raw_evidence = data.get("evidence_references") or []
        if isinstance(raw_evidence, str):
            try:
                raw_evidence = json.loads(raw_evidence)
            except Exception:
                raw_evidence = [raw_evidence]
        raw_tags = data.get("tags") or []
        if isinstance(raw_tags, str):
            try:
                raw_tags = json.loads(raw_tags)
            except Exception:
                raw_tags = [raw_tags]
        raw_meta = data.get("metadata") or {}
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except Exception:
                raw_meta = {}

        return cls(
            id=data.get("id") or f"find_{uuid.uuid4().hex[:10]}",
            title=data.get("title", "Untitled Finding"),
            affected_asset=data.get("affected_asset", "unknown_asset"),
            evidence_references=raw_evidence,
            confidence_score=float(data.get("confidence_score", 1.0)),
            recovery_path=data.get("recovery_path"),
            severity=data.get("severity", "INFO"),
            description=data.get("description", ""),
            remediation=data.get("remediation", ""),
            discovering_tool=data.get("discovering_tool"),
            discovering_node_id=data.get("discovering_node_id"),
            session_id=data.get("session_id"),
            plan_id=data.get("plan_id"),
            task_id=data.get("task_id"),
            created_at=data.get("created_at") or datetime.now(timezone.utc).isoformat(),
            tags=raw_tags,
            metadata=raw_meta,
        )


class EvidenceStore:
    """
    Central repository for storing, indexing, cryptographically hashing,
    and retrieving the 6 blueprint artifact classes and findings.
    """

    def __init__(
        self,
        db_path: Optional[Path | str] = None,
        artifacts_dir: Optional[Path | str] = None,
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else Path("evidence_artifacts")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensures the artifacts and findings tables exist."""
        init_db(self.db_path)
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                task_id TEXT,
                plan_id TEXT,
                title TEXT NOT NULL,
                affected_asset TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'INFO',
                confidence_score REAL NOT NULL DEFAULT 1.0,
                evidence_references TEXT NOT NULL DEFAULT '[]',
                recovery_path TEXT,
                description TEXT,
                remediation TEXT,
                discovering_tool TEXT,
                discovering_node_id TEXT,
                created_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata TEXT
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_session ON findings(session_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_plan ON findings(plan_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_asset ON findings(affected_asset);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);")
        conn.close()

    def store_evidence(self, evidence: BaseEvidence) -> BaseEvidence:
        """
        Persists an evidence object to disk, computes its SHA-256 hash,
        and registers it in the SQLite artifacts table.
        """
        filename = evidence.filename or f"evidence_{evidence.evidence_class.value}_{evidence.evidence_id}.json"
        target_path = self.artifacts_dir / filename

        # Format payload and metadata
        meta = {
            "evidence_id": evidence.evidence_id,
            "evidence_class": evidence.evidence_class.value,
            "title": evidence.title,
            "session_id": evidence.session_id,
            "plan_id": evidence.plan_id,
            "parent_event_id": evidence.parent_event_id,
            **evidence.metadata,
        }

        content_dict = {
            "evidence_id": evidence.evidence_id,
            "evidence_class": evidence.evidence_class.value,
            "title": evidence.title,
            "timestamp": evidence.timestamp,
            "task_id": evidence.task_id,
            "payload": evidence.payload,
            "metadata": meta,
        }

        # Write to disk
        content_str = json.dumps(content_dict, indent=2)
        target_path.write_text(content_str, encoding="utf-8")

        # Compute hash and size
        sha256_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
        size_bytes = len(content_str.encode("utf-8"))

        evidence.filepath = str(target_path.resolve())
        evidence.filename = filename
        evidence.sha256 = sha256_hash
        evidence.size_bytes = size_bytes
        evidence.metadata = meta

        # Insert into artifacts table
        artifact = Artifact(
            task_id=evidence.task_id,
            filename=filename,
            filepath=evidence.filepath,
            size_bytes=size_bytes,
            sha256=sha256_hash,
            mime_type=evidence.mime_type,
            created_at=evidence.timestamp,
            metadata=json.dumps(meta),
        )
        insert_artifact(artifact, self.db_path)
        return evidence

    def store_command_evidence(
        self,
        task_id: str,
        command_line: str,
        stdout: str,
        stderr: str = "",
        exit_code: int = 0,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        duration_ms: Optional[float] = None,
        parent_event_id: Optional[str] = None,
    ) -> CommandEvidence:
        """Helper to create and persist CommandEvidence."""
        ev = CommandEvidence(
            evidence_id=f"cmd_{uuid.uuid4().hex[:10]}",
            evidence_class=EvidenceClass.COMMAND,
            title=title or f"CLI: {command_line[:40]}...",
            task_id=task_id,
            session_id=session_id,
            plan_id=plan_id,
            command_line=command_line,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            duration_ms=duration_ms,
            parent_event_id=parent_event_id,
        )
        self.store_evidence(ev)
        return ev

    def store_network_evidence(
        self,
        task_id: str,
        host: str,
        port: Optional[int] = None,
        protocol: str = "tcp",
        service: Optional[str] = None,
        banner: Optional[str] = None,
        http_method: Optional[str] = None,
        http_url: Optional[str] = None,
        http_status: Optional[int] = None,
        http_headers: Optional[Dict[str, str]] = None,
        http_body_preview: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> NetworkEvidence:
        """Helper to create and persist NetworkEvidence."""
        ev = NetworkEvidence(
            evidence_id=f"net_{uuid.uuid4().hex[:10]}",
            evidence_class=EvidenceClass.NETWORK,
            title=title or f"Network: {host}{f':{port}' if port else ''}",
            task_id=task_id,
            session_id=session_id,
            plan_id=plan_id,
            host=host,
            port=port,
            protocol=protocol,
            service=service,
            banner=banner,
            http_method=http_method,
            http_url=http_url,
            http_status=http_status,
            http_headers=http_headers,
            http_body_preview=http_body_preview,
        )
        self.store_evidence(ev)
        return ev

    def store_file_evidence(
        self,
        task_id: str,
        target_filepath: str,
        content_snippet: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> FileEvidence:
        """Helper to create and persist FileEvidence."""
        p = Path(target_filepath)
        f_hash = compute_sha256(p) if p.is_file() else hashlib.sha256(b"").hexdigest()
        size_bytes = p.stat().st_size if p.is_file() else len((content_snippet or "").encode("utf-8"))

        ev = FileEvidence(
            evidence_id=f"file_{uuid.uuid4().hex[:10]}",
            evidence_class=EvidenceClass.FILE,
            title=title or f"File: {p.name}",
            task_id=task_id,
            session_id=session_id,
            plan_id=plan_id,
            target_filepath=str(p.resolve()) if p.is_file() else target_filepath,
            target_filename=p.name,
            file_sha256=f_hash,
            file_size_bytes=size_bytes,
            content_snippet=content_snippet,
        )
        self.store_evidence(ev)
        return ev

    def store_visual_evidence(
        self,
        task_id: str,
        caption: str,
        image_path: Optional[str] = None,
        thumbnail_b64: Optional[str] = None,
        dom_snapshot: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> VisualEvidence:
        """Helper to create and persist VisualEvidence."""
        ev = VisualEvidence(
            evidence_id=f"vis_{uuid.uuid4().hex[:10]}",
            evidence_class=EvidenceClass.VISUAL,
            title=title or f"Visual: {caption[:40]}",
            task_id=task_id,
            session_id=session_id,
            plan_id=plan_id,
            caption=caption,
            image_path=image_path,
            thumbnail_b64=thumbnail_b64,
            dom_snapshot=dom_snapshot,
        )
        self.store_evidence(ev)
        return ev

    def store_analytic_evidence(
        self,
        task_id: str,
        analytic_type: str,
        facts: Dict[str, Any],
        confidence: float = 1.0,
        critique_verdict: Optional[str] = None,
        heuristics_matched: Optional[List[str]] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> AnalyticEvidence:
        """Helper to create and persist AnalyticEvidence."""
        ev = AnalyticEvidence(
            evidence_id=f"ana_{uuid.uuid4().hex[:10]}",
            evidence_class=EvidenceClass.ANALYTIC,
            title=title or f"Analytic: {analytic_type}",
            task_id=task_id,
            session_id=session_id,
            plan_id=plan_id,
            analytic_type=analytic_type,
            facts=facts,
            confidence=confidence,
            critique_verdict=critique_verdict,
            heuristics_matched=heuristics_matched or [],
        )
        self.store_evidence(ev)
        return ev

    def store_finding(self, finding: Finding) -> Finding:
        """Persists a Finding card into the SQLite findings table."""
        self._ensure_tables()
        conn = get_connection(self.db_path)
        query = """
        INSERT OR REPLACE INTO findings (
            id, session_id, task_id, plan_id, title, affected_asset, severity,
            confidence_score, evidence_references, recovery_path, description,
            remediation, discovering_tool, discovering_node_id, created_at, tags, metadata
        ) VALUES (
            :id, :session_id, :task_id, :plan_id, :title, :affected_asset, :severity,
            :confidence_score, :evidence_references, :recovery_path, :description,
            :remediation, :discovering_tool, :discovering_node_id, :created_at, :tags, :metadata
        )
        """
        recovery_path_serialized = (
            finding.recovery_path
            if isinstance(finding.recovery_path, str)
            else json.dumps(finding.recovery_path) if finding.recovery_path is not None
            else None
        )

        data = {
            "id": finding.id,
            "session_id": finding.session_id or "default_session",
            "task_id": finding.task_id,
            "plan_id": finding.plan_id,
            "title": finding.title,
            "affected_asset": finding.affected_asset,
            "severity": finding.severity.upper(),
            "confidence_score": float(finding.confidence_score),
            "evidence_references": json.dumps(finding.evidence_references),
            "recovery_path": recovery_path_serialized,
            "description": finding.description,
            "remediation": finding.remediation,
            "discovering_tool": finding.discovering_tool,
            "discovering_node_id": finding.discovering_node_id,
            "created_at": finding.created_at,
            "tags": json.dumps(finding.tags),
            "metadata": json.dumps(finding.metadata),
        }

        with conn:
            cursor = conn.cursor()
            cursor.execute(query, data)
        conn.close()
        return finding

    def get_finding(self, finding_id: str) -> Optional[Finding]:
        """Retrieves a single finding by ID."""
        self._ensure_tables()
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM findings WHERE id = ?", (finding_id,))
            row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return Finding.from_dict(dict(row))

    def list_findings(
        self,
        session_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        affected_asset: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[Finding]:
        """Lists findings filtered by criteria."""
        self._ensure_tables()
        conn = get_connection(self.db_path)
        query = "SELECT * FROM findings WHERE 1=1"
        params: List[Any] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        if plan_id:
            query += " AND plan_id = ?"
            params.append(plan_id)
        if affected_asset:
            query += " AND affected_asset LIKE ?"
            params.append(f"%{affected_asset}%")
        if severity:
            query += " AND severity = ?"
            params.append(severity.upper())
        query += " ORDER BY created_at DESC"

        with conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return [Finding.from_dict(r) for r in rows]

    def resolve_evidence_references(self, refs: List[str]) -> List[Dict[str, Any]]:
        """
        Resolves a list of evidence references (which may be SHA-256 hashes,
        artifact IDs, or evidence filenames) into structured evidence objects.
        """
        resolved: List[Dict[str, Any]] = []
        if not refs:
            return resolved

        self._ensure_tables()
        conn = get_connection(self.db_path)
        with conn:
            cursor = conn.cursor()
            for ref in refs:
                cleaned_ref = ref.replace("sha256:", "").strip()
                # Try finding by SHA-256
                cursor.execute("SELECT * FROM artifacts WHERE sha256 = ? OR sha256 LIKE ?", (cleaned_ref, f"{cleaned_ref}%"))
                row = cursor.fetchone()
                if not row:
                    # Try finding by filename
                    cursor.execute("SELECT * FROM artifacts WHERE filename = ? OR filepath = ?", (cleaned_ref, cleaned_ref))
                    row = cursor.fetchone()

                if row:
                    art_dict = dict(row)
                    # Check if file still exists on disk
                    fpath = Path(art_dict["filepath"])
                    content_preview = None
                    if fpath.is_file():
                        try:
                            raw_txt = fpath.read_text(encoding="utf-8", errors="replace")
                            try:
                                parsed = json.loads(raw_txt)
                                art_dict["parsed_content"] = parsed
                                content_preview = json.dumps(parsed.get("payload") or parsed, indent=2)[:500]
                            except Exception:
                                content_preview = raw_txt[:500]
                        except Exception:
                            content_preview = "[Binary or unreadable file]"

                    art_dict["preview"] = content_preview
                    resolved.append(art_dict)
                else:
                    # Unmatched reference placeholder
                    resolved.append({
                        "sha256": cleaned_ref,
                        "filename": ref,
                        "status": "unresolved_hash",
                        "size_bytes": 0,
                    })
        conn.close()
        return resolved

    def auto_ingest_from_node_result(
        self,
        plan_id: str,
        node_id: str,
        tool: str,
        result_data: Dict[str, Any],
        session_id: Optional[str] = None,
        target_asset: Optional[str] = None,
    ) -> List[Finding]:
        """
        Automatically translates cognitive engine node execution results
        into typed Evidence instances and structured Finding cards.
        Attaches the full recovery narrative / path from Task 2.4/2.5.
        """
        findings: List[Finding] = []
        facts = result_data.get("facts") or {}
        attempts = int(result_data.get("attempts") or 1)
        recovery_narrative = result_data.get("recovery_narrative")
        recovery_path = result_data.get("recovery_path")
        task_id = f"plan_{plan_id}_{node_id}"

        # 1. Store Command/Execution Evidence
        cmd_ev = self.store_command_evidence(
            task_id=task_id,
            command_line=result_data.get("command_executed") or f"{tool} execution",
            stdout=result_data.get("raw_stdout") or result_data.get("summary") or "Execution completed",
            stderr=result_data.get("raw_stderr", ""),
            exit_code=int(result_data.get("exit_code", 0)),
            title=f"Node {node_id} ({tool}) Execution Evidence",
            session_id=session_id,
            plan_id=plan_id,
        )

        # 2. Ingest Open Ports -> Network Evidence & Findings
        for port_info in facts.get("ports", []):
            p_num = port_info.get("port")
            p_svc = port_info.get("service", "unknown")
            asset = target_asset or port_info.get("host") or "127.0.0.1"

            net_ev = self.store_network_evidence(
                task_id=task_id,
                host=asset,
                port=p_num,
                service=p_svc,
                banner=port_info.get("banner"),
                title=f"Open Port {p_num}/{p_svc} on {asset}",
                session_id=session_id,
                plan_id=plan_id,
            )

            finding = Finding(
                title=f"Open Service: {p_svc.upper()} on Port {p_num}",
                affected_asset=f"{asset}:{p_num}",
                evidence_references=[f"sha256:{net_ev.sha256}", f"sha256:{cmd_ev.sha256}"],
                confidence_score=0.95,
                recovery_path=recovery_narrative if attempts > 1 else None,
                severity="LOW" if p_num in (80, 443) else "MEDIUM",
                description=f"Port {p_num} is active and exposing service '{p_svc}'.",
                remediation=f"Ensure access to port {p_num} is restricted to authorized IP ranges.",
                discovering_tool=tool,
                discovering_node_id=node_id,
                session_id=session_id,
                plan_id=plan_id,
                task_id=task_id,
                tags=["network", "port_scan", p_svc],
            )
            self.store_finding(finding)
            findings.append(finding)

        # 3. Ingest Endpoints -> File/Network Evidence & Findings
        for ep_info in facts.get("endpoints", []):
            path = ep_info.get("path") or ep_info.get("url")
            status = ep_info.get("status", 200)
            asset = target_asset or "127.0.0.1"

            net_ev = self.store_network_evidence(
                task_id=task_id,
                host=asset,
                http_method="GET",
                http_url=f"http://{asset}{path}",
                http_status=status,
                title=f"Endpoint {path} (HTTP {status})",
                session_id=session_id,
                plan_id=plan_id,
            )

            is_sensitive = any(k in path.lower() for k in ["admin", "login", "api", "config", "backup", "secret"])
            severity = "HIGH" if is_sensitive else "LOW"

            finding = Finding(
                title=f"Discovered Web Path: {path}",
                affected_asset=f"http://{asset}{path}",
                evidence_references=[f"sha256:{net_ev.sha256}", f"sha256:{cmd_ev.sha256}"],
                confidence_score=0.92,
                recovery_path=recovery_narrative if attempts > 1 else None,
                severity=severity,
                description=f"Discovered accessible HTTP resource at '{path}' with status code {status}.",
                remediation="Verify authentication and access control policies on this route.",
                discovering_tool=tool,
                discovering_node_id=node_id,
                session_id=session_id,
                plan_id=plan_id,
                task_id=task_id,
                tags=["web", "directory_fuzz", "endpoint"],
            )
            self.store_finding(finding)
            findings.append(finding)

        # 4. Ingest Vulnerabilities -> Analytic Evidence & Findings
        for vuln in facts.get("vulnerabilities", []):
            v_title = vuln.get("type") or vuln.get("id") or "Security Vulnerability"
            severity = vuln.get("severity", "HIGH").upper()
            asset = target_asset or vuln.get("target") or "127.0.0.1"

            ana_ev = self.store_analytic_evidence(
                task_id=task_id,
                analytic_type="vulnerability_assessment",
                facts=vuln,
                confidence=float(vuln.get("confidence", 0.90)),
                title=f"Vulnerability Analysis: {v_title}",
                session_id=session_id,
                plan_id=plan_id,
            )

            finding = Finding(
                title=f"{severity}: {v_title}",
                affected_asset=asset,
                evidence_references=[f"sha256:{ana_ev.sha256}", f"sha256:{cmd_ev.sha256}"],
                confidence_score=float(vuln.get("confidence", 0.90)),
                recovery_path=recovery_narrative if attempts > 1 else None,
                severity=severity,
                description=vuln.get("description", f"Identified {v_title} affecting target asset."),
                remediation=vuln.get("remediation", "Apply vendor security patch or adjust input sanitization."),
                discovering_tool=tool,
                discovering_node_id=node_id,
                session_id=session_id,
                plan_id=plan_id,
                task_id=task_id,
                tags=["vulnerability", severity.lower()],
            )
            self.store_finding(finding)
            findings.append(finding)

        return findings


# Global EvidenceStore instance
evidence_store = EvidenceStore()
