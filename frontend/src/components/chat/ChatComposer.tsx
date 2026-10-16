import React from "react";
import Editor from "@monaco-editor/react";
import { Code2, Send } from "lucide-react";
import { TrackType } from "../../types/api";

interface ChatComposerProps {
  track: TrackType;
  draft: string;
  setDraft: (value: string) => void;
  loading: boolean;
  placeholder: string;
  showCodePad: boolean;
  setShowCodePad: (value: boolean) => void;
  codePad: string;
  setCodePad: (value: string) => void;
  onSend: (text: string) => void;
  onSendCode: () => void;
}

export const ChatComposer: React.FC<ChatComposerProps> = ({
  track,
  draft,
  setDraft,
  loading,
  placeholder,
  showCodePad,
  setShowCodePad,
  codePad,
  setCodePad,
  onSend,
  onSendCode,
}) => (
  <>
    {track === "CODE" && showCodePad && (
      <div className="mx-4 mb-2 rounded-xl border border-green-900/10 overflow-hidden h-44 animate-fade-up bg-white/70">
        <Editor
          height="100%"
          defaultLanguage="python"
          theme="vs-light"
          value={codePad}
          onChange={(v) => setCodePad(v || "")}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            scrollBeyondLastLine: false,
          }}
        />
        <div className="flex justify-end gap-2 p-2 bg-white/90 border-t border-green-900/10">
          <button
            type="button"
            onClick={onSendCode}
            disabled={loading}
            className="text-[11px] px-3 py-1.5 rounded-lg bg-green-600 hover:bg-green-500 text-white"
          >
            Send code to tutor
          </button>
        </div>
      </div>
    )}

    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSend(draft);
      }}
      className="p-4 pt-2 border-t border-green-900/10 bg-white/50 backdrop-blur"
    >
      <div className="flex items-end gap-2 rounded-2xl border border-green-900/15 bg-white/90 px-3 py-2 focus-within:border-green-500/60 transition shadow-sm">
        {track === "CODE" && (
          <button
            type="button"
            onClick={() => setShowCodePad(!showCodePad)}
            className="p-2 rounded-lg text-stone-400 hover:text-green-700 hover:bg-green-50 transition"
            title="Toggle code pad"
          >
            <Code2 className="w-4 h-4" />
          </button>
        )}
        <textarea
          rows={1}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend(draft);
            }
          }}
          placeholder={placeholder}
          className="flex-1 resize-none bg-transparent text-sm text-stone-800 placeholder:text-stone-400 focus:outline-none py-2 max-h-32"
        />
        <button
          type="submit"
          disabled={loading || !draft.trim()}
          className="p-2.5 rounded-xl bg-orange-500 hover:bg-orange-400 disabled:opacity-40 text-white transition"
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
      <p className="mt-1.5 text-[10px] text-stone-500 text-center">
        Enter to send · Shift+Enter for a new line
      </p>
    </form>
  </>
);
