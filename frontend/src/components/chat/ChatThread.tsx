import React from "react";
import { Loader2, Sparkles } from "lucide-react";
import { ChatMessage } from "./trackMeta";

interface ChatThreadProps {
  messages: ChatMessage[];
  loading: boolean;
  bottomRef: React.RefObject<HTMLDivElement>;
}

export const ChatThread: React.FC<ChatThreadProps> = ({
  messages,
  loading,
  bottomRef,
}) => (
  <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
    {messages.map((msg) => (
      <div
        key={msg.id}
        className={`flex animate-fade-up ${
          msg.role === "student" ? "justify-end" : "justify-start"
        }`}
      >
        <div
          className={`max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
            msg.role === "student"
              ? "bg-green-600 text-white rounded-br-md"
              : msg.role === "system"
              ? "bg-orange-50 border border-orange-200 text-stone-600 text-xs"
              : "bg-white/85 border border-green-900/10 text-stone-800 rounded-bl-md"
          }`}
        >
          {msg.role === "tutor" && (
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-green-700 mb-1.5 font-semibold">
              <Sparkles className="w-3 h-3" /> Tutor
              {msg.solved && (
                <span className="ml-1 text-orange-600">· Goal reached</span>
              )}
            </div>
          )}
          <p className="whitespace-pre-wrap">{msg.content}</p>
        </div>
      </div>
    ))}

    {loading && (
      <div className="flex justify-start animate-fade-up">
        <div className="rounded-2xl rounded-bl-md px-4 py-3 bg-white/85 border border-green-900/10 text-stone-600 text-xs flex items-center gap-2">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-green-600" />
          Tutor is thinking…
        </div>
      </div>
    )}
    <div ref={bottomRef} />
  </div>
);
