import React from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  ChevronLeft,
  Cpu,
  ShieldAlert,
  Sparkles,
  Clock,
} from "lucide-react";
import { SocraticTurnResponse, SymbolicVerdict } from "../types/api";

interface NeuroSymbolicAuditDrawerProps {
  isOpen: boolean;
  onToggle: () => void;
  latestTurn: SocraticTurnResponse | null;
}

export const NeuroSymbolicAuditDrawer: React.FC<
  NeuroSymbolicAuditDrawerProps
> = ({ isOpen, onToggle, latestTurn }) => {
  if (!isOpen) {
    return (
      <button
        type="button"
        onClick={onToggle}
        title="Open Live Neuro-Symbolic Audit Drawer"
        className="fixed right-0 top-24 z-30 bg-white border border-r-0 border-green-900/15 text-green-700 p-2.5 rounded-l-xl shadow-lg hover:bg-green-50 transition flex items-center gap-1.5 text-xs font-semibold"
      >
        <ChevronLeft className="w-4 h-4" />
        <Activity className="w-4 h-4" />
        <span className="hidden sm:inline">Audit Drawer</span>
      </button>
    );
  }

  const verdicts: SymbolicVerdict[] = latestTurn?.audit_trail || [];

  return (
    <aside className="w-full lg:w-96 shrink-0 bg-white/80 border-l border-green-900/10 flex flex-col h-full overflow-y-auto backdrop-blur">
      <div className="p-4 border-b border-green-900/10 flex items-center justify-between bg-orange-50/50">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-orange-600" />
          <div>
            <h3 className="text-xs font-bold uppercase tracking-wider text-stone-900">
              Neuro-Symbolic Audit Drawer
            </h3>
            <p className="text-[11px] text-stone-500">
              Live 4-Step LangGraph Verification Telemetry
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={onToggle}
          className="p-1.5 rounded-lg text-stone-400 hover:text-stone-800 hover:bg-green-50"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4 border-b border-green-900/10 bg-green-50/40">
        <div className="text-[11px] font-semibold text-stone-500 mb-2">
          4-STEP SOCRATIC CYCLE TOPOLOGY
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="p-2 rounded-lg bg-white border border-green-900/10">
            <span className="text-green-700 font-bold">1. Intuitive Leap</span>
            <p className="text-stone-500">Gemini JSON Draft</p>
          </div>
          <div className="p-2 rounded-lg bg-white border border-green-900/10">
            <span className="text-green-800 font-bold">2. Interrogation</span>
            <p className="text-stone-500">SymPy / AST / RAG Guard</p>
          </div>
          <div className="p-2 rounded-lg bg-white border border-green-900/10">
            <span className="text-orange-600 font-bold">3. Alignment Loop</span>
            <p className="text-stone-500">Critique Retry (Max 3)</p>
          </div>
          <div className="p-2 rounded-lg bg-white border border-green-900/10">
            <span className="text-orange-700 font-bold">4. Certified Output</span>
            <p className="text-stone-500">0% Leak Release</p>
          </div>
        </div>
      </div>

      <div className="p-4 space-y-4 flex-1">
        {!latestTurn ? (
          <div className="text-center py-12 px-4 border border-dashed border-green-900/15 rounded-xl">
            <Sparkles className="w-7 h-7 text-orange-400 mx-auto mb-2" />
            <p className="text-xs font-medium text-stone-700">
              No Socratic Turn Executed Yet
            </p>
            <p className="text-[11px] text-stone-500 mt-1">
              Chat with the tutor to inspect every neural draft and symbolic
              verdict in real time.
            </p>
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between p-3 rounded-xl bg-white border border-green-900/10 text-xs">
              <div>
                <span className="text-stone-500">Iterations Taken: </span>
                <span className="font-bold text-stone-900">
                  {latestTurn.iterations_taken} / 3
                </span>
              </div>
              {latestTurn.circuit_breaker_triggered ? (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-orange-500/10 text-orange-700 border border-orange-500/30 text-[11px]">
                  <AlertTriangle className="w-3 h-3" /> Circuit Breaker
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-green-500/10 text-green-800 border border-green-600/30 text-[11px]">
                  <CheckCircle2 className="w-3 h-3" /> Certified
                </span>
              )}
            </div>

            {verdicts.map((v) => (
              <div
                key={v.iteration}
                className={`p-3.5 rounded-xl border text-xs space-y-2 ${
                  v.passed
                    ? "bg-green-50 border-green-200"
                    : "bg-rose-50 border-rose-200"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-stone-900 flex items-center gap-1.5">
                    {v.passed ? (
                      <CheckCircle2 className="w-4 h-4 text-green-600" />
                    ) : (
                      <ShieldAlert className="w-4 h-4 text-rose-500" />
                    )}
                    Iteration #{v.iteration}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded font-semibold text-[10px] ${
                      v.passed
                        ? "bg-green-500/15 text-green-800"
                        : "bg-rose-500/15 text-rose-700"
                    }`}
                  >
                    {v.passed ? "PASSED" : "REJECTED -> STEP 3 RETRY"}
                  </span>
                </div>

                <div className="flex items-center justify-between text-[11px] text-stone-600 font-mono">
                  <span className="flex items-center gap-1">
                    <Cpu className="w-3 h-3 text-green-600" />
                    {v.model_used}
                  </span>
                  <span className="flex items-center gap-1 text-stone-500">
                    <Clock className="w-3 h-3" />
                    {v.latency_ms} ms
                  </span>
                </div>

                <div className="text-[11px] text-stone-700 bg-white/80 p-2 rounded border border-green-900/10 font-mono">
                  Rule: {v.symbolic_rule_checked}
                </div>

                <div className="flex gap-2 text-[11px]">
                  <span className="px-2 py-0.5 rounded bg-white border border-green-900/10 text-stone-600">
                    Step Correct: {v.student_step_correct ? "Yes" : "No"}
                  </span>
                  <span
                    className={`px-2 py-0.5 rounded border ${
                      v.answer_leaked_in_hint
                        ? "bg-rose-100 border-rose-300 text-rose-700 font-semibold"
                        : "bg-white border-green-900/10 text-stone-600"
                    }`}
                  >
                    Answer Leaked: {v.answer_leaked_in_hint ? "YES" : "No"}
                  </span>
                </div>

                {v.rejection_reason && (
                  <div className="p-2 rounded bg-rose-100 border border-rose-200 text-[11px] text-rose-700 font-mono">
                    {v.rejection_reason}
                  </div>
                )}
              </div>
            ))}
          </>
        )}
      </div>
    </aside>
  );
};
