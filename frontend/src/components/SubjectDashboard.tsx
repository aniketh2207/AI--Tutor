import React, { useState } from "react";
import {
  Calculator,
  Code2,
  BookOpen,
  CheckCircle2,
  ArrowRight,
  MessageCircle,
} from "lucide-react";
import { apiClient, EnrollmentResponse, TrackType } from "../types/api";

interface SubjectDashboardProps {
  enrollments: EnrollmentResponse[];
  onEnrolled: (enrollment: EnrollmentResponse) => void;
  onSelectTrack: (track: TrackType) => void;
}

const TRACK_CARDS = [
  {
    track: "MATH" as const,
    title: "Math",
    subtitle: "Ask about calculus, algebra, or any homework step",
    engineBadge: "SymPy-verified hints",
    description:
      "Start a chat with your math tutor. Bring your own question — optional practice problems are available if you want them.",
    icon: <Calculator className="w-6 h-6 text-green-600" />,
    glow: "hover:border-green-500/50",
  },
  {
    track: "CODE" as const,
    title: "Coding",
    subtitle: "Python, loops, and DSA — talk it through",
    engineBadge: "AST + sandbox checks",
    description:
      "Chat about coding concepts or paste a function for structural feedback. The tutor guides; it won't dump full solutions.",
    icon: <Code2 className="w-6 h-6 text-green-700" />,
    glow: "hover:border-lime-500/50",
  },
  {
    track: "RAG" as const,
    title: "Custom textbook",
    subtitle: "Upload a PDF and ask grounded questions",
    engineBadge: "Verbatim citation guard",
    description:
      "Upload a chapter, then chat about what's in those pages. Answers stay grounded in your material.",
    icon: <BookOpen className="w-6 h-6 text-orange-600" />,
    glow: "hover:border-orange-500/50",
  },
];

export const SubjectDashboard: React.FC<SubjectDashboardProps> = ({
  enrollments,
  onEnrolled,
  onSelectTrack,
}) => {
  const [busyTrack, setBusyTrack] = useState<TrackType | null>(null);

  const isEnrolled = (track: TrackType) =>
    enrollments.some((e) => e.track === track);

  const handleTrackAction = async (track: TrackType) => {
    if (isEnrolled(track)) {
      onSelectTrack(track);
      return;
    }
    setBusyTrack(track);
    try {
      const resp = await apiClient.post<EnrollmentResponse>(
        "/api/subjects/enroll",
        { track }
      );
      onEnrolled(resp.data);
      onSelectTrack(track);
    } finally {
      setBusyTrack(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-5xl mx-auto py-10 px-6">
        <div className="mb-10 animate-fade-up">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-800 border border-green-600/20 mb-3">
            <MessageCircle className="w-3.5 h-3.5" /> Conversational Socratic
            tutoring
          </span>
          <h2 className="font-display text-3xl sm:text-4xl text-stone-900 tracking-tight">
            What do you want to learn?
          </h2>
          <p className="text-sm text-stone-600 mt-2 max-w-xl leading-relaxed">
            Pick a track and start chatting. You ask the questions — the tutor
            guides you with verified Socratic hints.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {TRACK_CARDS.map((card, idx) => {
            const enrolled = isEnrolled(card.track);
            const loading = busyTrack === card.track;
            return (
              <div
                key={card.track}
                className={`flex flex-col justify-between rounded-2xl border border-green-900/10 bg-white/70 backdrop-blur p-6 shadow-sm transition duration-300 ${card.glow} animate-fade-up`}
                style={{ animationDelay: `${idx * 80}ms` }}
              >
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <div className="p-3 rounded-2xl bg-green-50 border border-green-900/10">
                      {card.icon}
                    </div>
                    {enrolled ? (
                      <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-800 border border-green-600/25">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Ready
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full text-xs font-medium bg-orange-500/10 text-orange-700">
                        Open chat
                      </span>
                    )}
                  </div>
                  <h3 className="text-lg font-semibold text-stone-900">
                    {card.title}
                  </h3>
                  <p className="text-xs text-orange-700/90 mt-1">{card.subtitle}</p>
                  <div className="mt-3 inline-block px-2.5 py-1 rounded-md bg-green-50 border border-green-900/10 text-[11px] font-mono text-stone-600">
                    {card.engineBadge}
                  </div>
                  <p className="mt-4 text-xs leading-relaxed text-stone-600">
                    {card.description}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => void handleTrackAction(card.track)}
                  className="mt-6 w-full py-2.5 px-4 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition bg-green-600 hover:bg-green-500 text-white disabled:opacity-50"
                >
                  {loading
                    ? "Opening…"
                    : enrolled
                    ? "Continue chat"
                    : "Start chatting"}
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
