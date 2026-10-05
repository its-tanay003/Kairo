"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";

interface ScreenPanelProps {
  ws?: WebSocket | null;
  activeSessionId?: string;
  isMaximized?: boolean;
  onToggleMaximize?: () => void;
}

interface RFBInstance {
  scaleViewport: boolean;
  resizeSession: boolean;
  showDotCursor: boolean;
  background: string;
  disconnect: () => void;
  sendKey: (keysym: number, code: string | null, down: number) => void;
  addEventListener: (name: string, handler: (e: CustomEvent) => void) => void;
  removeEventListener: (name: string, handler: (e: CustomEvent) => void) => void;
}

interface ScreenTelemetry {
  status?: string;
  ws_port?: number;
  width?: number;
  height?: number;
  clients?: number;
  plane?: string;
  upstream_vnc_detected?: boolean;
  protocol?: string;
}

export default function ScreenPanel({
  ws,
  activeSessionId,
  isMaximized,
  onToggleMaximize,
}: ScreenPanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<RFBInstance | null>(null);

  const [status, setStatus] = useState<"connected" | "connecting" | "disconnected">("disconnected");
  const [statusDetail, setStatusDetail] = useState<string>("Ready to stream Kali worker GUI");
  const [desktopName, setDesktopName] = useState<string>("Kali Linux Worker (Kairo)");
  const [scaleMode, setScaleMode] = useState<"fit" | "native">("fit");
  const [wsUrl, setWsUrl] = useState<string>("");
  const [useGatewayTunnel, setUseGatewayTunnel] = useState<boolean>(false);
  const [lastConnectedAt, setLastConnectedAt] = useState<string | null>(null);
  const [streamInfo, setStreamInfo] = useState<ScreenTelemetry | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Determine appropriate WebSocket VNC endpoint
  const resolveVncUrl = useCallback(() => {
    if (typeof window === "undefined") return "ws://127.0.0.1:6080";
    const host = window.location.hostname || "127.0.0.1";
    if (useGatewayTunnel) {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const port = window.location.port ? `:${window.location.port}` : "";
      return `${proto}//${host}${port}/vnc`;
    }
    // Direct port 6080 VNC WebSocket
    return `ws://${host}:6080`;
  }, [useGatewayTunnel]);

  // Query orchestrator screen info/status
  const fetchScreenStatus = useCallback(async () => {
    try {
      const resp = await fetch("/screen/status");
      if (resp.ok) {
        const data = (await resp.json()) as ScreenTelemetry;
        setStreamInfo(data);
        if (data.plane) {
          setDesktopName(`Kali Linux (${data.plane})`);
        }
      }
    } catch {
      // ignore
    }
  }, []);

  // Connect to noVNC / RFB Streamer
  const connectVnc = useCallback(async () => {
    if (!containerRef.current || typeof window === "undefined") return;

    // Clean up existing instance if any
    if (rfbRef.current) {
      try {
        rfbRef.current.disconnect();
      } catch {
        // ignore
      }
      rfbRef.current = null;
    }

    setStatus("connecting");
    setStatusDetail("Negotiating RFB 3.8 protocol over WebSocket...");
    setErrorMsg(null);

    const targetUrl = resolveVncUrl();
    setWsUrl(targetUrl);

    try {
      // Dynamic import of @novnc/novnc to ensure safe client-side execution in Next.js & Tauri
      const RFBModule = await import("@novnc/novnc");
      const RFB = RFBModule.default || RFBModule;

      // Clear container element
      while (containerRef.current.firstChild) {
        containerRef.current.removeChild(containerRef.current.firstChild);
      }

      const rfb = new RFB(containerRef.current, targetUrl, {
        credentials: { password: "" },
        shared: true,
        wsProtocols: ["binary"],
      }) as unknown as RFBInstance;

      rfb.scaleViewport = scaleMode === "fit";
      rfb.resizeSession = true;
      rfb.showDotCursor = true;
      rfb.background = "#0d1117";

      rfb.addEventListener("connect", () => {
        setStatus("connected");
        setStatusDetail(`Connected to Kali Worker (${targetUrl})`);
        setLastConnectedAt(new Date().toLocaleTimeString());
        setErrorMsg(null);
      });

      rfb.addEventListener("disconnect", (e: CustomEvent<{ clean?: boolean }>) => {
        setStatus("disconnected");
        const clean = e.detail?.clean;
        setStatusDetail(clean ? "Session disconnected cleanly." : "Connection lost. Reconnect below.");
        rfbRef.current = null;
      });

      rfb.addEventListener("desktopname", (e: CustomEvent<{ name?: string }>) => {
        if (e.detail?.name) {
          setDesktopName(e.detail.name);
        }
      });

      rfb.addEventListener("securityfailure", (e: CustomEvent<{ reason?: string }>) => {
        setStatus("disconnected");
        setErrorMsg(`Security handshake failure: ${e.detail?.reason || "Authentication error"}`);
      });

      rfbRef.current = rfb;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatus("disconnected");
      setErrorMsg(`Failed to initialize noVNC client: ${msg}`);
      setStatusDetail("Connection error. Ensure VNC server is running on port 6080.");
    }
  }, [resolveVncUrl, scaleMode]);

  // Disconnect VNC
  const disconnectVnc = useCallback(() => {
    if (rfbRef.current) {
      try {
        rfbRef.current.disconnect();
      } catch {
        // ignore
      }
      rfbRef.current = null;
    }
    setStatus("disconnected");
    setStatusDetail("Disconnected by operator.");
  }, []);

  // Update scaling mode on live rfb instance
  const handleToggleScale = () => {
    const nextMode = scaleMode === "fit" ? "native" : "fit";
    setScaleMode(nextMode);
    if (rfbRef.current) {
      rfbRef.current.scaleViewport = nextMode === "fit";
    }
  };

  // Toggle fullscreen
  const handleToggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen?.().catch(() => {});
    } else {
      document.exitFullscreen?.().catch(() => {});
    }
  };

  // Send special key combinations (e.g. Ctrl+C or Ctrl+Alt+Del)
  const sendKeyCombo = (keys: number[]) => {
    if (!rfbRef.current) return;
    try {
      for (const k of keys) {
        rfbRef.current.sendKey(k, null, 1); // down
      }
      for (const k of keys.reverse()) {
        rfbRef.current.sendKey(k, null, 0); // up
      }
    } catch (err: unknown) {
      console.warn("Could not send key combo:", err);
    }
  };

  // Auto-connect on mount and query status asynchronously
  useEffect(() => {
    let isMounted = true;
    const init = async () => {
      if (isMounted) {
        await fetchScreenStatus();
        await connectVnc();
      }
    };
    init();

    return () => {
      isMounted = false;
      if (rfbRef.current) {
        try {
          rfbRef.current.disconnect();
        } catch {
          // ignore
        }
      }
    };
  }, [connectVnc, fetchScreenStatus]);

  // Note session props for debugging/tunnel tracking
  const sessionLabel = activeSessionId ? `Session: ${activeSessionId}` : ws ? "WS Sync: Active" : "";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        width: "100%",
        background: "#0a0e14",
        borderRadius: "8px",
        overflow: "hidden",
        border: "1px solid rgba(6, 182, 212, 0.25)",
      }}
    >
      {/* Top Toolbar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "8px 12px",
          background: "#111827",
          borderBottom: "1px solid #1f2937",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <span style={{ fontSize: "14px", fontWeight: "bold", color: "var(--accent-cyan, #06b6d4)" }}>
            🖥️ SCREEN
          </span>
          <span style={{ fontSize: "12px", color: "#9ca3af" }}>
            {desktopName}
          </span>
          {/* Status Badge */}
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "5px",
              padding: "2px 8px",
              borderRadius: "9999px",
              fontSize: "11px",
              fontWeight: 600,
              background:
                status === "connected"
                  ? "rgba(16, 185, 129, 0.2)"
                  : status === "connecting"
                  ? "rgba(245, 158, 11, 0.2)"
                  : "rgba(239, 68, 68, 0.2)",
              color:
                status === "connected"
                  ? "#10b981"
                  : status === "connecting"
                  ? "#f59e0b"
                  : "#ef4444",
              border: `1px solid ${
                status === "connected"
                  ? "rgba(16, 185, 129, 0.4)"
                  : status === "connecting"
                  ? "rgba(245, 158, 11, 0.4)"
                  : "rgba(239, 68, 68, 0.4)"
              }`,
            }}
          >
            <span
              style={{
                width: "6px",
                height: "6px",
                borderRadius: "50%",
                background:
                  status === "connected"
                    ? "#10b981"
                    : status === "connecting"
                    ? "#f59e0b"
                    : "#ef4444",
              }}
            />
            {status.toUpperCase()}
          </span>
        </div>

        {/* Action Controls */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
          {/* Endpoint Mode Toggle */}
          <button
            className="quick-btn secondary"
            style={{
              padding: "3px 8px",
              fontSize: "11px",
              background: useGatewayTunnel ? "rgba(6, 182, 212, 0.2)" : undefined,
              borderColor: useGatewayTunnel ? "var(--accent-cyan, #06b6d4)" : undefined,
            }}
            title="Switch between direct port 6080 and gateway /vnc reverse tunnel"
            onClick={() => {
              setUseGatewayTunnel((prev) => !prev);
              setTimeout(() => connectVnc(), 100);
            }}
          >
            {useGatewayTunnel ? "Tunnel: /vnc" : "Direct: :6080"}
          </button>

          {/* Scale Mode */}
          <button
            className="quick-btn secondary"
            style={{ padding: "3px 8px", fontSize: "11px" }}
            onClick={handleToggleScale}
            title="Toggle between Auto-Fit scale and 1:1 pixel native"
          >
            {scaleMode === "fit" ? "🔍 Fit Screen" : "1:1 Native"}
          </button>

          {/* Send Special Keys */}
          <button
            className="quick-btn secondary"
            style={{ padding: "3px 8px", fontSize: "11px", color: "#f87171" }}
            onClick={() => sendKeyCombo([0xffe3, 0x0063])} // Ctrl+C
            title="Send Ctrl+C (SIGINT) to virtual terminal"
          >
            Ctrl+C
          </button>

          {/* Fullscreen */}
          <button
            className="quick-btn secondary"
            style={{ padding: "3px 8px", fontSize: "11px" }}
            onClick={handleToggleFullscreen}
            title="Toggle fullscreen display"
          >
            ⛶ Fullscreen
          </button>

          {/* Connect / Disconnect */}
          {status === "connected" ? (
            <button
              className="quick-btn secondary"
              style={{ padding: "3px 10px", fontSize: "11px", borderColor: "#ef4444", color: "#ef4444" }}
              onClick={disconnectVnc}
            >
              Disconnect
            </button>
          ) : (
            <button
              className="quick-btn"
              style={{ padding: "3px 10px", fontSize: "11px" }}
              onClick={connectVnc}
              disabled={status === "connecting"}
            >
              {status === "connecting" ? "Connecting..." : "Connect"}
            </button>
          )}

          {/* Maximize Dock View */}
          {onToggleMaximize && (
            <button
              className="quick-btn secondary"
              style={{ padding: "3px 8px", fontSize: "11px" }}
              onClick={onToggleMaximize}
              title={isMaximized ? "Restore view" : "Maximize dock panel"}
            >
              {isMaximized ? "❐ Restore" : "🗖 Maximize"}
            </button>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {errorMsg && (
        <div
          style={{
            background: "rgba(239, 68, 68, 0.15)",
            borderBottom: "1px solid rgba(239, 68, 68, 0.3)",
            color: "#fca5a5",
            padding: "6px 12px",
            fontSize: "12px",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <span>⚠️ {errorMsg}</span>
          <button
            style={{ background: "none", border: "none", color: "#fff", cursor: "pointer", fontSize: "12px" }}
            onClick={() => setErrorMsg(null)}
          >
            ✕
          </button>
        </div>
      )}

      {/* Main noVNC Canvas Container */}
      <div
        ref={containerRef}
        id="novnc-canvas-container"
        tabIndex={0}
        style={{
          flex: 1,
          width: "100%",
          height: "100%",
          position: "relative",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#080c12",
          overflow: "auto",
          outline: "none",
        }}
      >
        {status === "disconnected" && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              gap: "12px",
              padding: "24px",
              textAlign: "center",
              maxWidth: "460px",
            }}
          >
            <div style={{ fontSize: "42px" }}>🖥️</div>
            <h3 style={{ margin: 0, color: "#e5e7eb", fontSize: "16px" }}>
              Kali Worker Desktop Stream Offline
            </h3>
            <p style={{ margin: 0, color: "#9ca3af", fontSize: "13px", lineHeight: "1.5" }}>
              {statusDetail}
            </p>
            <div style={{ display: "flex", gap: "8px", marginTop: "6px" }}>
              <button className="quick-btn" onClick={connectVnc}>
                ⚡ Reconnect noVNC Stream
              </button>
              <button
                className="quick-btn secondary"
                onClick={() => {
                  setUseGatewayTunnel(!useGatewayTunnel);
                  setTimeout(() => connectVnc(), 50);
                }}
              >
                Try {useGatewayTunnel ? "Direct Port 6080" : "Gateway Tunnel (/vnc)"}
              </button>
            </div>
            <div style={{ marginTop: "10px", fontSize: "11px", color: "#6b7280" }}>
              Endpoint: <code>{wsUrl || resolveVncUrl()}</code>
            </div>
          </div>
        )}

        {status === "connecting" && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: "10px",
              color: "#38bdf8",
            }}
          >
            <div
              style={{
                width: "28px",
                height: "28px",
                border: "3px solid rgba(6, 182, 212, 0.2)",
                borderTopColor: "#06b6d4",
                borderRadius: "50%",
                animation: "spin 1s linear infinite",
              }}
            />
            <span style={{ fontSize: "13px" }}>Connecting to Kali Worker ({wsUrl})...</span>
          </div>
        )}
      </div>

      {/* Bottom Telemetry Bar */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "5px 12px",
          background: "#0f172a",
          borderTop: "1px solid #1e293b",
          fontSize: "11px",
          color: "#94a3b8",
          flexWrap: "wrap",
          gap: "8px",
        }}
      >
        <div style={{ display: "flex", gap: "12px" }}>
          <span>
            Plane: <strong style={{ color: "#38bdf8" }}>{streamInfo?.plane || "WSL2 kali-linux"}</strong>
          </span>
          <span>
            Res: <strong>{streamInfo?.width || 1024}x{streamInfo?.height || 768}</strong> (32bpp TrueColor)
          </span>
          <span>
            Protocol: <strong>RFB 3.8 / WebSocket</strong>
          </span>
        </div>
        <div style={{ display: "flex", gap: "10px", alignItems: "center" }}>
          {sessionLabel && <span style={{ color: "#38bdf8" }}>{sessionLabel}</span>}
          {lastConnectedAt && <span>Connected since: {lastConnectedAt}</span>}
          <span style={{ color: "#64748b" }}>
            💡 Tip: Click inside desktop to interact with mouse & keyboard
          </span>
        </div>
      </div>
    </div>
  );
}
