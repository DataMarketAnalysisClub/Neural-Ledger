import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Notice, describeError } from "@/components/ui";
import { BrandMark } from "@/components/BrandMark";
import { t, tList } from "@/i18n";
import { useAuth } from "./AuthProvider";

const fieldClass = "h-[42px] w-full rounded-control border border-control bg-surface px-3 text-[15px] text-ink placeholder:text-ink-3 focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25";
const labelClass = "mb-1.5 block text-[13px] font-semibold text-ink";

/**
 * Two halves from lg: the product's pitch on teal with the real app peeking in, and the form's card on white. On a
 * phone the pitch is a short banner above the card. The form comes first in the document, so the h1 and the
 * fields lead; the sandbox notice closes the card.
 */
function AuthLayout({ title, description, children }: { readonly title: string; readonly description: string; readonly children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col lg:grid lg:grid-cols-[1.15fr_1fr]">
      <main className="order-2 flex flex-1 items-center justify-center bg-surface px-3.5 pt-[18px] pb-[26px] lg:p-7">
        <div className="w-full max-w-[400px] rounded-lg border border-line bg-surface px-[18px] py-[22px] lg:p-7">
          <h1 className="m-0 mb-0.5 text-[22px] leading-normal font-semibold tracking-[-0.02em] text-ink">{title}</h1>
          <p className="m-0 mb-[18px] text-sm text-ink-2">{description}</p>
          {children}
          <p className="m-0 mt-3.5 flex items-center gap-1.5 text-xs text-ink-3">
            <span aria-hidden className="size-[7px] flex-none rounded-full bg-positive" />
            {t("auth.sandbox")}
          </p>
        </div>
      </main>
      <aside className="order-1 flex flex-col gap-3.5 overflow-hidden bg-accent px-5 py-[22px] text-on-accent lg:gap-[22px] lg:p-9 lg:pb-0">
        <div className="flex items-center gap-2.5 text-[17px] font-semibold tracking-[-0.01em]">
          <BrandMark tile="var(--on-accent)" ink="var(--rail-bg)" dot="var(--accent)" />
          {t("app.name")}
        </div>
        <p className="m-0 text-[24px] leading-[1.08] font-bold tracking-[-0.03em] lg:text-[clamp(26px,3.3vw,42px)]">{t("auth.hero.title")}</p>
        <p className="m-0 max-w-[25rem] text-[15.5px] text-on-accent">{t("auth.hero.lede")}</p>
        <ul aria-label={t("auth.hero.featuresLabel")} className="m-0 hidden list-none flex-wrap gap-2 p-0 lg:flex">
          {tList("auth.hero.features").map((feature) => (
            <li key={feature} className="rounded-full border border-on-accent/40 px-3 py-1 text-[13px]">{feature}</li>
          ))}
        </ul>
        {/* The real app, decorative: it enters from below and bleeds off the corner. */}
        <img
          src="/login-preview.png"
          alt=""
          className="mt-auto -mr-9 ml-0 hidden max-h-[310px] w-[108%] max-w-none self-end overflow-hidden rounded-tl-[10px] border border-r-0 border-b-0 border-on-accent/35 bg-surface object-cover object-top-left animate-[rise_900ms_var(--ease-out)_both] motion-reduce:animate-none lg:block"
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
      <form onSubmit={(event) => void submit(event)}>
        <div className="mb-3.5">
          <label htmlFor="signin-email" className={labelClass}>{t("auth.email")}</label>
          <input id="signin-email" type="email" autoComplete="email" placeholder="you@example.com" required value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
        </div>
        <div className="mb-3.5">
          <label htmlFor="signin-password" className={labelClass}>{t("auth.password")}</label>
          <input id="signin-password" type="password" autoComplete="current-password" placeholder="••••••••••" required value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
        </div>
        {error !== null && <div className="mb-3.5"><Notice tone="danger" title={describeError(error)} /></div>}
        <Button type="submit" variant="primary" className="h-11 w-full text-[15px] font-semibold" busy={busy} disabled={busy}>{t("auth.signin.submit")}</Button>
      </form>
      <div role="group" aria-label={t("auth.explore.title")} aria-describedby="explore-note">
        <p className="mt-[18px] mb-3 flex items-center gap-2.5 text-[12.5px] text-ink-3 before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">{t("auth.explore.divider")}</p>
        <div className="grid grid-cols-2 gap-2">
          {(["camila", "diego"] as const).map((persona) => (
            <button
              key={persona}
              type="button"
              onClick={() => void explore(persona)}
              disabled={busy}
              aria-label={t(`auth.explore.${persona}`)}
              className="flex h-11 cursor-pointer items-center justify-center gap-2 rounded-control border border-control bg-surface text-sm text-ink transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span aria-hidden className="grid size-[22px] place-items-center rounded-full bg-accent-soft text-xs font-bold text-accent-hover">{persona === "camila" ? "C" : "D"}</span>
              {persona === "camila" ? "Camila" : "Diego"}
            </button>
          ))}
        </div>
        <p id="explore-note" className="sr-only">{t("auth.explore.description")}</p>
      </div>
      <p className="m-0 mt-4 text-[13.5px] text-ink-2">{t("auth.signin.noAccount")} <Link to="/signup" className="font-semibold text-accent underline">{t("auth.signup.link")}</Link></p>
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
      <form onSubmit={(event) => void submit(event)}>
        <div className="mb-3.5">
          <label htmlFor="signup-name" className={labelClass}>{t("auth.displayName")}</label>
          <input id="signup-name" autoComplete="name" required maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className={fieldClass} />
          <p className="m-0 mt-1.5 text-xs text-ink-3">{t("auth.nameHint")}</p>
        </div>
        <div className="mb-3.5">
          <label htmlFor="signup-email" className={labelClass}>{t("auth.email")}</label>
          <input id="signup-email" type="email" autoComplete="email" placeholder="you@example.com" required value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
        </div>
        <div className="mb-3.5">
          <label htmlFor="signup-password" className={labelClass}>{t("auth.password")}</label>
          <input id="signup-password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
          <p className="m-0 mt-1.5 text-xs text-ink-3">{t("auth.passwordHint")}</p>
        </div>
        {error !== null && <div className="mb-3.5"><Notice tone="danger" title={describeError(error)} /></div>}
        <Button type="submit" variant="primary" className="h-11 w-full text-[15px] font-semibold" busy={busy} disabled={busy}>{t("auth.signup.submit")}</Button>
      </form>
      <p className="m-0 mt-4 text-[13.5px] text-ink-2">{t("auth.signup.haveAccount")} <Link to="/signin" className="font-semibold text-accent underline">{t("auth.signin.link")}</Link></p>
    </AuthLayout>
  );
}
