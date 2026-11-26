import type { Metadata } from "next";
import "./globals.css";
import {PLATFORM_NAME} from "@/lib/branding";
export const metadata: Metadata = {
  title: `${PLATFORM_NAME} · Experiment Console`,
  description: "Configure, run and inspect Harness evolution experiments.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
