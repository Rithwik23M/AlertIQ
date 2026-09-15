import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // AlertIQ surface palette — light / Experiential-style
        "aq-navy":          "#ffffff",
        "aq-surface":       "#ffffff",
        "aq-surface-raised":"#f9fafb",
        "aq-border":        "#e5e7eb",
        "aq-border-subtle": "#f3f4f6",
        "aq-muted":         "#f3f4f6",
        // Text hierarchy
        "aq-text":           "#111827",
        "aq-text-secondary": "#374151",
        "aq-text-dim":       "#9ca3af",
        // Accent — forest green (Experiential)
        "aq-accent": "#16a34a",
        // Risk-level semantic tokens (light-background optimised)
        "risk-critical": "#dc2626",
        "risk-high":     "#ea580c",
        "risk-medium":   "#d97706",
        "risk-low":      "#16a34a",
        "risk-minimal":  "#6b7280",
        // Status tokens (light-background optimised)
        "status-new":      "#2563eb",
        "status-progress": "#7c3aed",
        "status-escalated":"#dc2626",
        "status-closed":   "#6b7280",
        "status-review":   "#d97706",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
