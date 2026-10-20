"""
Backwards-compatibility alias for orchestrator.reporter_templates.

NOTICE:
This module has been renamed to `orchestrator.reporter_templates` to accurately
reflect that it is a fast, deterministic templating and formatting engine rather
than an active language-model inference pipeline.

Please import directly from `orchestrator.reporter_templates` in new code.
"""

from __future__ import annotations

from orchestrator.reporter_templates import (
    synthesize_agent_response,
    _synthesize_nmap_scan,
    _synthesize_web_audit,
    _synthesize_network_connection,
    _synthesize_domain_recon,
    _synthesize_generic_execution,
    _synthesize_scope_violation,
)

__all__ = [
    "synthesize_agent_response",
    "_synthesize_nmap_scan",
    "_synthesize_web_audit",
    "_synthesize_network_connection",
    "_synthesize_domain_recon",
    "_synthesize_generic_execution",
    "_synthesize_scope_violation",
]
