import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Service Boundary Verification",
  description: "Next.js UI connecting via WebSocket to Gateway, Orchestrator, and SQLite Event Store",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
