import React from "react";
import { Paperclip } from "lucide-react";
import { ProblemItemResponse, TextbookChapterResponse, TrackType } from "../../types/api";

interface ChatToolbarProps {
  track: TrackType;
  problems: ProblemItemResponse[];
  activeProblemId: number | null;
  loading: boolean;
  onPractice: (problem: ProblemItemResponse) => void;
  chapters: TextbookChapterResponse[];
  chapterId: number | null;
  setChapterId: (id: number) => void;
  uploading: boolean;
  onPickFile: () => void;
  fileRef: React.RefObject<HTMLInputElement>;
  onFileChange: (file: File | null) => void;
}

export const ChatToolbar: React.FC<ChatToolbarProps> = ({
  track,
  problems,
  activeProblemId,
  loading,
  onPractice,
  chapters,
  chapterId,
  setChapterId,
  uploading,
  onPickFile,
  fileRef,
  onFileChange,
}) => {
  if (track === "MATH" || track === "CODE") {
    if (problems.length === 0) return null;
    return (
      <div className="px-4 pb-2 flex gap-2 overflow-x-auto">
        <span className="text-[10px] uppercase tracking-wide text-stone-500 self-center shrink-0">
          Optional practice
        </span>
        {problems.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => onPractice(p)}
            disabled={loading}
            className={`shrink-0 text-[11px] px-3 py-1.5 rounded-full border transition ${
              activeProblemId === p.id
                ? "border-green-600/40 bg-green-500/15 text-green-800"
                : "border-green-900/10 bg-white/60 text-stone-600 hover:bg-orange-50"
            }`}
          >
            {p.title}
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="px-4 pb-2 flex flex-wrap items-center gap-2">
      <button
        type="button"
        onClick={onPickFile}
        disabled={uploading}
        className="text-[11px] px-3 py-1.5 rounded-full border border-orange-500/30 bg-orange-500/10 text-orange-800 hover:bg-orange-500/20 flex items-center gap-1.5 transition"
      >
        <Paperclip className="w-3.5 h-3.5" />
        {uploading ? "Uploading…" : "Upload textbook PDF"}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => onFileChange(e.target.files?.[0] || null)}
      />
      {chapters.slice(0, 3).map((ch) => (
        <button
          key={ch.id}
          type="button"
          onClick={() => setChapterId(ch.id)}
          className={`text-[11px] px-3 py-1.5 rounded-full border transition ${
            chapterId === ch.id
              ? "border-orange-500/40 bg-orange-500/15 text-orange-800"
              : "border-green-900/10 bg-white/60 text-stone-600"
          }`}
        >
          {ch.title}
        </button>
      ))}
    </div>
  );
};
