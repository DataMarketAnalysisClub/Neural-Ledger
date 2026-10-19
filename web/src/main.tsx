import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { PersonaProvider } from "@/api/hooks";
import { AppShell } from "@/app/AppShell";
import { MobileLanding } from "@/app/mobileLanding";
import { FinancialRoute } from "@/app/FinancialRoute";
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";
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
const ConnectionsPage = lazy(() => import("@/features/connections/ConnectionsPage").then((m) => ({ default: m.ConnectionsPage })));
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
    <Routes>
      {/* The questionnaire is its own screen, outside the app shell. */}
      <Route path="/onboarding" element={auth.mode === "accounts"
        ? <Suspense fallback={<Loading className="mx-auto mt-16 max-w-md" />}><OnboardingPage /></Suspense>
        : <Navigate to="/" replace />} />
      <Route element={<AppShell><Suspense fallback={<Loading className="max-w-5xl" />}><Outlet /></Suspense></AppShell>}>
        <Route path="/" element={<MobileLanding><FinancialRoute><OverviewPage /></FinancialRoute></MobileLanding>} />
        <Route path="/commitments" element={<FinancialRoute><CommitmentsPage /></FinancialRoute>} />
        <Route path="/simulator" element={<FinancialRoute><SimulatorPage /></FinancialRoute>} />
        <Route path="/plan" element={<FinancialRoute><PlanPage /></FinancialRoute>} />
        <Route path="/copilot" element={<FinancialRoute><CopilotPage /></FinancialRoute>} />
        <Route path="/audit" element={<FinancialRoute><AuditPage /></FinancialRoute>} />
        <Route path="/statements" element={<StatementsRoute><StatementsPage /></StatementsRoute>} />
        <Route path="/connections" element={<ConnectionsPage />} />
        <Route path="/profile" element={auth.mode === "accounts" ? <ProfilePage /> : <Navigate to="/" replace />} />
        <Route path="/signin" element={<Navigate to="/" replace />} />
        <Route path="/signup" element={<Navigate to={auth.mode === "accounts" ? "/onboarding" : "/"} replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
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
