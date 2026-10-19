import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Notice, Surface, describeError } from "@/components/ui";
import { BrandMark } from "@/components/BrandMark";
import { t, tList } from "@/i18n";
import { useAuth } from "./AuthProvider";

const fieldClass = "h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25";

/**
 * Two halves from lg: the product's pitch on teal with the real app peeking in, and the form's card. On a phone the
 * pitch is a short banner above the card. The form comes first in the document, so the h1 and the fields lead.
 */
function AuthLayout({ title, description, children }: { readonly title: string; readonly description: string; readonly children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col lg:grid lg:grid-cols-[1.1fr_1fr]">
      <main className="flex flex-1 items-center justify-center bg-canvas px-4 py-6 order-2 lg:px-8 lg:py-10">
        <div className="w-full max-w-md">
          <Surface className="p-6 sm:p-8">
            <h1 className="text-2xl font-semibold tracking-[-0.02em] text-ink">{title}</h1>
            <p className="mt-1.5 mb-6 text-sm text-ink-2">{description}</p>
            {children}
          </Surface>
          <p className="mt-4 flex items-center gap-2 text-xs text-ink-3">
            <span aria-hidden className="size-1.5 rounded-full bg-positive" />
            {t("auth.sandbox")}
          </p>
        </div>
      </main>
      <aside className="flex flex-col gap-4 overflow-hidden bg-accent px-5 pt-5 pb-6 text-on-accent order-1 lg:gap-6 lg:px-9 lg:pt-9 lg:pb-0">
        <div className="flex items-center gap-2.5 text-lg font-semibold tracking-[-0.01em]">
          <BrandMark tile="var(--on-accent)" ink="var(--rail-bg)" dot="var(--accent)" />
          {t("app.name")}
        </div>
        <p className="max-w-[18ch] text-2xl leading-[1.1] font-semibold tracking-[-0.03em] sm:max-w-[22ch] lg:text-[2.625rem]">{t("auth.hero.title")}</p>
        <p className="max-w-[46ch] text-sm text-on-accent/95 lg:text-base">{t("auth.hero.lede")}</p>
        <ul aria-label={t("auth.hero.featuresLabel")} className="hidden flex-wrap gap-2 lg:flex">
          {tList("auth.hero.features").map((feature) => (
            <li key={feature} className="rounded-full border border-on-accent/40 px-3 py-1 text-sm">{feature}</li>
          ))}
        </ul>
        {/* The real app, decorative: it enters from below and bleeds off the corner. */}
        <img
          src="/login-preview.png"
          alt=""
          className="mt-auto ml-auto hidden max-h-[19.5rem] w-[108%] max-w-none self-end rounded-tl-object border border-r-0 border-b-0 border-on-accent/35 bg-surface object-cover object-top-left animate-[rise_900ms_var(--ease-out)_both] motion-reduce:animate-none lg:block"
        />
      </aside>
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
      <div className="mt-6" role="group" aria-label={t("auth.explore.title")}>
        <p className="flex items-center gap-3 text-xs text-ink-3 before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">{t("auth.explore.divider")}</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {(["camila", "diego"] as const).map((persona) => (
            <Button key={persona} type="button" onClick={() => void explore(persona)} disabled={busy} aria-label={t(`auth.explore.${persona}`)} className="justify-center gap-2">
              <span aria-hidden className="grid size-5.5 place-items-center rounded-full bg-accent-soft text-xs font-bold text-accent">{persona === "camila" ? "C" : "D"}</span>
              {persona === "camila" ? "Camila" : "Diego"}
            </Button>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-3">{t("auth.explore.description")}</p>
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
