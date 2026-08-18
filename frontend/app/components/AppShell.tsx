"use client";

import { useState } from "react";
import Sidebar from "@/app/components/Sidebar";
import ThemeToggle from "@/app/components/ThemeToggle";

function MenuIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className="app-shell">
      <Sidebar mobileOpen={navOpen} onNavigate={() => setNavOpen(false)} />
      {navOpen && <div className="mobile-nav-backdrop" onClick={() => setNavOpen(false)} />}

      <div className="app-main">
        <div className="app-topbar">
          <button
            className="mobile-nav-toggle"
            onClick={() => setNavOpen((o) => !o)}
            aria-label={navOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={navOpen}
          >
            <MenuIcon />
          </button>
          <span className="mobile-nav-logo">Humin</span>
          <ThemeToggle />
        </div>
        <main className="container">
          <div className="container-inner">{children}</div>
        </main>
      </div>
    </div>
  );
}
