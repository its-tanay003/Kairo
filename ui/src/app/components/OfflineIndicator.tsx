"use client";

import React, { useState } from "react";

export type OfflineDataPathState = "fully offline" | "local-only" | "connected";

export interface OfflineIndicatorProps {
  wsStatus: "connected" | "connecting" | "disconnected";
  clientType?: string;
  sessionId?: string;
  workspaceId?: string | null;
  gatewayUrl?: string;
  authenticated?: boolean;
  onProvisionWorkspace?: () => void;
  onTerminateWorkspace?: () => void;
}

export default function OfflineIndicator({
  wsStatus,
  clientType = "browser-desktop",
  sessionId = "unknown",
  workspaceId = null,
  gatewayUrl = "http://localhost:4000",
  authenticated = true,
  onProvisionWorkspace,
  onTerminateWorkspace,
}: OfflineIndicatorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [manualOverride, setManualOverride] = useState<OfflineDataPathState | null>(null);

  // Determine current active data path state
  const computedState: OfflineDataPathState = (() => {
    if (manualOverride) return manualOverride;
    if (wsStatus === "disconnected") return "fully offline";
    if (wsStatus === "connecting") return "local-only";

    // If connected to localhost / loopback, it's local-only (0 bytes cloud egress)
    const isLoopback =
      typeof window !== "undefined" &&
      (window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1" ||
        gatewayUrl.includes("localhost") ||
        gatewayUrl.includes("127.0.0.1"));

    return isLoopback ? "local-only" : "connected";
  })();

  const config = {
    "fully offline": {
      label: "Fully Offline",
      shortLabel: "Air-Gapped",
      badgeColor: "#f43f5e",
      bgColor: "rgba(244, 63, 94, 0.12)",
      borderColor: "rgba(244, 63, 94, 0.35)",
      glowColor: "rgba(244, 63, 94, 0.4)",
      dotClass: "disconnected",
      icon: "⚡",
      egress: "0 B (Air-gapped)",
      description: "No connection to gateway or cloud. All inputs and artifacts remain strictly on this device.",
    },
    "local-only": {
      label: "Local-Only",
      shortLabel: "0 Cloud Egress",
      badgeColor: "#f59e0b",
      bgColor: "rgba(245, 158, 11, 0.12)",
      borderColor: "rgba(245, 158, 11, 0.35)",
      glowColor: "rgba(245, 158, 11, 0.4)",
      dotClass: "connecting",
      icon: "🔒",
      egress: "0 B (Localhost / WSL2 Loopback)",
      description: "Connected to local Session Gateway & Kali VM. Zero telemetry leaves your private hardware.",
    },
    "connected": {
      label: "Connected",
      shortLabel: "Private Backend",
      badgeColor: "#10b981",
      bgColor: "rgba(16, 185, 129, 0.12)",
      borderColor: "rgba(16, 185, 129, 0.35)",
      glowColor: "rgba(16, 185, 129, 0.4)",
      dotClass: "connected",
      icon: "🛡️",
      egress: "Encrypted WSS (User Instance)",
      description: "Secure TLS connection to user-controlled private backend instance with authenticated token.",
    },
  }[computedState];

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      {/* Clickable Status Chip */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          padding: "5px 12px",
          borderRadius: "9999px",
          fontSize: "12px",
          fontWeight: 600,
          background: config.bgColor,
          border: `1px solid ${config.borderColor}`,
          color: config.badgeColor,
          cursor: "pointer",
          transition: "all 0.2s ease",
          boxShadow: `0 0 12px ${config.glowColor}`,
        }}
        title="Data Path Indicator: Click to inspect security & network isolation"
      >
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: config.badgeColor,
            boxShadow: `0 0 8px ${config.badgeColor}`,
            display: "inline-block",
          }}
        />
        <span>
          Data Path: <strong>{config.label}</strong> ({config.shortLabel})
        </span>
        <span style={{ fontSize: "10px", opacity: 0.8 }}>▾</span>
      </button>

      {/* Inspection Modal / Dropdown */}
      {isOpen && (
        <>
          <div
            style={{
              position: "fixed",
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              zIndex: 998,
            }}
            onClick={() => setIsOpen(false)}
          />
          <div
            style={{
              position: "absolute",
              top: "calc(100% + 8px)",
              right: 0,
              width: "360px",
              maxWidth: "calc(100vw - 24px)",
              background: "#0f172a",
              border: "1px solid rgba(255, 255, 255, 0.12)",
              borderRadius: "12px",
              boxShadow: "0 20px 40px rgba(0, 0, 0, 0.7)",
              padding: "16px",
              zIndex: 999,
              color: "#e2e8f0",
              fontSize: "13px",
              backdropFilter: "blur(16px)",
            }}
          >
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontSize: "16px" }}>{config.icon}</span>
                <span style={{ fontWeight: 700, fontSize: "14px", color: config.badgeColor }}>
                  Data Path Verification
                </span>
              </div>
              <span
                style={{
                  fontSize: "10px",
                  padding: "2px 8px",
                  borderRadius: "4px",
                  background: config.bgColor,
                  color: config.badgeColor,
                  border: `1px solid ${config.borderColor}`,
                  fontWeight: 600,
                  textTransform: "uppercase",
                }}
              >
                {computedState}
              </span>
            </div>

            <p style={{ color: "#94a3b8", fontSize: "12px", lineHeight: "1.4", marginBottom: "14px" }}>
              {config.description}
            </p>

            {/* Metrics Grid */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr",
                gap: "8px",
                background: "rgba(15, 23, 42, 0.6)",
                padding: "12px",
                borderRadius: "8px",
                border: "1px solid rgba(255, 255, 255, 0.06)",
                marginBottom: "14px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Cloud Egress:</span>
                <span style={{ fontWeight: 600, color: computedState === "connected" ? "#38bdf8" : "#10b981" }}>
                  {config.egress}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Client Platform:</span>
                <span style={{ fontWeight: 500, color: "#cbd5e1" }}>{clientType}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Gateway Endpoint:</span>
                <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#cbd5e1" }}>{gatewayUrl}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Auth Status:</span>
                <span style={{ color: authenticated ? "#10b981" : "#f43f5e", fontWeight: 600 }}>
                  {authenticated ? "Verified Token" : "Unauthenticated"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Disposable Workspace:</span>
                <span style={{ fontFamily: "monospace", fontSize: "11px", color: workspaceId ? "#38bdf8" : "#64748b" }}>
                  {workspaceId ? workspaceId.slice(0, 16) + "..." : "None Active"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "#64748b" }}>Session ID:</span>
                <span style={{ fontFamily: "monospace", fontSize: "11px", color: "#cbd5e1" }}>{sessionId}</span>
              </div>
            </div>

            {/* Quick Actions */}
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
              {onProvisionWorkspace && (
                <button
                  type="button"
                  onClick={() => {
                    onProvisionWorkspace();
                    setIsOpen(false);
                  }}
                  style={{
                    flex: 1,
                    padding: "6px 10px",
                    borderRadius: "6px",
                    fontSize: "11px",
                    fontWeight: 600,
                    background: "rgba(56, 189, 248, 0.15)",
                    color: "#38bdf8",
                    border: "1px solid rgba(56, 189, 248, 0.3)",
                    cursor: "pointer",
                  }}
                >
                  ⚡ Boot Disposable Kali VM
                </button>
              )}
              {workspaceId && onTerminateWorkspace && (
                <button
                  type="button"
                  onClick={() => {
                    onTerminateWorkspace();
                    setIsOpen(false);
                  }}
                  style={{
                    padding: "6px 10px",
                    borderRadius: "6px",
                    fontSize: "11px",
                    fontWeight: 600,
                    background: "rgba(244, 63, 94, 0.15)",
                    color: "#f43f5e",
                    border: "1px solid rgba(244, 63, 94, 0.3)",
                    cursor: "pointer",
                  }}
                >
                  Purge VM
                </button>
              )}
            </div>

            {/* Simulated Data Path Tester (for validation) */}
            <div style={{ borderTop: "1px solid rgba(255, 255, 255, 0.08)", paddingTop: "10px" }}>
              <div style={{ fontSize: "11px", color: "#64748b", marginBottom: "6px" }}>
                Simulate Data Path State:
              </div>
              <div style={{ display: "flex", gap: "4px" }}>
                {(["fully offline", "local-only", "connected"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setManualOverride(manualOverride === s ? null : s)}
                    style={{
                      flex: 1,
                      padding: "4px 6px",
                      borderRadius: "4px",
                      fontSize: "10px",
                      fontWeight: computedState === s ? 700 : 400,
                      background:
                        computedState === s ? "rgba(255, 255, 255, 0.15)" : "rgba(255, 255, 255, 0.04)",
                      color: computedState === s ? "#ffffff" : "#94a3b8",
                      border: "1px solid rgba(255, 255, 255, 0.08)",
                      cursor: "pointer",
                      textTransform: "capitalize",
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
