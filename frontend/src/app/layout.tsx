import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MyBank Help & Support",
  description: "Banking help bot — ask about accounts, cards, transfers, loans, and more.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        {/* Mobile viewport — disable user scaling for webview feel */}
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover"
        />
        {/* Android WebView full-screen capability */}
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="theme-color" content="#0A1628" />
      </head>
      <body className="h-full overflow-hidden bg-[#0A1628] text-gray-900 antialiased">
        {children}
      </body>
    </html>
  );
}
