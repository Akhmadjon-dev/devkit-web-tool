import { create } from "zustand";

const STORAGE_KEY = "devworkspace_token";

function readInitialToken(): string | null {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem(STORAGE_KEY, fromUrl);
    url.searchParams.delete("token");
    window.history.replaceState({}, "", url.toString());
    return fromUrl;
  }
  return localStorage.getItem(STORAGE_KEY);
}

interface AuthState {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

export const useAuth = create<AuthState>((set) => ({
  token: readInitialToken(),
  setToken: (token: string) => {
    localStorage.setItem(STORAGE_KEY, token);
    set({ token });
  },
  clearToken: () => {
    localStorage.removeItem(STORAGE_KEY);
    set({ token: null });
  },
}));
