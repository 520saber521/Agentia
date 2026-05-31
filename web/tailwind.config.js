/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "rgb(var(--color-bg) / <alpha-value>)",
        panel: "rgb(var(--color-panel) / <alpha-value>)",
        border: "rgb(var(--color-border) / <alpha-value>)",
        muted: "rgb(var(--color-muted) / <alpha-value>)",
        "muted-fg": "rgb(var(--color-muted-fg) / <alpha-value>)",
        fg: "rgb(var(--color-fg) / <alpha-value>)",
        accent: "rgb(var(--color-accent) / <alpha-value>)",
        "accent-hover": "rgb(var(--color-accent-hover) / <alpha-value>)",
        "surface-hover": "rgb(var(--color-surface-hover) / <alpha-value>)",
        user: "rgb(var(--color-user) / <alpha-value>)",
        agent: "rgb(var(--color-agent) / <alpha-value>)",
        danger: "rgb(var(--color-danger) / <alpha-value>)",
        success: "rgb(var(--color-success) / <alpha-value>)",
        warning: "rgb(var(--color-warning) / <alpha-value>)",
        info: "rgb(var(--color-info) / <alpha-value>)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "Segoe UI",
          "system-ui",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "Cascadia Mono", "Consolas", "monospace"],
      },
      fontSize: {
        // Accessibility: base sizes never below 12px for UI labels
        "3xs": ["0.6875rem", { lineHeight: "0.9375rem" }],
        "2xs": ["0.75rem", { lineHeight: "1rem" }],
        "xs": ["0.8125rem", { lineHeight: "1.25rem" }],
      },
      borderRadius: {
        sm: "6px",
        md: "8px",
        lg: "12px",
        xl: "16px",
        "2xl": "20px",
        full: "9999px",
      },
      boxShadow: {
        "card-sm": "0 4px 16px rgba(0, 0, 0, 0.10)",
        "card-md": "0 8px 24px rgba(0, 0, 0, 0.13)",
        "card-lg": "0 10px 30px rgba(0, 0, 0, 0.17)",
        "bubble-user": "0 1px 3px rgba(0, 0, 0, 0.18)",
        "bubble-agent": "0 1px 3px rgba(0, 0, 0, 0.12)",
        popover: "0 16px 48px rgba(0, 0, 0, 0.35)",
        modal: "0 24px 64px rgba(0, 0, 0, 0.40)",
      },
      transitionDuration: {
        150: "150ms",
        200: "200ms",
        300: "300ms",
      },
      animation: {
        blink: "blink 1s steps(2) infinite",
        "fade-in": "fade-in 0.18s ease-out",
        "dot-pulse": "dot-pulse 1.4s infinite ease-in-out both",
      },
      keyframes: {
        blink: { "50%": { opacity: "0" } },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "dot-pulse": {
          "0%, 80%, 100%": { transform: "scale(0)" },
          "40%": { transform: "scale(1)" },
        },
      },
    },
  },
  plugins: [],
};
