# KAIRO: End-to-End Installation, Setup & Deployment Guide

> **Production Deployment, VirtualBox Kali Sandbox Provisioning, & Local Dev Quickstart**  
> **Target Release**: KAIRO v4.0.0

---

## Table of Contents

1. [Prerequisites & System Requirements](#1-prerequisites--system-requirements)
2. [Local Development Quickstart (5 Minutes)](#2-local-development-quickstart-5-minutes)
3. [Kali Linux Virtualization Sandbox Provisioning](#3-kali-linux-virtualization-sandbox-provisioning)
4. [Dockerized Security Lab Targets (`/lab`)](#4-dockerized-security-lab-targets-lab)
5. [Production Deployment with PM2 & Systemd](#5-production-deployment-with-pm2--systemd)
6. [Hardware Sizing & GPU Acceleration](#6-hardware-sizing--gpu-acceleration)
7. [Troubleshooting & Diagnostics](#7-troubleshooting--diagnostics)

---

## 1. Prerequisites & System Requirements

### Hardware Requirements
- **CPU**: 4+ Physical Cores (x86_64 or ARM64)
- **RAM**: 16 GB minimum (32 GB recommended if running local 70B models or multiple lab containers)
- **Disk**: 40 GB free SSD storage (for Kali VM image, datasets, and logs)
- **GPU (Optional)**: NVIDIA GPU with CUDA 12+ (8 GB+ VRAM recommended for fast local inference via `llama.cpp`)

### Software Prerequisites
- **Python**: 3.11 or 3.12 (with `venv`, `pip`)
- **Node.js**: v18.0.0 or higher with `npm`
- **Docker**: Docker Desktop or Docker Engine with Docker Compose
- **VirtualBox**: Version 7.0+ (for isolated Kali Linux guest worker)

---

## 2. Local Development Quickstart (5 Minutes)

### Step 1: Clone the Repository
```bash
git clone https://github.com/its-tanay003/Kairo.git
cd Kairo
```

### Step 2: Configure Python Virtual Environment
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r orchestrator/requirements.txt
```

### Step 3: Install Node.js Dependencies
```bash
npm install
npm --prefix ui install
npm --prefix gateway install
```

### Step 4: Initialize the SQLite Audit Database
```bash
python -c "from events.db import init_db; init_db(); print('Database initialized successfully')"
```

### Step 5: Launch the Service Stack
Run the following in separate terminal panes or background processes:

```bash
# Terminal 1: Next.js 16 Client UI (Port 3000)
npm --prefix ui run dev

# Terminal 2: Session Gateway WebSocket (Port 4000)
npm --prefix gateway run dev

# Terminal 3: Agent Orchestrator (Port 8000 & 6080)
python -m uvicorn orchestrator.server:app --host 127.0.0.1 --port 8000
```

Open your browser to `http://localhost:3000` to interact with the **Claude UI cockpit**.

---

## 3. Kali Linux Virtualization Sandbox Provisioning

To enable isolated Tier 2 & Tier 3 tool execution:

### Step 1: Import VirtualBox Image
1. Download official Kali Linux VirtualBox image (.ova) from [kali.org](https://www.kali.org/get-kali/#kali-virtual-machines).
2. Import the appliance into VirtualBox and name it `Kali-Worker-Sandbox`.

### Step 2: Configure Host-Only Network
1. Open VirtualBox -> Tools -> Network Manager.
2. Ensure `vboxnet0` exists with IPv4 `192.168.56.1` and subnet mask `255.255.255.0`.
3. In VM Settings -> Network -> Adapter 2, select **Host-Only Adapter** (`vboxnet0`).

### Step 3: Deploy the Worker Agent Inside Kali
Run the deployment automation script from the host:
```bash
python scripts/deploy_worker.py --vm-name "Kali-Worker-Sandbox"
```

This installs the worker dependencies, copies [`vm/worker_service.py`](file:///c:/New%20Volume%20(D)/dev/vm), and enables the systemd service listening on `192.168.56.10:9999`.

### Step 4: Create Pristine Snapshot
```bash
VBoxManage snapshot "Kali-Worker-Sandbox" take "baseline_clean" --description "Pristine sandbox state"
```

---

## 4. Dockerized Security Lab Targets (`/lab`)

KAIRO includes self-contained lab targets for vulnerability verification:

```bash
cd lab
docker compose up -d
```

This brings up:
- **Mini-DVWA**: `http://localhost:8080` (SQLi, XSS, Command Injection)
- **Mini-Metasploitable**: Vulnerable FTP and SSH services on port `2222`.

---

## 5. Production Deployment with PM2 & Systemd

In production Linux environments, use PM2 for Node services and systemd for Python uvicorn:

### PM2 Process File (`ecosystem.config.js`)
```javascript
module.exports = {
  apps: [
    {
      name: "kairo-ui",
      cwd: "./ui",
      script: "npm",
      args: "start",
      env: { PORT: 3000 }
    },
    {
      name: "kairo-gateway",
      cwd: "./gateway",
      script: "npm",
      args: "start",
      env: { PORT: 4000 }
    }
  ]
};
```

### Systemd Orchestrator Unit (`/etc/systemd/system/kairo-orchestrator.service`)
```ini
[Unit]
Description=KAIRO Autonomous Cyber-Ops Orchestrator
After=network.target

[Service]
Type=simple
User=kairo
WorkingDirectory=/opt/kairo
ExecStart=/opt/kairo/venv/bin/uvicorn orchestrator.server:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 6. Hardware Sizing & GPU Acceleration

| Deployment Tier | Recommended RAM | VRAM | Model Capability |
| :--- | :--- | :--- | :--- |
| **Edge / Laptop** | 16 GB | None (CPU) | 380M – 1.5B quantized SFT models |
| **Standard Workstation**| 32 GB | 8 GB (RTX 4060/4070) | 7B – 14B Q4 models (`llama.cpp` GPU offload) |
| **Enterprise Server** | 64 GB+ | 24 GB+ (RTX 3090/4090/A5000)| 70B quantized models or DeepSeek-R1 full context |

---

## 7. Troubleshooting & Diagnostics

- **Port 3000 already in use**: Kill existing processes using `Get-Process -Id (Get-NetTCPConnection -LocalPort 3000).OwningProcess | Stop-Process -Force` (Windows) or `lsof -ti:3000 | xargs kill -9` (Linux).
- **Gateway connection refused (`wsStatus: disconnected`)**: Ensure Gateway is running on port 4000 (`npm --prefix gateway run dev`).
- **Orchestrator offline**: Verify FastAPI log: `python -m uvicorn orchestrator.server:app --port 8000`.
- **Playwright Navigation Timeout**: In testing, use `wait_until="domcontentloaded"` rather than `networkidle` due to persistent WebSocket streams.
