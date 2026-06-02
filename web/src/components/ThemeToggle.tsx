import { useTheme } from "../hooks/useTheme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggle}
      className="relative shrink-0 rounded-full overflow-hidden transition-all duration-500
        hover:scale-110 hover:shadow-xl
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
      style={{
        width: 34,
        height: 34,
        background: isDark
          ? "linear-gradient(135deg, #6366F1 0%, #818CF8 40%, #A5B4FC 70%, #C7D2FE 100%)"
          : "linear-gradient(135deg, #F59E0B 0%, #F97316 30%, #EF4444 65%, #EC4899 100%)",
        boxShadow: isDark
          ? "0 0 16px rgba(99,102,241,0.4), inset 0 0 6px rgba(165,180,252,0.15)"
          : "0 0 16px rgba(245,158,11,0.45), inset 0 0 6px rgba(251,191,36,0.2)",
      }}
      aria-label={isDark ? "切换到亮色模式" : "切换到暗色模式"}
      title={isDark ? "亮色模式" : "暗色模式"}
    >
      {/* Crescent eclipse overlay */}
      <div
        className="absolute rounded-full bg-bg"
        style={{
          right: -2,
          top: -2,
          width: 28,
          height: 28,
          transform: isDark ? "scale(1)" : "scale(0)",
          transformOrigin: "top right",
          transition: "transform 0.55s cubic-bezier(0.645, 0.045, 0.355, 1)",
        }}
      />

      {/* Tiny stars — visible only in dark mode */}
      <span
        className="absolute rounded-full bg-white transition-all duration-500"
        style={{
          left: 7,
          top: 7,
          width: 3,
          height: 3,
          opacity: isDark ? 0.9 : 0,
          transform: isDark ? "scale(1)" : "scale(0)",
          transitionDelay: isDark ? "0.25s" : "0s",
        }}
      />
      <span
        className="absolute rounded-full bg-white transition-all duration-500"
        style={{
          right: 8,
          bottom: 7,
          width: 2,
          height: 2,
          opacity: isDark ? 0.7 : 0,
          transform: isDark ? "scale(1)" : "scale(0)",
          transitionDelay: isDark ? "0.35s" : "0s",
        }}
      />
      <span
        className="absolute rounded-full bg-white transition-all duration-500"
        style={{
          left: 13,
          bottom: 5,
          width: 2,
          height: 2,
          opacity: isDark ? 0.6 : 0,
          transform: isDark ? "scale(1)" : "scale(0)",
          transitionDelay: isDark ? "0.3s" : "0s",
        }}
      />
    </button>
  );
}
