import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button, EmptyState, PageHeader } from "@/components/ui";
import { useAuth } from "@/features/auth/AuthProvider";
import { t } from "@/i18n";

/**
 * In accounts mode the financial screens need a financial model: a demo persona's fixture, or the account's own
 * imported statements (ADR-029). An account with neither is asked to import statements. When the statements are
 * too few, the screen itself shows what the API says is missing (e.g. "history (at least 6 months, found 5)").
 */
export function FinancialRoute({ children }: { readonly children: ReactNode }) {
  const auth = useAuth();
  const isMock = import.meta.env.DEV && import.meta.env.VITE_ACCOUNTS_MOCK === "true";
  const source = auth.me?.data_source;
  const persona = source === "persona";
  const hasModel = persona || source === "statements";
  if (auth.mode === "accounts" && (!hasModel || isMock)) {
    return <>
      <PageHeader title={t("profile.emptyTitle")} subtitle={t("profile.emptyDetail")} />
      <EmptyState title={persona ? t("auth.mock") : t("profile.emptyTitle")}
        action={persona ? <Button asChild variant="primary"><Link to="/profile">{t("profile.openProfile")}</Link></Button>
          : <Button asChild variant="primary"><Link to="/statements">{t("profile.importStatements")}</Link></Button>}>
        {persona ? t("profile.mockFinancial") : t("profile.capacityMissing")}
      </EmptyState>
    </>;
  }
  return children;
}
