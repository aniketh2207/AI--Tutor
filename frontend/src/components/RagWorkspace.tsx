import React from "react";
import { SocraticTurnResponse } from "../types/api";
import { TutorChat } from "./TutorChat";

interface RagWorkspaceProps {
  onTurnCompleted: (turn: SocraticTurnResponse) => void;
}

/** Track 3 entrypoint — textbook-grounded conversational tutoring via TutorChat. */
export const RagWorkspace: React.FC<RagWorkspaceProps> = ({
  onTurnCompleted,
}) => <TutorChat track="RAG" onTurnCompleted={onTurnCompleted} />;
