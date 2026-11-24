import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Harness Lab · 组件进化",
  description: "Harness 组件版本谱系、完整配置快照与证据回放。",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
