import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { accountsApi } from "@/api/accounts";
import { usePersona } from "@/api/hooks";
import { Button, EmptyState, ErrorState, Loading, PageHeader, Surface } from "@/components/ui";
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
  if (questionnaire.isPending) return <Loading className="max-w-3xl" />;
  if (questionnaire.isError) return <ErrorState error={questionnaire.error} onRetry={() => void questionnaire.refetch()} />;

  const definition = questionnaire.data.data;
  const question = definition?.questions[step];
  if (!definition || !question) return <EmptyState title={t("onboarding.unavailable")} />;
  const selected = answers[question.question_id];
  const last = step === definition.questions.length - 1;

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
    <div className="mx-auto max-w-3xl">
      <PageHeader title={t("onboarding.title")} subtitle={t("onboarding.description")} />
      <p className="num mb-4 text-sm font-medium text-ink-2">{t("onboarding.step", { current: step + 1, total: definition.questions.length })}</p>
      <Surface className="p-6 sm:p-8">
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
          <div className="mt-8 flex flex-wrap items-center gap-3 border-t border-line pt-6">
            {step > 0 && <Button type="button" onClick={() => setStep((previous) => previous - 1)}>{t("onboarding.back")}</Button>}
            <Button type="submit" variant="primary" disabled={!selected || submit.isPending} busy={submit.isPending}>
              {submit.isPending ? t("onboarding.saving") : last ? t("onboarding.submit") : t("onboarding.next")}
            </Button>
            <Button asChild variant="quiet"><Link to="/profile">{t("onboarding.later")}</Link></Button>
          </div>
        </form>
      </Surface>
      <p className="mt-4 text-sm text-ink-2">{t("onboarding.laterHint")}</p>
    </div>
  );
}
