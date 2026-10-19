import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { accountsApi, type AccountDeletion, type AccountDeletionInput, type Me, type SigninInput, type SignupInput } from "@/api/accounts";
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
  /** Delete the account (then signed out, every cached query dropped) or reset a demo persona (cache refreshed). */
  readonly deleteAccount: (input: AccountDeletionInput) => Promise<AccountDeletion>;
  /** Re-read /v1/me for the same session, e.g. after an import changed the account's data source (ADR-029). */
  readonly refreshMe: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { readonly children: ReactNode }) {
  const client = useQueryClient();
  const health = useHealth();
  const mode = health.data?.auth === "accounts" ? "accounts" : "demo";
  const [session, setSession] = useState<Session>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const generation = useRef(0);

  useEffect(() => {
    if (mode !== "accounts" || !health.data) return;
    let active = true;
    const started = generation.current;
    void accountsApi.me().then(
      (me) => { if (active && started === generation.current) setSession({ status: "authenticated", me }); },
      (error: unknown) => {
        if (!active || started !== generation.current) return;
        if (error instanceof ApiError && error.httpStatus === 401) setSession({ status: "anonymous" });
        else setSession({ status: "error", error });
      },
    );
    return () => { active = false; };
  }, [mode, health.data, attempt]);

  const transition = useCallback(async (authenticated: boolean) => {
    const started = ++generation.current;
    setSession({ status: "loading" });
    await client.cancelQueries();
    if (started !== generation.current) return;
    client.removeQueries({ predicate: (query) => query.queryKey[0] !== "health" });
    if (!authenticated) {
      setSession({ status: "anonymous" });
      return;
    }
    try {
      const me = await accountsApi.me();
      if (started === generation.current) setSession({ status: "authenticated", me });
    } catch (error) {
      if (started !== generation.current) return;
      if (error instanceof ApiError && error.httpStatus === 401) setSession({ status: "anonymous" });
      else setSession({ status: "error", error });
      throw error;
    }
  }, [client]);

  const signup = useCallback(async (input: SignupInput) => {
    await accountsApi.signup(input);
    await transition(true);
  }, [transition]);
  const signin = useCallback(async (input: SigninInput) => {
    await accountsApi.signin(input);
    await transition(true);
  }, [transition]);
  const explore = useCallback(async (persona: "camila" | "diego") => {
    await accountsApi.demoSession(persona);
    await transition(true);
  }, [transition]);
  const signout = useCallback(async () => {
    await accountsApi.signout();
    await transition(false);
  }, [transition]);
  const deleteAccount = useCallback(async (input: AccountDeletionInput) => {
    const result = await accountsApi.deleteAccount(input);
    if (result.status === "DELETED") await transition(false);
    else await client.invalidateQueries({ predicate: (query) => query.queryKey[0] !== "health" });
    return result;
  }, [transition, client]);
  const refreshMe = useCallback(async () => {
    if (mode !== "accounts") return;
    const started = generation.current;
    try {
      const me = await accountsApi.me();
      // Only if no sign-in, sign-out or switch happened meanwhile, and it is still the same account.
      setSession((current) => started === generation.current && current.status === "authenticated" && current.me.user_id === me.user_id
        ? { status: "authenticated", me } : current);
    } catch {
      // Keep the current state: the next request that needs a session reports the problem.
    }
  }, [mode]);
  const retry = useCallback(() => {
    generation.current += 1;
    setSession({ status: "loading" });
    if (health.isError) void health.refetch();
    else setAttempt((previous) => previous + 1);
  }, [health]);

  const value = useMemo<AuthContextValue>(() => ({
    mode, me: session.status === "authenticated" ? session.me : null,
    pending: health.isPending || (mode === "accounts" && session.status === "loading"),
    error: health.error ?? (session.status === "error" ? session.error : null),
    retry, signup, signin, explore, signout, deleteAccount, refreshMe,
  }), [mode, session, health.isPending, health.error, retry, signup, signin, explore, signout, deleteAccount, refreshMe]);
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
