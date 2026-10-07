import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kairo - Autonomous Cyber-Ops Platform",
  description: "Minimalist, high-focus cyber defense cockpit and autonomous agent interface.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
