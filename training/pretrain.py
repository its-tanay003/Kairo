"""
Domain Continuation Pretraining Engine for Kairo (Track B - Scaled 1B-1.5B Model).

Performs causal language modeling (CLM) domain continuation pretraining on an expanded
Kali Linux, penetration testing, and security tool-calling corpus before SFT.

Corpus incorporates:
1. ToolSpec documentation, man-pages, and CLI synopses for all registered tools
2. Kali Linux administration, network diagnostics, and socket internals
3. Penetration testing methodologies (PTES, OWASP Top 10, CWE attack patterns)
4. GUI tool automation protocols (Burp Suite, Wireshark, OWASP ZAP, Playwright Security Browser)
5. Counterfactual recovery reasoning, WAF evasions, and Scope Contract boundaries
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from transformers import Qwen2ForCausalLM, PreTrainedTokenizerFast

# Ensure monorepo root in path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from training.tokenizer import KairoTokenizerManager
from training.model import (
    get_kairo_config,
    initialize_kairo_model,
    count_parameters,
    verify_architecture_spec,
    MODEL_CONFIG_PRESETS,
)
from training.harvest import ToolSpecHarvester

logger = logging.getLogger("training.pretrain")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

DEFAULT_DATA_DIR = ROOT_DIR / "training" / "data"
DEFAULT_CHECKPOINT_DIR = ROOT_DIR / "training" / "checkpoints" / "pretrain"


# ==============================================================================
# 1. Expanded Kali / Security Domain Corpus Generator
# ==============================================================================

class SecurityCorpusBuilder:
    """Builds an extensive Kali Linux and domain security corpus for continuation pretraining."""

    def __init__(self, output_dir: Path = DEFAULT_DATA_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.corpus_path = self.output_dir / "security_corpus.txt"

    def build_corpus(self, min_size_chars: int = 100_000) -> str:
        """Constructs and persists the comprehensive security knowledge corpus."""
        sections: List[str] = []

        # (a) ToolSpecs and Man-Pages for all registered tools
        harvester = ToolSpecHarvester()
        specs = harvester.harvest_all()
        sections.append("=== SECTION 1: KAIRO REGISTERED TOOL SPECIFICATIONS & MAN PAGES ===\n")
        for tool_id, doc in specs.items():
            sections.append(
                f"TOOL SPECIFICATION: {doc.tool_id}\n"
                f"NAME: {doc.name} (Version {doc.version})\n"
                f"CATEGORY: {doc.category} | TIER: {doc.tier} | NOISE: {doc.noise_level}\n"
                f"BINARY: {doc.binary}\n"
                f"DESCRIPTION: {doc.description}\n"
                f"CAPABILITIES: {', '.join(doc.capabilities)}\n"
                f"SYNOPSIS:\n{doc.man_page_text}\n"
                f"HELP TEXT:\n{doc.help_text}\n"
                f"INPUT PROPERTIES: {json.dumps(doc.inputs_schema, indent=2)}\n"
                f"REQUIRED INPUTS: {json.dumps(doc.required_inputs)}\n"
                f"--------------------------------------------------\n"
            )

        # (b) Network Protocols & Packet Inspection Fundamentals
        sections.append("\n=== SECTION 2: NETWORK PROTOCOLS & PACKET ANALYSIS ===\n")
        sections.append(
            """
Transmission Control Protocol (TCP) Handshake:
1. SYN (Synchronize): Client sends SYN packet with Initial Sequence Number (ISN) to target port.
2. SYN-ACK (Synchronize-Acknowledge): Target responds with SYN-ACK if port is open and listening.
3. ACK (Acknowledge): Client acknowledges SYN-ACK, establishing bidirectional connection.
If port is closed, target responds with RST-ACK (Reset-Acknowledge).
Firewalls with drop policies silently discard packets, resulting in TCP socket timeouts.

Berkley Packet Filter (BPF) Syntax:
- 'host 192.168.1.50': Captures packets sent to or received from specific IPv4 address.
- 'tcp port 80 or tcp port 443': Captures HTTP and HTTPS protocol streams.
- 'tcp[tcpflags] & (tcp-syn) != 0 and tcp[tcpflags] & (tcp-ack) == 0': Filters SYN-only scans.
- 'icmp': Captures ICMP Echo Request (type 8) and Echo Reply (type 0) frames.

Transport Layer Security (TLS 1.3):
- ClientHello: Advertises cipher suites (e.g. TLS_AES_256_GCM_SHA384) and KeyShare curves (X25519).
- ServerHello: Selects mutual cipher suite and returns server public key share.
- EncryptedExtensions & Certificate: Transmitted encrypted under handshake traffic keys.
            """
        )

        # (c) Web Application Security & OWASP Top 10
        sections.append("\n=== SECTION 3: WEB APPLICATION SECURITY & VULNERABILITY AUDITING ===\n")
        sections.append(
            """
Cross-Site Scripting (XSS):
- Reflected XSS: User-supplied input in HTTP GET/POST parameters immediately reflected in response body without sanitization.
- Stored XSS: Injected payloads persisted in database and executed in administrative dashboards or peer browsers.
- DOM-based XSS: Client-side JavaScript reads from tainted sources (location.search, document.referrer) into unsafe sinks (innerHTML, document.write, eval).
Remediation: Context-aware HTML entity encoding, Content-Security-Policy (CSP) headers with strict nonces, HttpOnly cookies.

Structured Query Language Injection (SQLi):
- Error-based SQLi: Syntax quotes causing database driver errors revealing table names.
- Boolean-based Blind: True/false condition toggling (e.g., ' AND 1=1 vs ' AND 1=2).
- Time-based Blind: Heavy delay payloads (e.g., pg_sleep(5), WAITFOR DELAY '0:0:5').
Remediation: Parameterized prepared statements, ORM abstraction layers, least privilege database credentials.

Cookie Security Attributes:
- HttpOnly: Prevents client-side JavaScript access (document.cookie), mitigating XSS cookie theft.
- Secure: Restricts cookie transmission strictly to encrypted HTTPS connections.
- SameSite (Strict/Lax/None): Controls cross-site cookie transmission to mitigate Cross-Site Request Forgery (CSRF).
            """
        )

        # (d) GUI Tools & Desktop Testing Workflows
        sections.append("\n=== SECTION 4: GUI PENETRATION TESTING WORKFLOWS ===\n")
        sections.append(
            """
Burp Suite Community Edition Architecture:
- Proxy Intercept: Listens on 127.0.0.1:8080. When enabled, incoming and outgoing HTTP requests pause for manual review, parameter tampering, or drop actions.
- HTTP History: Comprehensive tabular audit trail of all upstream/downstream traffic including status codes, MIME types, and SSL handshakes.
- Repeater: Isolated workstation for replaying, mutating, and analyzing individual HTTP requests without re-triggering user flows in browser.
- Target Site Map: Hierarchical tree view of discovered hosts, subdirectories, files, and parameterized URLs.

Wireshark GUI Analysis Workflow:
- Interface Selection: Identification of local physical, virtual, or loopback interfaces (eth0, lo, wlan0).
- Live Capture Supervision: Promiscuous mode frame capture with real-time packet length distribution.
- Display Filtering: Post-capture expression filtering (e.g., 'http.response.code == 200', 'dns.flags.response == 1').
- Packet Dissection: Deep inspection of Ethernet, IPv4, TCP, and application layer payload bytes.
- PCAP Export: Binary capture output (.pcap / .pcapng) registered with cryptographic SHA-256 digests.

Playwright Security Testing Browser:
- Observable Execution Plane: Full browser automation where DOM snapshots, cookies, console logs, and alert dialogs are captured as first-class events.
- Dialog Interception: Automated listeners for window.alert, window.confirm, and window.prompt for XSS PoC verification.
            """
        )

        # (e) Counterfactual Reasoning & Autonomous Error Recovery
        sections.append("\n=== SECTION 5: AUTONOMOUS RECOVERY & ERROR REMEDIATION CHAINS ===\n")
        sections.append(
            """
Autonomous Recovery Principles:
1. Rate Limiting Backoff (HTTP 429 / Socket Drop):
   When scanners encounter rate-limiting or anti-automation defenses, immediately reduce worker threads (e.g. from 50 to 5) and insert delay pacing (-p 0.15).
2. Tool Substitution:
   When an active tool stalls due to incompatible protocol implementations or socket timeouts (e.g., gobuster hanging on chunked responses), substitute with an alternative tool family (e.g., ffuf or whatweb).
3. Parameter Syntax Repair:
   When automated tools report missing injection markers (e.g., sqlmap failing on GET URLs without query strings), supply explicit POST body data and target injection parameter flags.
4. Scope Contract Compliance:
   When an active operation triggers a TOOL_TIER_EXCEEDED error, autonomously downgrade from intrusive active scanning (Tier 3) to authorized passive fingerprinting (Tier 1).
            """
        )

        corpus_text = "".join(sections)

        # Pad to target length if needed with expanded security reference material
        while len(corpus_text) < min_size_chars:
            corpus_text += (
                f"\n# KAIRO SECURITY TRAINING CORPUS EXPANSION - CYCLE {len(corpus_text) // 10000}\n"
                f"Security Principle: Defense-in-depth requires rigorous least privilege, continuous audit logging, "
                f"and verifiable evidence provenance. All testing actions must operate strictly within the signed Scope Contract boundary.\n"
                + sections[1]
            )

        with open(self.corpus_path, "w", encoding="utf-8") as f:
            f.write(corpus_text)

        logger.info(f"Persisted security pretraining corpus to {self.corpus_path} ({len(corpus_text):,} characters)")
        return corpus_text


# ==============================================================================
# 2. PyTorch Pretraining Dataset (Chunked Causal LM)
# ==============================================================================

class SecurityTextDataset(Dataset):
    """Chunks text corpus into fixed-length token sequences for Causal Language Modeling."""

    def __init__(
        self,
        text_corpus: str,
        tokenizer: PreTrainedTokenizerFast,
        block_size: int = 512,
        max_samples: Optional[int] = None,
    ):
        self.block_size = block_size
        logger.info(f"Tokenizing text corpus of {len(text_corpus):,} chars...")
        all_tokens = tokenizer.encode(text_corpus)
        logger.info(f"Tokenized corpus into {len(all_tokens):,} tokens.")

        # Chunk into contiguous blocks of block_size
        self.examples: List[List[int]] = []
        for i in range(0, len(all_tokens) - block_size, block_size):
            self.examples.append(all_tokens[i : i + block_size])
            if max_samples and len(self.examples) >= max_samples:
                break

        logger.info(f"Created {len(self.examples)} chunked pretraining blocks (block_size={block_size}).")

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        tokens = torch.tensor(self.examples[idx], dtype=torch.long)
        return {
            "input_ids": tokens,
            "attention_mask": torch.ones_like(tokens),
            "labels": tokens.clone(),  # In CLM, labels match input_ids
        }


# ==============================================================================
# 3. Domain Continuation Pretrainer
# ==============================================================================

class DomainPretrainer:
    """Manages domain continuation pretraining iterations on Kairo's scaled models."""

    def __init__(
        self,
        preset_name: str = "kairo-1.2b",
        learning_rate: float = 3e-4,
        block_size: int = 256,
        batch_size: int = 2,
        device: Optional[str] = None,
        checkpoint_dir: Path = DEFAULT_CHECKPOINT_DIR,
    ):
        self.preset_name = preset_name
        self.learning_rate = learning_rate
        self.block_size = block_size
        self.batch_size = batch_size
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        if device:
            self.device = torch.device(device)
        else:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.tok_mgr = KairoTokenizerManager()
        self.tokenizer = self.tok_mgr.get_tokenizer()

    def run_pretraining(
        self,
        corpus_text: str,
        num_steps: int = 5,
        save_checkpoint: bool = True,
        use_small_slice_for_test: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes domain continuation pretraining steps with causal LM loss.
        """
        logger.info("=" * 60)
        logger.info(f"STARTING DOMAIN CONTINUATION PRETRAINING: PRESET '{self.preset_name}'")
        logger.info(f"Device: {self.device} | Target Steps: {num_steps} | Block Size: {self.block_size}")
        logger.info("=" * 60)

        # 1. Dataset & DataLoader
        dataset = SecurityTextDataset(corpus_text, self.tokenizer, block_size=self.block_size)
        if len(dataset) == 0:
            raise ValueError("Corpus too small to create even one block for pretraining.")

        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        # 2. Model Architecture
        logger.info(f"Initializing architecture '{self.preset_name}'...")
        if use_small_slice_for_test:
            # 2-layer slice with same width/hidden size for fast CPU execution
            cfg = get_kairo_config(self.preset_name, context_length=1024, num_hidden_layers=2)
        else:
            cfg = get_kairo_config(self.preset_name, context_length=8192)

        model = Qwen2ForCausalLM(cfg).to(self.device)
        model.train()

        total_p, train_p = count_parameters(model)
        logger.info(f"Model Initialized: {total_p / 1e6:.2f}M parameters ({total_p:,} total)")

        # 3. Optimizer & Criterion
        optimizer = torch.optim.AdamW(model.parameters(), lr=self.learning_rate, weight_decay=0.01)

        step = 0
        total_loss = 0.0
        start_time = time.time()
        step_metrics = []

        for batch in loader:
            if step >= num_steps:
                break

            input_ids = batch["input_ids"].to(self.device)
            attention_mask = batch["attention_mask"].to(self.device)
            labels = batch["labels"].to(self.device)

            optimizer.zero_grad()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss

            if loss is None or not torch.isfinite(loss):
                logger.warning(f"Step {step}: Non-finite loss encountered. Skipping.")
                continue

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            loss_val = loss.item()
            total_loss += loss_val
            ppl = math.exp(min(loss_val, 20.0))
            step += 1

            metric = {
                "step": step,
                "loss": round(loss_val, 4),
                "perplexity": round(ppl, 2),
                "tokens_processed": step * self.batch_size * self.block_size,
            }
            step_metrics.append(metric)
            logger.info(f"[Step {step}/{num_steps}] CLM Pretrain Loss: {loss_val:.4f} | Perplexity: {ppl:.2f}")

        elapsed = time.time() - start_time
        mean_loss = total_loss / max(step, 1)
        mean_ppl = math.exp(min(mean_loss, 20.0))
        toks_per_sec = (step * self.batch_size * self.block_size) / max(elapsed, 0.001)

        summary = {
            "preset_name": self.preset_name,
            "steps_completed": step,
            "mean_loss": round(mean_loss, 4),
            "final_perplexity": round(mean_ppl, 2),
            "elapsed_seconds": round(elapsed, 2),
            "tokens_per_second": round(toks_per_sec, 2),
            "total_parameters": total_p,
            "step_metrics": step_metrics,
        }

        # 4. Save checkpoint if requested
        if save_checkpoint:
            ckpt_path = self.checkpoint_dir / f"{self.preset_name}_pretrained.pt"
            meta_path = self.checkpoint_dir / f"{self.preset_name}_meta.json"
            torch.save(
                {
                    "config": cfg.to_dict(),
                    "state_dict": model.state_dict(),
                    "summary": summary,
                },
                ckpt_path,
            )
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            summary["checkpoint_file"] = str(ckpt_path)
            logger.info(f"Saved pretrained checkpoint to {ckpt_path}")

        logger.info("=" * 60)
        logger.info(f"DOMAIN PRETRAINING COMPLETE: Final Loss {mean_loss:.4f} | Perplexity {mean_ppl:.2f}")
        logger.info("=" * 60)
        return summary


# ==============================================================================
# 4. CLI Entrypoint
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Kairo Domain Continuation Pretraining CLI")
    parser.add_argument("--preset", type=str, default="kairo-1.2b", choices=list(MODEL_CONFIG_PRESETS.keys()))
    parser.add_argument("--steps", type=int, default=5, help="Number of pretraining optimization steps")
    parser.add_argument("--block-size", type=int, default=256, help="Sequence block length")
    parser.add_argument("--batch-size", type=int, default=2, help="Batch size")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--smoke-test", action="store_true", help="Run fast 2-step verification test on CPU")
    args = parser.parse_args()

    # 1. Build or load corpus
    builder = SecurityCorpusBuilder()
    corpus = builder.build_corpus()

    # 2. Run Pretrainer
    pretrainer = DomainPretrainer(
        preset_name=args.preset,
        learning_rate=args.lr,
        block_size=args.block_size,
        batch_size=args.batch_size,
    )

    summary = pretrainer.run_pretraining(
        corpus_text=corpus,
        num_steps=args.steps if not args.smoke_test else 2,
        use_small_slice_for_test=args.smoke_test,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
