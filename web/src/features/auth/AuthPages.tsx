import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Notice, Surface, describeError } from "@/components/ui";
import { t } from "@/i18n";
import { useAuth } from "./AuthProvider";

const fieldClass = "h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25";

function AuthLayout({ title, description, children }: { readonly title: string; readonly description: string; readonly children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas px-6 py-10 sm:justify-center">
      <main className="mx-auto w-full max-w-md">
        <p className="mb-8 text-sm font-semibold text-ink">{t("app.name")}</p>
        <h1 className="text-2xl font-semibold text-ink">{title}</h1>
        <p className="mt-2 text-base text-ink-2">{description}</p>
        <Surface className="mt-8 p-6 sm:p-8">{children}</Surface>
        <p className="mt-6 text-xs text-ink-3">{t("auth.sandbox")}</p>
      </main>
    </div>
  );
}

export function SignInPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.signin({ email, password });
      navigate("/", { replace: true });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  async function explore(persona: "camila" | "diego") {
    setBusy(true);
    setError(null);
    try {
      await auth.explore(persona);
      navigate("/", { replace: true });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={t("auth.signin.title")} description={t("auth.signin.description")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-5">
        <div>
          <label htmlFor="signin-email" className="mb-2 block text-sm font-medium text-ink">{t("auth.email")}</label>
          <input id="signin-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
        </div>
        <div>
          <label htmlFor="signin-password" className="mb-2 block text-sm font-medium text-ink">{t("auth.password")}</label>
          <input id="signin-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
        </div>
        {error !== null && <Notice tone="danger" title={describeError(error)} />}
        <Button type="submit" variant="primary" className="w-full" busy={busy} disabled={busy}>{t("auth.signin.submit")}</Button>
      </form>
      <p className="mt-5 text-sm text-ink-2">{t("auth.signin.noAccount")} <Link to="/signup" className="font-medium text-accent underline">{t("auth.signup.link")}</Link></p>
      <div className="mt-8 border-t border-line pt-6">
        <p className="text-sm font-medium text-ink">{t("auth.explore.title")}</p>
        <p className="mt-1 text-sm text-ink-2">{t("auth.explore.description")}</p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="button" onClick={() => void explore("camila")} disabled={busy}>{t("auth.explore.camila")}</Button>
          <Button type="button" onClick={() => void explore("diego")} disabled={busy}>{t("auth.explore.diego")}</Button>
        </div>
      </div>
    </AuthLayout>
  );
}

export function SignUpPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await auth.signup({ email, password, display_name: displayName });
      navigate("/onboarding", { replace: true });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={t("auth.signup.title")} description={t("auth.signup.description")}>
      <form onSubmit={(event) => void submit(event)} className="space-y-5">
        <div>
          <label htmlFor="signup-name" className="mb-2 block text-sm font-medium text-ink">{t("auth.displayName")}</label>
          <input id="signup-name" autoComplete="name" required maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className={fieldClass} />
          <p className="mt-2 text-xs text-ink-3">{t("auth.nameHint")}</p>
        </div>
        <div>
          <label htmlFor="signup-email" className="mb-2 block text-sm font-medium text-ink">{t("auth.email")}</label>
          <input id="signup-email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
        </div>
        <div>
          <label htmlFor="signup-password" className="mb-2 block text-sm font-medium text-ink">{t("auth.password")}</label>
          <input id="signup-password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
          <p className="mt-2 text-xs text-ink-3">{t("auth.passwordHint")}</p>
        </div>
        {error !== null && <Notice tone="danger" title={describeError(error)} />}
        <Button type="submit" variant="primary" className="w-full" busy={busy} disabled={busy}>{t("auth.signup.submit")}</Button>
      </form>
      <p className="mt-5 text-sm text-ink-2">{t("auth.signup.haveAccount")} <Link to="/signin" className="font-medium text-accent underline">{t("auth.signin.link")}</Link></p>
    </AuthLayout>
  );
}
