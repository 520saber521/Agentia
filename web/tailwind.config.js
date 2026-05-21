/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        bg: "#0f1115",
        panel: "#1a1d24",
        border: "#2a2e38",
        muted: "#98a2b3",
        fg: "#e6e6e6",
        accent: "#3b82f6",
        "accent-hover": "#2563eb",
        user: "#1e3a8a",
        agent: "#1f2937",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "Segoe UI",
          "system-ui",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["JetBrains Mono", "Cascadia Mono", "Consolas", "monospace"],
      },
      animation: {
        blink: "blink 1s steps(2) infinite",
        "fade-in": "fade-in 0.18s ease-out",
      },
      keyframes: {
        blink: { "50%": { opacity: "0" } },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
