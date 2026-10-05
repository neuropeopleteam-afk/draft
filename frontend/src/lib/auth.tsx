import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, tokenStore, type MeOut } from "./api";

interface AuthState {
  me: MeOut | null;
  loading: boolean;
  signIn: (token: string) => Promise<MeOut>;
  signOut: () => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeOut | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) { setMe(null); setLoading(false); return; }
    try { setMe(await api<MeOut>("/me")); }
    catch { tokenStore.clear(); setMe(null); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const signIn = async (token: string) => {
    tokenStore.set(token);
    const m = await api<MeOut>("/me");
    setMe(m);
    return m;
  };
  const signOut = () => { tokenStore.clear(); setMe(null); };

  return <Ctx.Provider value={{ me, loading, signIn, signOut, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth вне AuthProvider");
  return v;
}

export const cabinetPath = (role: string) => (role === "employer" ? "/employer" : "/candidate");
