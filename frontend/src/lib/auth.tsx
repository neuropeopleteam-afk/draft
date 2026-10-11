import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, isTransient, tokenStore, type MeOut } from "./api";

interface AuthState {
  me: MeOut | null;
  loading: boolean;
  /** Я16: /api/me не ответил из-за сети или сервера (5xx, обрыв): вход сохранён, кабинет показывает экран повтора. */
  error: unknown | null;
  /** сколько стартовых попыток подряд не удалось (для автоповтора экрана StartupError) */
  failures: number;
  retry: () => void;
  signIn: (token: string) => Promise<MeOut>;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown | null>(null);
  const [failures, setFailures] = useState(0);

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) { setMe(null); setError(null); setLoading(false); return; }
    try { setMe(await api<MeOut>("/me")); setError(null); setFailures(0); }
    catch (e) {
      // Я16: 5xx и обрыв сети — не повод выходить из учётки (раньше токен стирался и кабинет уводил на /login)
      if (isTransient(e)) { setError(e); setFailures((n) => n + 1); }
      else { tokenStore.clear(); setMe(null); setError(null); setFailures(0); }
    }
    finally { setLoading(false); }
  }, []);
  const retry = useCallback(() => { setLoading(true); void refresh(); }, [refresh]);

  useEffect(() => { void refresh(); }, [refresh]);

  const signIn = async (token: string) => {
    tokenStore.set(token);
    const m = await api<MeOut>("/me");
    setMe(m);
    return m;
  };
  const signOut = () => { tokenStore.clear(); setMe(null); setError(null); };

  return <Ctx.Provider value={{ me, loading, error, failures, retry, signIn, signOut, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth вне AuthProvider");
  return v;
}

export const cabinetPath = (role: string) => (role === "employer" ? "/employer" : role === "admin" || role === "expert" ? "/expert" : role === "fsp_analyst" ? "/fsp" : "/candidate");
