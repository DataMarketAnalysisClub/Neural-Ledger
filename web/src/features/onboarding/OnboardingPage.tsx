import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { accountsApi } from "@/api/accounts";
import { usePersona } from "@/api/hooks";
import { Check } from "@phosphor-icons/react";
import { Button, EmptyState, ErrorState, Loading, Surface, cn } from "@/components/ui";
import { t, tDynamic } from "@/i18n";
import { useAuth } from "@/features/auth/AuthProvider";

export function OnboardingPage() {
  const auth = useAuth();
  const { identity } = usePersona();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Readonly<Record<string, string>>>({});
  const questionnaire = useQuery({ queryKey: [identity.user_id, "questionnaire"], queryFn: accountsApi.questionnaire });
  const submit = useMutation({ mutationFn: accountsApi.submitQuestionnaire });

  if (auth.me?.user_id === "camila" || auth.me?.user_id === "diego") return <Navigate to="/profile" replace />;
  if (questionnaire.isPending) return <Stage><Loading /></Stage>;
  if (questionnaire.isError) return <Stage><ErrorState error={questionnaire.error} onRetry={() => void questionnaire.refetch()} /></Stage>;

  const definition = questionnaire.data.data;
  const question = definition?.questions[step];
  if (!definition || !question) return <Stage><EmptyState title={t("onboarding.unavailable")} /></Stage>;
  const selected = answers[question.question_id];
  const total = definition.questions.length;
  const last = step === total - 1;
  // A person can revisit what they answered, never skip a question: the furthest step is the first one still empty.
  const firstEmpty = definition.questions.findIndex(({ question_id }) => !answers[question_id]);
  const furthest = firstEmpty === -1 ? total - 1 : firstEmpty;

  function advance(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !definition) return;
    if (!last) {
      setStep((previous) => previous + 1);
      return;
    }
    submit.mutate({
      version: definition.version,
      answers: definition.questions.map(({ question_id }) => ({ question_id, option_id: answers[question_id] ?? "" })),
    }, { onSuccess: () => {
      void client.invalidateQueries({ queryKey: [identity.user_id, "profile"] });
      navigate("/profile", { replace: true });
    } });
  }

  return (
    <Stage>
      <header className="mb-6 sm:mb-8">
        <h1 className="text-2xl font-semibold tracking-[-0.02em] text-ink sm:text-3xl">{t("onboarding.title")}</h1>
        <p className="mt-2 text-sm text-ink-2 sm:text-base">{t("onboarding.description")}</p>
      </header>
      <ol aria-label={t("onboarding.timeline")} className="mb-3 flex items-center">
        {definition.questions.map(({ question_id, copy_key }, index) => {
          const reachable = index <= furthest;
          const state = index === step ? "current" : answers[question_id] ? "answered" : reachable ? "pending" : "locked";
          return (
            <li key={question_id} className={cn("flex items-center", index < total - 1 && "flex-1")}>
              <button
                type="button"
                disabled={!reachable}
                aria-current={state === "current" ? "step" : undefined}
                aria-label={t("onboarding.stepAria", { current: index + 1, total, state: t(`onboarding.state.${state}`) })}
                title={tDynamic("questionnaire", copy_key.replace(/^questionnaire\./, ""), "onboarding.unavailable")}
                onClick={() => setStep(index)}
                className="group flex size-11 shrink-0 items-center justify-center rounded-full focus-visible:outline-none disabled:cursor-not-allowed"
              >
                <span
                  className={cn(
                    "num flex size-8 items-center justify-center rounded-full border text-sm font-semibold transition-colors group-focus-visible:ring-2 group-focus-visible:ring-accent/40",
                    state === "current" && "border-accent bg-surface text-accent ring-2 ring-accent/25",
                    state === "answered" && "border-ink bg-ink text-on-accent group-hover:bg-ink-2",
                    state === "pending" && "border-control bg-surface text-ink group-hover:bg-canvas",
                    state === "locked" && "border-line bg-surface text-ink-3",
                  )}
                >
                  {state === "answered" ? <Check aria-hidden weight="bold" className="size-4" /> : index + 1}
                </span>
              </button>
              {index < total - 1 && <span aria-hidden className={cn("h-px flex-1", answers[question_id] ? "bg-ink" : "bg-line")} />}
            </li>
          );
        })}
      </ol>
      <p className="num mb-4 text-sm font-medium text-ink-2">{t("onboarding.step", { current: step + 1, total })}</p>
      <Surface className="p-5 sm:p-8">
        <form onSubmit={advance}>
          <fieldset>
            <legend className="text-lg font-semibold text-ink">{tDynamic("questionnaire", question.copy_key.replace(/^questionnaire\./, ""), "onboarding.unavailable")}</legend>
            <div className="mt-6 space-y-2">
              {question.options.map((option) => (
                <label key={option.option_id} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-control border border-line bg-surface px-4 py-3 text-sm text-ink-2 hover:bg-canvas has-[:checked]:bg-canvas has-[:checked]:font-medium has-[:checked]:text-ink">
                  <input type="radio" name={question.question_id} value={option.option_id} checked={selected === option.option_id}
                    onChange={() => setAnswers((previous) => ({ ...previous, [question.question_id]: option.option_id }))} className="size-4 accent-accent" />
                  {tDynamic("questionnaire", option.copy_key.replace(/^questionnaire\./, ""), "onboarding.unavailable")}
                </label>
              ))}
            </div>
          </fieldset>
          {submit.isError && <div className="mt-4"><ErrorState error={submit.error} /></div>}
          <div className="mt-8 flex flex-col gap-3 border-t border-line pt-6 sm:flex-row sm:flex-wrap sm:items-center">
            {step > 0 && <Button type="button" className="order-2 w-full sm:order-1 sm:w-auto" onClick={() => setStep((previous) => previous - 1)}>{t("onboarding.back")}</Button>}
            <Button type="submit" variant="primary" className="order-1 w-full sm:order-2 sm:w-auto" disabled={!selected || submit.isPending} busy={submit.isPending}>
              {submit.isPending ? t("onboarding.saving") : last ? t("onboarding.submit") : t("onboarding.next")}
            </Button>
            <Button asChild variant="quiet" className="order-3 w-full sm:ml-auto sm:w-auto"><Link to="/profile">{t("onboarding.later")}</Link></Button>
          </div>
        </form>
      </Surface>
      <p className="mt-4 text-sm text-ink-2">{t("onboarding.laterHint")}</p>
    </Stage>
  );
}

/** The questionnaire is its own screen: the canvas and one column, with none of the app's navigation around it. */
function Stage({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-dvh bg-canvas px-4 pt-8 pb-[max(2rem,env(safe-area-inset-bottom))] sm:px-6 sm:pt-16">
      <div className="mx-auto w-full max-w-xl">{children}</div>
    </main>
  );
}
