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
      <body className="min-h-screen bg-[#f9fafb] text-aq-text antialiased flex flex-col">
        {/* ── Top navigation bar ── */}
        <header
          className="border-b border-aq-border bg-aq-surface sticky top-0 z-50"
          role="banner"
        >
          <div className="w-full px-6 h-14 flex items-center gap-6">

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
                  stroke="#16a34a"
                  strokeWidth="1.25"
                  strokeLinejoin="round"
                  fill="none"
                />
                <path
                  d="M11 7.5L7 9.75v4.5L11 16.5l4-2.25V9.75L11 7.5z"
                  fill="#16a34a"
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

            {/* Right side — compliance notice */}
            <div className="ml-auto flex items-center gap-4">
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
          className="w-full px-6 py-6 flex-1"
          id="main-content"
        >
          {children}
        </main>

        {/* ── Footer — version indicator ── */}
        <footer
          className="border-t border-[var(--aq-border)] bg-[var(--aq-surface)] mt-auto"
          role="contentinfo"
        >
          <div className="w-full px-6 h-9 flex items-center justify-between">
            <div
              className="flex items-center gap-2 text-xs text-[var(--aq-text-dim)]"
              aria-label="Application version"
            >
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500/70 flex-shrink-0" aria-hidden="true" />
              <span className="font-mono">v1.0.1</span>
              <span className="text-[var(--aq-border)]">·</span>
              <span>Production</span>
            </div>
            <p className="text-xs text-[var(--aq-text-dim)]">
              AlertIQ — AML Investigation Workspace
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
