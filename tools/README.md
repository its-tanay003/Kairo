# /tools - External Binaries & Tunneling Utilities

The `/tools` directory contains standalone system binaries and utilities used for deployment, ingress networking, and remote access.

---

## Binary Catalog

### `cloudflared.exe`

- **Description**: Cloudflare Tunnel daemon (cloudflared) for Windows 64-bit systems.
- **Role in Kairo**:
  - Provides encrypted, outbound-only reverse tunneling from isolated or air-gapped security labs to external remote operators.
  - Allows exposing the Kairo Gateway (`ws://localhost:4000`, `http://localhost:4000`) and the UI (`http://localhost:3000`) securely without port-forwarding or public IP exposure.
- **Typical Usage**:

```bash
# Quick temporary tunnel for remote operator access
tools\cloudflared.exe tunnel --url http://localhost:3000
```

- **Integrity**: Official signed binary from Cloudflare.
