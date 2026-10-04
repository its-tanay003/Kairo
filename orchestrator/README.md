# /orchestrator - Agent Loop Engine

Python implementation of the agent core execution loop, designed for migration and hardening to Rust in subsequent phases.

## Responsibilities
1. Load ToolSpecs from `/registry`.
2. Evaluate agent prompts and dispatch tool execution.
3. Record high-fidelity, strictly validated events directly to `/events/events.db` conforming to the 20-field Event specification.
4. Expose an internal HTTP RPC boundary (`POST /run`, `GET /health`, `GET /events`).

## Hardening Path to Rust
The service boundary is explicitly decoupled via HTTP/JSON. Hardening to Rust involves swapping `server.py` and `agent.py` with an `axum` or `actix-web` daemon that links to `rusqlite` and `serde_yaml` without requiring changes to `/gateway` or `/ui`.
