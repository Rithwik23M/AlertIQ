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
        // AlertIQ surface palette
        "aq-navy":          "#0C1622",
        "aq-surface":       "#132032",
        "aq-surface-raised":"#1A2D43",
        "aq-border":        "#1E3050",
        "aq-border-subtle": "#192840",
        "aq-muted":         "#223347",
        // Text hierarchy
        "aq-text":           "#D0E0F0",
        "aq-text-secondary": "#8DAFC8",
        "aq-text-dim":       "#526B85",
        // Accent
        "aq-accent": "#3B82F6",
        // Risk-level semantic tokens
        "risk-critical": "#E05252",
        "risk-high":     "#D9824A",
        "risk-medium":   "#C8A83A",
        "risk-low":      "#4AAA72",
        "risk-minimal":  "#5E7A90",
        // Status tokens
        "status-new":      "#4A9EED",
        "status-progress": "#8B7CD8",
        "status-escalated":"#E05252",
        "status-closed":   "#5E7A90",
        "status-review":   "#C8883A",
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
