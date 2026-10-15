import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { PersonaProvider } from "@/api/hooks";
import { AppShell } from "@/app/AppShell";
import { Loading } from "@/components/ui";

// Each screen is its own chunk; the chart library loads only where a chart is drawn.
const OverviewPage = lazy(() => import("@/features/overview/OverviewPage").then((m) => ({ default: m.OverviewPage })));
const CommitmentsPage = lazy(() => import("@/features/commitments/CommitmentsPage").then((m) => ({ default: m.CommitmentsPage })));
const SimulatorPage = lazy(() => import("@/features/simulator/SimulatorPage").then((m) => ({ default: m.SimulatorPage })));
const PlanPage = lazy(() => import("@/features/plan/PlanPage").then((m) => ({ default: m.PlanPage })));
const CopilotPage = lazy(() => import("@/features/copilot/CopilotPage").then((m) => ({ default: m.CopilotPage })));
const AuditPage = lazy(() => import("@/features/audit/AuditPage").then((m) => ({ default: m.AuditPage })));
const ProfilePage = lazy(() => import("@/features/profile/ProfilePage").then((m) => ({ default: m.ProfilePage })));
const StatementsPage = lazy(() => import("@/features/statements/StatementsPage").then((m) => ({ default: m.StatementsPage })));
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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <PersonaProvider>
          <AppShell>
            <Suspense fallback={<Loading className="max-w-5xl" />}>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/commitments" element={<CommitmentsPage />} />
              <Route path="/simulator" element={<SimulatorPage />} />
              <Route path="/plan" element={<PlanPage />} />
              <Route path="/copilot" element={<CopilotPage />} />
              <Route path="/audit" element={<AuditPage />} />
              <Route path="/statements" element={<StatementsPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
            </Suspense>
          </AppShell>
        </PersonaProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
