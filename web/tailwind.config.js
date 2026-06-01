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
        "4xs": ["0.625rem", { lineHeight: "0.875rem" }],   // 10px — micro labels
        "3xs": ["0.6875rem", { lineHeight: "0.9375rem" }], // 11px — mini labels
        "2xs": ["0.75rem", { lineHeight: "1rem" }],         // 12px — captions
        xs: ["0.8125rem", { lineHeight: "1.25rem" }],       // 13px — body small
        sm: ["0.875rem", { lineHeight: "1.375rem" }],       // 14px — body
        base: ["0.9375rem", { lineHeight: "1.5rem" }],      // 15px — body large
        lg: ["1.0625rem", { lineHeight: "1.625rem" }],      // 17px — subtitle
        xl: ["1.25rem", { lineHeight: "1.75rem" }],         // 20px — heading
        "2xl": ["1.5rem", { lineHeight: "2rem" }],          // 24px — heading large
      },
      borderRadius: {
        xs: "4px",
        sm: "6px",
        md: "8px",
        lg: "10px",
        xl: "14px",
        "2xl": "18px",
        full: "9999px",
      },
      boxShadow: {
        // Elevation tokens — consistent across all components
        xs: "0 1px 2px rgba(0, 0, 0, 0.06)",
        sm: "0 1px 3px rgba(0, 0, 0, 0.10)",
        md: "0 4px 16px rgba(0, 0, 0, 0.10)",
        lg: "0 8px 24px rgba(0, 0, 0, 0.12)",
        xl: "0 12px 32px rgba(0, 0, 0, 0.15)",
        "2xl": "0 20px 48px rgba(0, 0, 0, 0.22)",
        // Semantic shadows
        "bubble-user": "0 1px 3px rgba(0, 0, 0, 0.18)",
        "bubble-agent": "0 1px 3px rgba(0, 0, 0, 0.10)",
      },
      transitionDuration: {
        DEFAULT: "180ms",
        150: "150ms",
        200: "200ms",
        300: "300ms",
      },
      animation: {
        blink: "blink 1s steps(2) infinite",
        "fade-in": "fade-in 0.2s ease-out",
        "fade-in-up": "fade-in-up 0.2s ease-out",
        "slide-in-left": "slide-in-left 0.2s ease-out",
        "slide-in-right": "slide-in-right 0.2s ease-out",
        "dot-pulse": "dot-pulse 1.4s infinite ease-in-out both",
        "spin-slow": "spin 2s linear infinite",
      },
      keyframes: {
        blink: { "50%": { opacity: "0" } },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "fade-in-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in-left": {
          from: { opacity: "0", transform: "translateX(-12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "slide-in-right": {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
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
