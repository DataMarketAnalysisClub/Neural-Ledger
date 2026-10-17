import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { PersonaProvider } from "@/api/hooks";
import { AppShell } from "@/app/AppShell";
import { Button, EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";
import { AuthProvider, useAuth } from "@/features/auth/AuthProvider";
import { t } from "@/i18n";

// Each screen is its own chunk; the chart library loads only where a chart is drawn.
const OverviewPage = lazy(() => import("@/features/overview/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const CommitmentsPage = lazy(() => import("@/features/commitments/CommitmentsPage").then((m) => ({ default: m.CommitmentsPage })));
const SimulatorPage = lazy(() => import("@/features/simulator/SimulatorPage").then((m) => ({ default: m.SimulatorPage })));
const PlanPage = lazy(() => import("@/features/plan/PlanPage").then((m) => ({ default: m.PlanPage })));
const CopilotPage = lazy(() => import("@/features/copilot/CopilotPage").then((m) => ({ default: m.CopilotPage })));
const AuditPage = lazy(() => import("@/features/audit/AuditPage").then((m) => ({ default: m.AuditPage })));
const ProfilePage = lazy(() => import("@/features/profile/ProfilePage").then((m) => ({ default: m.ProfilePage })));
const StatementsPage = lazy(() => import("@/features/statements/StatementsPage").then((m) => ({ default: m.StatementsPage })));
const SignInPage = lazy(() => import("@/features/auth/AuthPages").then((m) => ({ default: m.SignInPage })));
const SignUpPage = lazy(() => import("@/features/auth/AuthPages").then((m) => ({ default: m.SignUpPage })));
const OnboardingPage = lazy(() => import("@/features/onboarding/OnboardingPage").then((m) => ({ default: m.OnboardingPage })));
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      // An envelope that says INVALID_INPUT or INSUFFICIENT_DATA will say the same thing again.
      retry: (count, error) => !(error instanceof ApiError) && count < 2,
    },
    mutations: { retry: false },
  },
});

/** In accounts mode only a read-only demo persona has financial data; every other account stays empty. */
function FinancialRoute({ children }: { readonly children: React.ReactNode }) {
  const auth = useAuth();
  const isMock = import.meta.env.DEV && import.meta.env.VITE_ACCOUNTS_MOCK === "true";
  const persona = auth.me?.data_source === "persona";
  if (auth.mode === "accounts" && (!persona || isMock)) {
    return <>
      <PageHeader title={t("profile.emptyTitle")} subtitle={t("profile.emptyDetail")} />
      <EmptyState title={persona ? t("auth.mock") : t("profile.emptyTitle")}
        action={<Button asChild variant="primary"><Link to="/profile">{t("profile.openProfile")}</Link></Button>}>
        {persona ? t("profile.mockFinancial") : t("profile.capacityMissing")}
      </EmptyState>
    </>;
  }
  return children;
}

/**
 * Statements are the signed-in account's own ledger, open to every account (an empty one included) through its own
 * session cookie. Importing one adds no projection and changes no profile. The local mock stores no statements.
 */
function StatementsRoute({ children }: { readonly children: React.ReactNode }) {
  const auth = useAuth();
  const isMock = import.meta.env.DEV && import.meta.env.VITE_ACCOUNTS_MOCK === "true";
  if (auth.mode === "accounts" && isMock) {
    return <>
      <PageHeader title={t("statements.title")} />
      <EmptyState title={t("auth.mock")}>{t("statements.mockUnavailable")}</EmptyState>
    </>;
  }
  return children;
}

function AppRoutes() {
  const auth = useAuth();
  if (auth.pending) return <main className="mx-auto max-w-3xl px-6 py-16"><Loading /></main>;
  if (auth.error) return <main className="mx-auto max-w-3xl px-6 py-16"><ErrorState error={auth.error} onRetry={auth.retry} /></main>;
  if (auth.mode === "accounts" && !auth.me) return <Suspense fallback={<Loading className="mx-auto mt-16 max-w-md" />}>
    <Routes>
      <Route path="/signup" element={<SignUpPage />} />
      <Route path="*" element={<SignInPage />} />
    </Routes>
  </Suspense>;

  return <PersonaProvider key={auth.me?.user_id ?? "demo"}>
    <AppShell>
      <Suspense fallback={<Loading className="max-w-5xl" />}>
        <Routes>
          <Route path="/" element={<FinancialRoute><OverviewPage /></FinancialRoute>} />
          <Route path="/commitments" element={<FinancialRoute><CommitmentsPage /></FinancialRoute>} />
          <Route path="/simulator" element={<FinancialRoute><SimulatorPage /></FinancialRoute>} />
          <Route path="/plan" element={<FinancialRoute><PlanPage /></FinancialRoute>} />
          <Route path="/copilot" element={<FinancialRoute><CopilotPage /></FinancialRoute>} />
          <Route path="/audit" element={<FinancialRoute><AuditPage /></FinancialRoute>} />
          <Route path="/statements" element={<StatementsRoute><StatementsPage /></StatementsRoute>} />
          <Route path="/profile" element={auth.mode === "accounts" ? <ProfilePage /> : <Navigate to="/" replace />} />
          <Route path="/onboarding" element={auth.mode === "accounts" ? <OnboardingPage /> : <Navigate to="/" replace />} />
          <Route path="/signin" element={<Navigate to="/" replace />} />
          <Route path="/signup" element={<Navigate to={auth.mode === "accounts" ? "/onboarding" : "/"} replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  </PersonaProvider>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AuthProvider><AppRoutes /></AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
