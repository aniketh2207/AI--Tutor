import React from "react";
import { BookOpen, Calculator, Code2 } from "lucide-react";
import { TrackType } from "../../types/api";

export interface ChatMessage {
  id: string;
  role: "student" | "tutor" | "system";
  content: string;
  solved?: boolean;
}

export const TRACK_META: Record<
  TrackType,
  {
    title: string;
    accent: string;
    icon: React.ReactNode;
    welcome: string;
    placeholder: string;
  }
> = {
  MATH: {
    title: "Math Tutor",
    accent: "from-green-400/35 to-orange-300/25",
    icon: <Calculator className="w-4 h-4" />,
    welcome:
      "Hi — I'm your math tutor. Ask me anything (derivatives, algebra, integrals…). Paste a homework problem or just say what you're stuck on.",
    placeholder: "Ask a math question… e.g. How do I differentiate x^3 + 2x?",
  },
  CODE: {
    title: "Coding Tutor",
    accent: "from-green-500/30 to-lime-300/25",
    icon: <Code2 className="w-4 h-4" />,
    welcome:
      "Hi — I'm your coding tutor. Ask about Python, loops, or DSA. You can also paste code below and ask me to review your approach.",
    placeholder: "Ask a coding question… e.g. How do I sum a list with a for loop?",
  },
  RAG: {
    title: "Textbook Tutor",
    accent: "from-orange-400/35 to-amber-300/25",
    icon: <BookOpen className="w-4 h-4" />,
    welcome:
      "Upload a textbook PDF chapter, then ask questions grounded in that material. I'll only answer from your uploaded pages.",
    placeholder: "Ask about something in your uploaded textbook…",
  },
};

export function newMessageId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
