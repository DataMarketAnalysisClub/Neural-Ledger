import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { accountsApi, type Me, type SigninInput, type SignupInput } from "@/api/accounts";
import { useHealth } from "@/api/hooks";

type Session =
  | { readonly status: "loading" }
  | { readonly status: "anonymous" }
  | { readonly status: "authenticated"; readonly me: Me }
  | { readonly status: "error"; readonly error: unknown };

export interface AuthContextValue {
  readonly mode: "demo" | "accounts";
  readonly me: Me | null;
  readonly pending: boolean;
  readonly error: unknown;
  readonly retry: () => void;
  readonly signup: (input: SignupInput) => Promise<void>;
  readonly signin: (input: SigninInput) => Promise<void>;
  readonly explore: (persona: "camila" | "diego") => Promise<void>;
  readonly signout: () => Promise<void>;
  readonly refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { readonly children: ReactNode }) {
  const client = useQueryClient();
  const health = useHealth();
  const mode = health.data?.auth === "accounts" ? "accounts" : "demo";
  const [session, setSession] = useState<Session>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (mode !== "accounts" || !health.data) return;
    let active = true;
    void accountsApi.me().then(
      (me) => { if (active) setSession({ status: "authenticated", me }); },
      (error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError && error.httpStatus === 401) setSession({ status: "anonymous" });
        else setSession({ status: "error", error });
      },
    );
    return () => { active = false; };
  }, [mode, health.data, attempt]);

  const transition = useCallback(async (me: Me | null) => {
    await client.cancelQueries();
    client.removeQueries({ predicate: (query) => query.queryKey[0] !== "health" });
    setSession(me ? { status: "authenticated", me } : { status: "anonymous" });
  }, [client]);

  const signup = useCallback(async (input: SignupInput) => {
    await accountsApi.signup(input);
    await transition(await accountsApi.me());
  }, [transition]);
  const signin = useCallback(async (input: SigninInput) => {
    await accountsApi.signin(input);
    await transition(await accountsApi.me());
  }, [transition]);
  const explore = useCallback(async (persona: "camila" | "diego") => {
    await accountsApi.demoSession(persona);
    await transition(await accountsApi.me());
  }, [transition]);
  const signout = useCallback(async () => {
    await accountsApi.signout();
    await transition(null);
  }, [transition]);
  const refreshMe = useCallback(async () => {
    await transition(await accountsApi.me());
  }, [transition]);
  const retry = useCallback(() => {
    setSession({ status: "loading" });
    if (health.isError) void health.refetch();
    else setAttempt((previous) => previous + 1);
  }, [health]);

  const value = useMemo<AuthContextValue>(() => ({
    mode, me: session.status === "authenticated" ? session.me : null,
    pending: health.isPending || (mode === "accounts" && session.status === "loading"),
    error: health.error ?? (session.status === "error" ? session.error : null),
    retry, signup, signin, explore, signout, refreshMe,
  }), [mode, session, health.isPending, health.error, retry, signup, signin, explore, signout, refreshMe]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}

export function useAuth(): AuthContextValue {
  const value = useOptionalAuth();
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}
