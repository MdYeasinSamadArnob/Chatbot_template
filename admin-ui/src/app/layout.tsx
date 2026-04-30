import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Banking KB Editor",
  description: "WYSIWYG editor for the Banking Knowledge Base",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased bg-gray-100">{children}</body>
    </html>
  );
}
