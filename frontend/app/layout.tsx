import type { Metadata } from "next";
import { Caveat } from "next/font/google";
import "./globals.css";
import AppShell from "@/app/components/AppShell";

const caveat = Caveat({ subsets: ["latin"], weight: ["600", "700"], variable: "--font-logo" });

export const metadata: Metadata = {
  title: "Humin - Autonomous Ad Manager",
  description: "Think (Huginn) / Remember (Muninn) / Learn / Adapt - an autonomous ad manager memoried by CockroachDB.",
};

// Applies the saved theme before first paint, so there's no flash of the
// wrong theme while React hydrates.
const noFlashScript = `
(function () {
  try {
    var saved = localStorage.getItem("humin-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={caveat.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashScript }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
