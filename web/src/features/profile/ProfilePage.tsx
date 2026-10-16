import { Info } from "@phosphor-icons/react";
import { useProfile, useQuestionnaire } from "@/api/hooks";
import { ErrorState, Loading, Notice, PageHeader, Section } from "@/components/ui";
import { t, tDynamic } from "@/i18n";

/**
 * The persona's stored profile, read only. Editing it and answering the questionnaire need backend endpoints that
 * are not wired yet (PATCH /v1/profile, POST /v1/profile/questionnaire), so this page has no form.
 */
export function ProfilePage() {
  const profile = useProfile();
  const questionnaire = useQuestionnaire();

  const queries = [profile, questionnaire];
  const failed = queries.find((q) => q.isError);
  if (failed) return <ErrorState error={failed.error} onRetry={() => queries.forEach((q) => void q.refetch())} />;
  if (queries.some((q) => q.isPending)) return <Loading className="max-w-3xl" />;

  const p = profile.data!.data!;
  const q = questionnaire.data!.data!;

  const rows: [string, string][] = [
    // display_name is untrusted text: rendered as a plain string, never markup.
    [t("profile.name"), p.display_name.untrusted_text],
    [t("profile.language"), tDynamic("profile.languages", p.language)],
    [t("profile.tolerance"), p.declared_tolerance ? tDynamic("plan.profile.levels", p.declared_tolerance) : t("profile.notDeclared")],
    [
      t("profile.questionnaire"),
      p.questionnaire.length === 0
        ? t("profile.notAnswered", { version: q.version, count: q.questions.length })
        : t("profile.answered", { version: p.questionnaire_version ?? q.version, answered: p.questionnaire.length, count: q.questions.length }),
    ],
  ];

  return (
    <>
      <PageHeader title={t("profile.title")} subtitle={t("profile.subtitle")} />
      <div className="max-w-3xl space-y-10">
        <Section id="profile-details">
          <dl className="divide-y divide-line border-y border-line text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="grid gap-1 py-3 sm:grid-cols-[220px_1fr] sm:gap-4">
                <dt className="text-ink-2">{label}</dt>
                <dd className="break-words text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </Section>
        <Notice tone="neutral" icon={Info} title={t("profile.readOnly")}>
          {t("profile.readOnlyDetail")}
        </Notice>
      </div>
    </>
  );
}
