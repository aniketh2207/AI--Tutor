import React, { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import {
  apiClient,
  ProblemItemResponse,
  RagUploadResponse,
  SocraticTurnResponse,
  TextbookChapterResponse,
  TrackType,
} from "../types/api";
import { ChatComposer } from "./chat/ChatComposer";
import { ChatThread } from "./chat/ChatThread";
import { ChatToolbar } from "./chat/ChatToolbar";
import { ChatMessage, TRACK_META, newMessageId } from "./chat/trackMeta";

interface TutorChatProps {
  track: TrackType;
  onTurnCompleted: (turn: SocraticTurnResponse) => void;
}

export const TutorChat: React.FC<TutorChatProps> = ({
  track,
  onTurnCompleted,
}) => {
  const meta = TRACK_META[track];
  const [messages, setMessages] = useState<ChatMessage[]>([
    { id: newMessageId(), role: "tutor", content: meta.welcome },
  ]);
  const [draft, setDraft] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<ProblemItemResponse[]>([]);
  const [activeProblemId, setActiveProblemId] = useState<number | null>(null);
  const [chapters, setChapters] = useState<TextbookChapterResponse[]>([]);
  const [chapterId, setChapterId] = useState<number | null>(null);
  const [showCodePad, setShowCodePad] = useState(false);
  const [codePad, setCodePad] = useState(
    "def sum_elements(nums):\n    # your approach here\n    pass\n"
  );
  const [uploading, setUploading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null!);
  const fileRef = useRef<HTMLInputElement>(null!);

  useEffect(() => {
    setMessages([{ id: newMessageId(), role: "tutor", content: meta.welcome }]);
    setSessionId(null);
    setActiveProblemId(null);
    setDraft("");
    setError(null);
  }, [track, meta.welcome]);

  useEffect(() => {
    if (track === "RAG") {
      apiClient
        .get<TextbookChapterResponse[]>("/api/rag/chapters")
        .then((res) => {
          setChapters(res.data);
          if (res.data.length > 0) setChapterId(res.data[0].id);
        })
        .catch(() => setChapters([]));
      return;
    }
    apiClient
      .get<ProblemItemResponse[]>(`/api/subjects/problems?track=${track}`)
      .then((res) => setProblems(res.data))
      .catch(() => setProblems([]));
  }, [track]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const activeProblem = useMemo(
    () => problems.find((p) => p.id === activeProblemId) || null,
    [problems, activeProblemId]
  );

  const sendMessage = async (
    text: string,
    opts?: { practiceId?: number | null }
  ) => {
    const content = text.trim();
    if (!content || loading) return;
    const practiceId =
      opts && "practiceId" in opts ? opts.practiceId ?? null : activeProblemId;

    setError(null);
    setMessages((prev) => [
      ...prev,
      { id: newMessageId(), role: "student", content },
    ]);
    setDraft("");
    setLoading(true);
    try {
      const body: Record<string, unknown> = {
        track,
        student_input: content,
        session_id: sessionId,
        chat_mode: practiceId == null,
      };
      if (practiceId != null) body.problem_id = practiceId;
      if (track === "RAG" && chapterId != null) body.chapter_id = chapterId;

      const resp = await apiClient.post<SocraticTurnResponse>(
        "/api/tutor/turn",
        body
      );
      setSessionId(resp.data.session_id);
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "tutor",
          content: resp.data.socratic_reply,
          solved: resp.data.problem_solved,
        },
      ]);
      onTurnCompleted(resp.data);
    } catch {
      setError(
        track === "RAG" && !chapterId
          ? "Upload a textbook PDF first, then ask your question."
          : "Couldn't reach the tutor. Check that the backend is running."
      );
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "system",
          content: "Message failed to send. Please try again.",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleUpload = async (file: File | null) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("title", file.name.replace(/\.pdf$/i, ""));
      const resp = await apiClient.post<RagUploadResponse>("/api/rag/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setChapters((prev) => [resp.data.chapter, ...prev]);
      setChapterId(resp.data.chapter.id);
      setMessages((prev) => [
        ...prev,
        {
          id: newMessageId(),
          role: "system",
          content: `Uploaded “${resp.data.chapter.title}” (${resp.data.chunks_created} chunks). Ask me anything from these pages.`,
        },
      ]);
    } catch {
      setError("PDF upload failed. Use a PDF ≤15 pages and ≤5MB.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-transparent">
      <div
        className={`mx-4 mt-4 mb-2 rounded-2xl border border-green-900/10 bg-gradient-to-r ${meta.accent} px-4 py-3 flex items-center justify-between gap-3`}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="p-2 rounded-xl bg-white/70 text-green-700 shrink-0">
            {meta.icon}
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-stone-900 truncate">
              {meta.title}
            </h2>
            <p className="text-[11px] text-stone-600 truncate">
              Chat freely — ask your own question
              {activeProblem ? ` · Practice: ${activeProblem.title}` : ""}
              {track === "RAG" && chapterId ? ` · Chapter #${chapterId}` : ""}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            setMessages([
              { id: newMessageId(), role: "tutor", content: meta.welcome },
            ]);
            setSessionId(null);
            setActiveProblemId(null);
            setError(null);
          }}
          className="text-xs text-stone-600 hover:text-stone-900 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg hover:bg-white/60 transition"
        >
          <RefreshCw className="w-3.5 h-3.5" /> New chat
        </button>
      </div>

      <ChatToolbar
        track={track}
        problems={problems}
        activeProblemId={activeProblemId}
        loading={loading}
        onPractice={(problem) => {
          setActiveProblemId(problem.id);
          void sendMessage(
            `I'd like help with this practice problem:\n\n${problem.prompt}\n\nCan you guide me step by step without giving away the final answer?`,
            { practiceId: problem.id }
          );
        }}
        chapters={chapters}
        chapterId={chapterId}
        setChapterId={setChapterId}
        uploading={uploading}
        onPickFile={() => fileRef.current?.click()}
        fileRef={fileRef}
        onFileChange={(file) => void handleUpload(file)}
      />

      <ChatThread messages={messages} loading={loading} bottomRef={bottomRef} />

      {error && (
        <div className="mx-4 mb-2 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2">
          {error}
        </div>
      )}

      <ChatComposer
        track={track}
        draft={draft}
        setDraft={setDraft}
        loading={loading}
        placeholder={meta.placeholder}
        showCodePad={showCodePad}
        setShowCodePad={setShowCodePad}
        codePad={codePad}
        setCodePad={setCodePad}
        onSend={(text) => void sendMessage(text)}
        onSendCode={() =>
          void sendMessage(
            `Here's my current code attempt. Can you review my approach and ask a guiding question?\n\n\`\`\`python\n${codePad}\n\`\`\``
          )
        }
      />
    </div>
  );
};
