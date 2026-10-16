import React from "react";
import { SocraticTurnResponse } from "../types/api";
import { TutorChat } from "./TutorChat";

interface MathWorkspaceProps {
  onTurnCompleted: (turn: SocraticTurnResponse) => void;
}

/** Track 1 entrypoint — conversational math tutoring via TutorChat. */
export const MathWorkspace: React.FC<MathWorkspaceProps> = ({
  onTurnCompleted,
}) => <TutorChat track="MATH" onTurnCompleted={onTurnCompleted} />;
