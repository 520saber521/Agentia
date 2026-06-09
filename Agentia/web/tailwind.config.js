/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        bg: "#05070a",
        panel: "#0b0f16",
        border: "#222936",
        muted: "#8b95a7",
        fg: "#e7edf7",
        accent: "#38bdf8",
        "accent-hover": "#0ea5e9",
        user: "#0f3f46",
        agent: "#101722",
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
