import React, { useEffect, useState } from "react";
import {
  ShieldCheck,
  LayoutDashboard,
  Calculator,
  Code2,
  BookOpen,
  LogOut,
  Activity,
} from "lucide-react";
import {
  apiClient,
  EnrollmentResponse,
  setAuthToken,
  SocraticTurnResponse,
  TrackType,
  UserResponse,
} from "./types/api";
import { AuthModal } from "./components/AuthModal";
import { SubjectDashboard } from "./components/SubjectDashboard";
import { MathWorkspace } from "./components/MathWorkspace";
import { CodeWorkspace } from "./components/CodeWorkspace";
import { RagWorkspace } from "./components/RagWorkspace";
import { NeuroSymbolicAuditDrawer } from "./components/NeuroSymbolicAuditDrawer";

export const App: React.FC = () => {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [activeView, setActiveView] = useState<"DASHBOARD" | TrackType>(
    "DASHBOARD"
  );
  const [enrollments, setEnrollments] = useState<EnrollmentResponse[]>([]);
  const [latestTurn, setLatestTurn] = useState<SocraticTurnResponse | null>(
    null
  );
  const [drawerOpen, setDrawerOpen] = useState<boolean>(false);

  useEffect(() => {
    const savedToken = localStorage.getItem("socratic_jwt");
    if (savedToken) {
      setAuthToken(savedToken);
      apiClient
        .get<UserResponse>("/api/auth/me")
        .then((res) => setUser(res.data))
        .catch(() => {
          localStorage.removeItem("socratic_jwt");
          setAuthToken(null);
        });
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    apiClient
      .get<EnrollmentResponse[]>("/api/subjects/enrollments")
      .then((res) => setEnrollments(res.data))
      .catch(() => setEnrollments([]));
  }, [user]);

  const handleAuthenticated = (authedUser: UserResponse, token: string) => {
    localStorage.setItem("socratic_jwt", token);
    setUser(authedUser);
  };

  const handleLogout = () => {
    localStorage.removeItem("socratic_jwt");
    setAuthToken(null);
    setUser(null);
    setLatestTurn(null);
    setActiveView("DASHBOARD");
  };

  if (!user) {
    return <AuthModal onAuthenticated={handleAuthenticated} />;
  }

  return (
    <div className="min-h-screen flex flex-col app-shell text-stone-800">
      <header className="h-14 shrink-0 border-b border-green-900/10 bg-white/55 backdrop-blur-md px-4 sm:px-6 flex items-center justify-between">
        <div className="flex items-center gap-4 sm:gap-6 min-w-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="p-2 rounded-xl bg-green-500/15 border border-green-600/25 text-green-700">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div className="min-w-0">
              <span className="text-sm font-semibold text-stone-900 tracking-tight">
                Socratic Tutor
              </span>
              <span className="hidden sm:inline text-[10px] text-stone-500 ml-2">
                Chat · Verify · Guide
              </span>
            </div>
          </div>

          <nav className="hidden md:flex items-center gap-1">
            {(
              [
                {
                  id: "DASHBOARD" as const,
                  label: "Home",
                  icon: <LayoutDashboard className="w-3.5 h-3.5" />,
                },
                {
                  id: "MATH" as const,
                  label: "Math",
                  icon: <Calculator className="w-3.5 h-3.5" />,
                },
                {
                  id: "CODE" as const,
                  label: "Code",
                  icon: <Code2 className="w-3.5 h-3.5" />,
                },
                {
                  id: "RAG" as const,
                  label: "Textbook",
                  icon: <BookOpen className="w-3.5 h-3.5" />,
                },
              ] as const
            ).map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveView(item.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition ${
                  activeView === item.id
                    ? "bg-green-600 text-white shadow-sm"
                    : "text-stone-500 hover:text-stone-800 hover:bg-orange-500/10"
                }`}
              >
                {item.icon} {item.label}
              </button>
            ))}
          </nav>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          {activeView !== "DASHBOARD" && (
            <button
              type="button"
              onClick={() => setDrawerOpen((prev) => !prev)}
              className="px-2.5 py-1.5 rounded-lg bg-orange-500/10 hover:bg-orange-500/20 text-xs font-medium text-orange-700 flex items-center gap-1.5 transition"
            >
              <Activity className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">
                {drawerOpen ? "Hide audit" : "Audit"}
              </span>
            </button>
          )}
          <span className="text-xs text-stone-500 hidden sm:inline truncate max-w-[140px]">
            {user.full_name}
          </span>
          <button
            type="button"
            onClick={handleLogout}
            className="p-2 rounded-lg text-stone-500 hover:text-rose-600 hover:bg-rose-500/10 transition"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </header>

      <main className="flex-1 flex overflow-hidden min-h-0">
        <div className="flex-1 flex flex-col overflow-hidden min-h-0">
          {activeView === "DASHBOARD" && (
            <SubjectDashboard
              enrollments={enrollments}
              onEnrolled={(newEnrollment) =>
                setEnrollments((prev) => [...prev, newEnrollment])
              }
              onSelectTrack={(track) => setActiveView(track)}
            />
          )}
          {activeView === "MATH" && (
            <MathWorkspace onTurnCompleted={(turn) => setLatestTurn(turn)} />
          )}
          {activeView === "CODE" && (
            <CodeWorkspace onTurnCompleted={(turn) => setLatestTurn(turn)} />
          )}
          {activeView === "RAG" && (
            <RagWorkspace onTurnCompleted={(turn) => setLatestTurn(turn)} />
          )}
        </div>

        {activeView !== "DASHBOARD" && (
          <NeuroSymbolicAuditDrawer
            isOpen={drawerOpen}
            onToggle={() => setDrawerOpen((prev) => !prev)}
            latestTurn={latestTurn}
          />
        )}
      </main>
    </div>
  );
};

export default App;
