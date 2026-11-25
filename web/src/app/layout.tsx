import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "HarnessLens · Experiment Console",
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
