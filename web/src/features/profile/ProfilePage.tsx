import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountsApi, type UserProfile } from "@/api/accounts";
import { usePersona } from "@/api/hooks";
import { Button, EmptyState, ErrorState, Loading, Notice, PageHeader, Section, StatusBadge, describeError } from "@/components/ui";
import { t, tDynamic } from "@/i18n";
import { useAuth } from "@/features/auth/AuthProvider";

function ProfileSettings({ profile }: { readonly profile: UserProfile }) {
  const { identity } = usePersona();
  const client = useQueryClient();
  const [displayName, setDisplayName] = useState(profile.display_name.untrusted_text);
  const update = useMutation({
    mutationFn: accountsApi.updateProfile,
    onSuccess: () => { void client.invalidateQueries({ queryKey: [identity.user_id, "profile"] }); },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    update.mutate({ display_name: displayName, language: profile.language });
  }

  return (
    <form onSubmit={submit} className="mt-6 flex flex-wrap items-end gap-4 border-t border-line pt-6">
      <div className="min-w-0 flex-1 sm:max-w-xs">
        <label htmlFor="profile-name" className="mb-2 block text-sm font-medium text-ink">{t("profile.name")}</label>
        <input id="profile-name" required maxLength={40} autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)}
          className="h-10 w-full rounded-control border border-control bg-surface px-3 text-sm text-ink focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25" />
      </div>
      <Button type="submit" variant="secondary" disabled={update.isPending || displayName === profile.display_name.untrusted_text} busy={update.isPending}>
        {update.isPending ? t("profile.saving") : t("profile.save")}
      </Button>
      {update.isError && <div className="w-full"><Notice tone="danger" title={describeError(update.error)} /></div>}
    </form>
  );
}

export function ProfilePage() {
  const auth = useAuth();
  const { identity } = usePersona();
  // A read-only demo persona has its fixture; an account has financial data once it imported statements (ADR-029).
  const readOnly = auth.me?.data_source === "persona";
  const hasModel = readOnly || auth.me?.data_source === "statements";
  const profile = useQuery({ queryKey: [identity.user_id, "profile"], queryFn: accountsApi.profile });
  const permitted = useQuery({
    queryKey: [identity.user_id, "profile-permitted", profile.data?.data?.declared_tolerance ?? "conservative", auth.me?.data_source],
    queryFn: () => accountsApi.permitted(profile.data?.data?.declared_tolerance ?? "conservative"),
    enabled: hasModel && Boolean(profile.data?.data),
  });

  if (profile.isPending) return <Loading className="max-w-3xl" />;
  if (profile.isError) return <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />;
  const record = profile.data.data;
  if (!record) return <EmptyState title={t("profile.emptyTitle")}>{t("profile.emptyDetail")}</EmptyState>;
  const declared = record.declared_tolerance ?? "conservative";
  const permission = permitted.data?.data;
  const limited = permission && permission.permitted !== permission.tolerance;

  return (
    <>
      <PageHeader title={t("profile.title")} subtitle={t("profile.description")} />
      <Section id="identity" title={record.display_name.untrusted_text} className="max-w-3xl">
        <p className="text-sm text-ink-2">{t("profile.language")}: {record.language}</p>
        {readOnly ? <p className="mt-4"><StatusBadge tone="neutral">{t("profile.readOnly")}</StatusBadge></p> :
          <ProfileSettings key={`${record.user_id}-${record.display_name.untrusted_text}`} profile={record} />}
      </Section>

      <div className="mt-10 grid gap-10 border-t border-line pt-10 lg:grid-cols-2">
        <Section id="tolerance" title={t("profile.declared")}>
          <p className="text-xl font-semibold text-ink">{record.declared_tolerance ? tDynamic("plan.profile.levels", declared) : t("profile.unanswered")}</p>
          {record.declared_tolerance === null && <p className="mt-2 text-sm text-ink-2">{t("profile.conservativeDefault")}</p>}
          {record.questionnaire_version && <p className="mt-2 font-mono text-xs text-ink-3">{t("profile.version", { version: record.questionnaire_version })}</p>}
          {!readOnly && <Button asChild variant="secondary" className="mt-5"><Link to="/onboarding">{t(record.questionnaire_version ? "profile.updateAnswers" : "profile.repeat")}</Link></Button>}
        </Section>
        <Section id="permitted" title={t("profile.permitted")}>
          {!hasModel ? <p className="text-sm text-ink-2">{t("profile.capacityMissing")}</p> : permitted.isPending ?
            <Loading className="max-w-xs" /> : permitted.isError ? <ErrorState error={permitted.error} onRetry={() => void permitted.refetch()} /> : permission && (
              <>
                <p className="text-xl font-semibold text-ink">{tDynamic("plan.profile.levels", permission.permitted)}</p>
                <p className="mt-2 text-sm text-ink-2">{t("profile.capacity")}: {tDynamic("plan.profile.levels", permission.capacity)}</p>
                <p className="mt-2 text-sm text-ink-2">{t("profile.permissionDetail")}</p>
                {limited && <div className="mt-4"><Notice tone="warning" title={t("profile.limited")}>{t("profile.limitedDetail")}</Notice></div>}
                {permitted.data?.warnings.map((warning) => <p key={warning.code} className="mt-3 text-sm text-ink-2">{warning.message}</p>)}
              </>
            )}
        </Section>
      </div>

      {!hasModel && (
        <Section id="financial-data" title={t("profile.emptyTitle")} className="mt-10 border-t border-line pt-10">
          <p className="max-w-prose text-sm text-ink-2">{t("profile.emptyDetail")}</p>
        </Section>
      )}
    </>
  );
}
