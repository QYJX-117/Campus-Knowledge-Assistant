import { create } from "zustand";

interface User {
  id: number; name: string; email: string; role: string; is_active: boolean; guest_id?: string;
}

interface AuthState {
  token: string | null;
  user: User | null;
  login: (token: string, user: User) => void;
  updateUser: (user: User) => void;
  logout: () => void;
  isAdmin: () => boolean;
}

let initial = { token: null as string | null, user: null as User | null };
try {
  const stored = localStorage.getItem("campus-qa-auth");
  if (stored) {
    const parsed = JSON.parse(stored);
    if (parsed?.token) initial = parsed;
  }
} catch { localStorage.removeItem("campus-qa-auth"); }

export const useAuthStore = create<AuthState>((set, get) => ({
  token: initial.token,
  user: initial.user,
  login: (token, user) => {
    localStorage.setItem("campus-qa-auth", JSON.stringify({ token, user }));
    set({ token, user });
  },
  updateUser: (user) => {
    const token = get().token;
    if (token) localStorage.setItem("campus-qa-auth", JSON.stringify({ token, user }));
    set({ user });
  },
  logout: () => {
    localStorage.removeItem("campus-qa-auth");
    set({ token: null, user: null });
  },
  isAdmin: () => get().user?.role === "ADMIN",
}));
