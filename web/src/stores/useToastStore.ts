import { create } from "zustand";

export interface Toast {
  id: string;
  type: "info" | "success" | "warning" | "error";
  message: string;
  duration?: number;
}

interface ToastState {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
}

let _nextId = 1;

export const useToastStore = create<ToastState>()((set, get) => ({
  toasts: [],

  addToast(toast) {
    const id = `toast-${_nextId++}`;
    const duration = toast.duration ?? 4000;
    const entry: Toast = { ...toast, id };
    set((s) => ({ toasts: [...s.toasts, entry] }));
    if (duration > 0) {
      setTimeout(() => {
        get().removeToast(id);
      }, duration);
    }
  },

  removeToast(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));
