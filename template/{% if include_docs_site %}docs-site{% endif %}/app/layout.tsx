import type { Metadata } from "next";
import "./globals.css";
// Title/description live in site.json so this file needs no templating: prettier
// re-wraps a long string in a TS object (`title:` → newline), which would make a
// freshly generated repo fail `prettier --check` for long project names.
// Prettier never re-wraps string values in JSON, so it is stable at any length.
import site from "./site.json";

export const metadata: Metadata = {
  title: site.title,
  description: site.description,
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
