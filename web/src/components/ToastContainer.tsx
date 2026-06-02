import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useToastStore } from "../stores/useToastStore";
import { X, AlertTriangle, CheckCircle, Info } from "./icons";

const TYPE_STYLES: Record<string, string> = {
  error: "border-danger/30 bg-danger/10 text-danger/90",
  warning: "border-warning/30 bg-warning/10 text-warning/90",
  success: "border-success/30 bg-success/10 text-success/90",
  info: "border-info/30 bg-info/10 text-info/90",
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
  error: <AlertTriangle className="h-4 w-4" />,
  warning: <AlertTriangle className="h-4 w-4" />,
  success: <CheckCircle className="h-4 w-4" />,
  info: <Info className="h-4 w-4" />,
};

export function ToastContainer() {
  const toasts = useToastStore((s) => s.toasts);
  const removeToast = useToastStore((s) => s.removeToast);
  const prefersReducedMotion = useReducedMotion();

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            initial={prefersReducedMotion ? undefined : { opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={prefersReducedMotion ? undefined : { opacity: 0, y: -8, scale: 0.95 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className={`pointer-events-auto flex items-start gap-2.5 rounded-lg border px-4 py-3 shadow-popover backdrop-blur-lg min-w-[280px] max-w-[420px] ${TYPE_STYLES[toast.type] ?? TYPE_STYLES.info}`}
          >
            <span className="shrink-0 mt-0.5">
              {TYPE_ICONS[toast.type] ?? TYPE_ICONS.info}
            </span>
            <p className="flex-1 text-xs leading-relaxed">{toast.message}</p>
            <button
              type="button"
              onClick={() => removeToast(toast.id)}
              className="shrink-0 rounded p-0.5 opacity-60 hover:opacity-100 transition-opacity"
              aria-label="关闭通知"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
