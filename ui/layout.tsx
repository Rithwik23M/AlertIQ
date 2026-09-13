import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AlertIQ — Investigation Workspace",
  description:
    "AML alert prioritisation and investigation workspace for financial crime analysts.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-aq-navy text-aq-text antialiased">
        {/* ── Top navigation bar ── */}
        <header
          className="border-b border-aq-border bg-aq-surface sticky top-0 z-50"
          role="banner"
        >
          <div className="max-w-screen-2xl mx-auto px-6 h-14 flex items-center gap-6">

            {/* Brand mark */}
            <a
              href="/"
              className="flex items-center gap-2.5 text-aq-text hover:text-white transition-colors flex-shrink-0"
              aria-label="AlertIQ home"
            >
              {/* Hexagon shield mark */}
              <svg
                width="22"
                height="22"
                viewBox="0 0 22 22"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path
                  d="M11 1.5L2.5 6.25v9.5L11 20.5l8.5-4.75V6.25L11 1.5z"
                  stroke="#3B82F6"
                  strokeWidth="1.25"
                  strokeLinejoin="round"
                  fill="none"
                />
                <path
                  d="M11 7.5L7 9.75v4.5L11 16.5l4-2.25V9.75L11 7.5z"
                  fill="#3B82F6"
                  opacity="0.5"
                />
              </svg>
              <span className="font-semibold text-sm tracking-tight">
                Alert<span className="text-aq-accent">IQ</span>
              </span>
            </a>

            {/* Separator */}
            <div className="h-4 w-px bg-aq-border" aria-hidden="true" />

            {/* Primary navigation */}
            <nav className="flex items-center gap-1 text-sm" aria-label="Primary navigation">
              <a
                href="/"
                className="px-3 py-1.5 rounded text-aq-text hover:bg-aq-surface-raised transition-colors font-medium text-sm"
                aria-current="page"
              >
                Queue
              </a>
              <a
                href="/investigations"
                className="px-3 py-1.5 rounded text-aq-text-dim hover:text-aq-text hover:bg-aq-surface-raised transition-colors text-sm"
              >
                Investigations
              </a>
            </nav>

            {/* Right side — model indicator + compliance notice */}
            <div className="ml-auto flex items-center gap-4">
              {/* Environment / model indicator */}
              <div
                className="hidden md:flex items-center gap-2 text-xs text-aq-text-dim"
                aria-label="Model environment"
              >
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500/70 flex-shrink-0" aria-hidden="true" />
                <span className="font-mono">v1.0.1</span>
                <span className="text-aq-border">·</span>
                <span>Production</span>
              </div>

              {/* Compliance notice */}
              <p
                className="hidden lg:block text-xs text-aq-text-dim border-l border-aq-border pl-4"
                role="note"
              >
                Decision-support only — all SAR decisions require analyst review
              </p>
            </div>
          </div>
        </header>

        <main
          className="max-w-screen-2xl mx-auto px-6 py-6"
          id="main-content"
        >
          {children}
        </main>
      </body>
    </html>
  );
}
