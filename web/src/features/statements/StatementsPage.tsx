import { EmptyState, PageHeader } from "@/components/ui";
import { t } from "@/i18n";

/**
 * Bank statement import ships with the /v1/statements API (staging branch). Until that API is on
 * main, the route explains why it is unavailable instead of showing mock data.
 */
export function StatementsPage({ unavailable = false }: { unavailable?: boolean }) {
  return (
    <>
      <PageHeader title={t("statements.title")} />
      {unavailable && (
        <EmptyState title={t("statements.unavailable")}>
          <p>{t("statements.unavailableDetail")}</p>
        </EmptyState>
      )}
    </>
  );
}
