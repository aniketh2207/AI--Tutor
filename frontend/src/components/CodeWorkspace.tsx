import React from "react";
import { SocraticTurnResponse } from "../types/api";
import { TutorChat } from "./TutorChat";

interface CodeWorkspaceProps {
  onTurnCompleted: (turn: SocraticTurnResponse) => void;
}

/** Track 2 entrypoint — conversational coding tutoring via TutorChat. */
export const CodeWorkspace: React.FC<CodeWorkspaceProps> = ({
  onTurnCompleted,
}) => <TutorChat track="CODE" onTurnCompleted={onTurnCompleted} />;
