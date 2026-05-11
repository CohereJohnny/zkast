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
        canvas: "var(--bg-canvas)",
        surface: {
          DEFAULT: "var(--bg-surface)",
          raised: "var(--bg-surface-raised)",
          overlay: "var(--bg-surface-overlay)",
        },
        "border-subtle": "var(--border-subtle)",
        "border-strong": "var(--border-strong)",
        primary: "var(--text-primary)",
        secondary: "var(--text-secondary)",
        muted: "var(--text-muted)",
        "accent-primary": "var(--accent-primary)",
        "accent-primary-hover": "var(--accent-primary-hover)",
        "accent-secondary": "var(--accent-secondary)",
        success: "var(--semantic-success)",
        warning: "var(--semantic-warning)",
        danger: "var(--semantic-danger)",
        info: "var(--semantic-info)",
      },
      fontFamily: {
        sans: ["var(--font-plus-jakarta)", "system-ui", "sans-serif"],
        serif: ["var(--font-crimson)", "Georgia", "serif"],
        mono: ["var(--font-jetbrains)", "ui-monospace", "monospace"],
      },
      fontSize: {
        display: [
          "30px",
          { lineHeight: "1.2", letterSpacing: "-0.02em", fontWeight: "600" },
        ],
        "title-1": [
          "24px",
          { lineHeight: "1.25", letterSpacing: "-0.01em", fontWeight: "600" },
        ],
        "title-2": ["20px", { lineHeight: "1.3", fontWeight: "600" }],
        "title-3": ["16px", { lineHeight: "1.35", fontWeight: "600" }],
        body: ["14px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-lg": ["16px", { lineHeight: "1.65", fontWeight: "400" }],
        caption: ["12px", { lineHeight: "1.4", fontWeight: "400" }],
        mono: ["13px", { lineHeight: "1.5", fontWeight: "400" }],
      },
      borderRadius: {
        sm: "6px",
        md: "8px",
        lg: "12px",
      },
      ringColor: {
        DEFAULT: "var(--accent-primary)",
        canvas: "var(--bg-canvas)",
      },
      ringOffsetColor: {
        canvas: "var(--bg-canvas)",
      },
      boxShadow: {
        modal: "0 8px 24px rgba(2, 6, 23, 0.6)",
      },
    },
  },
  plugins: [],
};

export default config;
