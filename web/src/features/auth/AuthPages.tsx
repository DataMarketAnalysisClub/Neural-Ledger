import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button, Notice, describeError } from "@/components/ui";
import { BrandMark } from "@/components/BrandMark";
import { LanguagePicker } from "@/components/LanguagePicker";
import { t, tList } from "@/i18n";
import { useAuth } from "./AuthProvider";
import { LoginPreview } from "./LoginPreview";

// The design is drawn at 1216px wide. From lg every size is "design pixels" times --u, which grows with the window
// (up to 1.7x), so the page keeps its proportions on a big screen instead of floating in empty space.
const fieldClass = "h-[calc(42*var(--u))] w-full rounded-control border border-control bg-surface px-[calc(12*var(--u))] text-[calc(15*var(--u))] text-ink placeholder:text-ink-3 focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25";
const labelClass = "mb-[calc(6*var(--u))] block text-[calc(13*var(--u))] font-semibold text-ink";
const groupClass = "mb-[calc(14*var(--u))]";
const hintClass = "m-0 mt-[calc(6*var(--u))] text-[calc(12*var(--u))] text-ink-3";
const primaryClass = "h-[calc(44*var(--u))] w-full text-[calc(15*var(--u))] font-semibold";
const linkLineClass = "m-0 mt-[calc(16*var(--u))] text-[calc(13.5*var(--u))] text-ink-2";

/**
 * Two halves from lg: the product's pitch on teal with the real app peeking in, and the form's card on white. On a
 * phone the pitch is a short banner above the card. The form comes first in the document, so the h1 and the
 * fields lead; the sandbox notice closes the card.
 */
function AuthLayout({ title, description, children }: { readonly title: string; readonly description: string; readonly children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col [--u:1px] lg:grid lg:grid-cols-[1.15fr_1fr] lg:[--u:clamp(1px,calc(100vw/1216),1.7px)]">
      <main className="order-2 flex flex-1 items-center justify-center bg-surface px-3.5 pt-[18px] pb-[26px] lg:p-[calc(28*var(--u))]">
        <div className="w-full max-w-[calc(400*var(--u))] rounded-[calc(8*var(--u))] border border-line bg-surface px-[18px] py-[22px] lg:p-[calc(28*var(--u))]">
          <div className="mb-[calc(14*var(--u))] flex justify-end">
            <LanguagePicker />
          </div>
          <h1 className="m-0 mb-[calc(2*var(--u))] text-[calc(22*var(--u))] leading-normal font-semibold tracking-[-0.02em] text-ink">{title}</h1>
          <p className="m-0 mb-[calc(18*var(--u))] text-[calc(14*var(--u))] text-ink-2">{description}</p>
          {children}
          <p className="m-0 mt-[calc(14*var(--u))] flex items-center gap-[calc(6*var(--u))] text-[calc(12*var(--u))] text-ink-3">
            <span aria-hidden className="size-[calc(7*var(--u))] flex-none rounded-full bg-positive" />
            {t("auth.sandbox")}
          </p>
        </div>
      </main>
      <aside className="order-1 flex min-h-0 flex-col gap-3.5 overflow-hidden bg-accent px-5 py-[22px] text-on-accent lg:gap-[calc(22*var(--u))] lg:p-[calc(36*var(--u))] lg:pb-0">
        <div className="flex items-center gap-[calc(10*var(--u))] text-[calc(17*var(--u))] font-semibold tracking-[-0.01em]">
          <BrandMark className="size-[calc(32*var(--u))]" tile="var(--on-accent)" ink="var(--rail-bg)" dot="var(--accent)" />
          {t("app.name")}
        </div>
        <p className="m-0 text-[24px] leading-[1.08] font-bold tracking-[-0.03em] lg:text-[calc(40*var(--u))]">{t("auth.hero.title")}</p>
        <p className="m-0 max-w-[calc(400*var(--u))] text-[calc(15.5*var(--u))] text-on-accent">{t("auth.hero.lede")}</p>
        <ul aria-label={t("auth.hero.featuresLabel")} className="m-0 hidden list-none flex-wrap gap-[calc(8*var(--u))] p-0 lg:flex">
          {tList("auth.hero.features").map((feature) => (
            <li key={feature} className="rounded-full border border-on-accent/40 px-[calc(12*var(--u))] py-[calc(4*var(--u))] text-[calc(13*var(--u))]">{feature}</li>
          ))}
        </ul>
        {/* The real app, page after page, filling what is left under the chips and bleeding off the corner. */}
        <LoginPreview className="-mr-[calc(36*var(--u))] hidden min-h-[calc(220*var(--u))] flex-1 lg:block" />
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
        <div className={groupClass}>
          <label htmlFor="signin-email" className={labelClass}>{t("auth.email")}</label>
          <input id="signin-email" type="email" autoComplete="email" placeholder="you@example.com" required value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
        </div>
        <div className={groupClass}>
          <label htmlFor="signin-password" className={labelClass}>{t("auth.password")}</label>
          <input id="signin-password" type="password" autoComplete="current-password" placeholder="••••••••••" required value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
        </div>
        {error !== null && <div className={groupClass}><Notice tone="danger" title={describeError(error)} /></div>}
        <Button type="submit" variant="primary" className={primaryClass} busy={busy} disabled={busy}>{t("auth.signin.submit")}</Button>
      </form>
      <div role="group" aria-label={t("auth.explore.title")} aria-describedby="explore-note">
        <p className="mt-[calc(18*var(--u))] mb-[calc(12*var(--u))] flex items-center gap-[calc(10*var(--u))] text-[calc(12.5*var(--u))] text-ink-3 before:h-px before:flex-1 before:bg-line after:h-px after:flex-1 after:bg-line">{t("auth.explore.divider")}</p>
        <div className="grid grid-cols-2 gap-[calc(8*var(--u))]">
          {(["camila", "diego"] as const).map((persona) => (
            <button
              key={persona}
              type="button"
              onClick={() => void explore(persona)}
              disabled={busy}
              aria-label={t(`auth.explore.${persona}`)}
              className="flex h-[calc(44*var(--u))] cursor-pointer items-center justify-center gap-[calc(8*var(--u))] rounded-control border border-control bg-surface text-[calc(14*var(--u))] text-ink transition-colors hover:bg-canvas focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span aria-hidden className="grid size-[calc(22*var(--u))] place-items-center rounded-full bg-accent-soft text-[calc(12*var(--u))] font-bold text-accent-hover">{persona === "camila" ? "C" : "D"}</span>
              {persona === "camila" ? "Camila" : "Diego"}
            </button>
          ))}
        </div>
        <p id="explore-note" className="sr-only">{t("auth.explore.description")}</p>
      </div>
      <p className={linkLineClass}>{t("auth.signin.noAccount")} <Link to="/signup" className="font-semibold text-accent underline">{t("auth.signup.link")}</Link></p>
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
        <div className={groupClass}>
          <label htmlFor="signup-name" className={labelClass}>{t("auth.displayName")}</label>
          <input id="signup-name" autoComplete="name" required maxLength={40} value={displayName} onChange={(event) => setDisplayName(event.target.value)} className={fieldClass} />
          <p className={hintClass}>{t("auth.nameHint")}</p>
        </div>
        <div className={groupClass}>
          <label htmlFor="signup-email" className={labelClass}>{t("auth.email")}</label>
          <input id="signup-email" type="email" autoComplete="email" placeholder="you@example.com" required value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} />
        </div>
        <div className={groupClass}>
          <label htmlFor="signup-password" className={labelClass}>{t("auth.password")}</label>
          <input id="signup-password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} className={fieldClass} />
          <p className={hintClass}>{t("auth.passwordHint")}</p>
        </div>
        {error !== null && <div className={groupClass}><Notice tone="danger" title={describeError(error)} /></div>}
        <Button type="submit" variant="primary" className={primaryClass} busy={busy} disabled={busy}>{t("auth.signup.submit")}</Button>
      </form>
      <p className={linkLineClass}>{t("auth.signup.haveAccount")} <Link to="/signin" className="font-semibold text-accent underline">{t("auth.signin.link")}</Link></p>
    </AuthLayout>
  );
}
