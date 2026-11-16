import { create } from "zustand";

export type Theme = "light" | "dark";
let stored: Theme = "light";
try { stored = (localStorage.getItem("campus-qa-theme") || "light") as Theme; } catch {}

export const useThemeStore = create<{ theme: Theme; toggle: () => void }>((set) => ({
  theme: stored,
  toggle: () => set((s) => {
    const next = s.theme === "light" ? "dark" : "light";
    localStorage.setItem("campus-qa-theme", next);
    return { theme: next };
  }),
}));
