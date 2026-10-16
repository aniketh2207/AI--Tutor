/**
 * Strict TypeScript API Contracts synced 1:1 with `backend/app/schemas/`
 * (`auth.py`, `socratic.py`, `rag.py`).
 */

import axios from "axios";

export type TrackType = "MATH" | "CODE" | "RAG";

export interface UserRegisterRequest {
  email: string;
  password: string;
  full_name: string;
}

export interface UserLoginRequest {
  email: string;
  password: string;
}

export interface GoogleAuthRequest {
  id_token: string;
}

export interface PublicAuthConfig {
  google_client_id: string;
  google_sign_in_enabled: boolean;
}

export interface UserResponse {
  id: number;
  email: string;
  full_name: string;
  auth_provider: string;
  created_at: string;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user: UserResponse;
}

export interface SubjectEnrollRequest {
  track: TrackType;
}

export interface EnrollmentResponse {
  id: number;
  user_id: number;
  track: TrackType;
  enrolled_at: string;
}

export interface SymbolicRulesPayload {
  variables?: string[];
  target_expr?: string;
  allowed_intermediate_exprs?: string[];
  function_name?: string;
  required_ast_nodes?: string[];
  forbidden_ast_nodes?: string[];
  forbidden_calls?: string[];
  test_cases?: Array<{ input: unknown[]; expected: unknown }>;
  target_concept?: string;
  fallback_question?: string;
}

export interface ProblemItemResponse {
  id: number;
  slug: string;
  track: TrackType;
  title: string;
  prompt: string;
  difficulty: string;
  symbolic_rules_json: SymbolicRulesPayload;
}

export interface NeuralSocraticDraft {
  student_intent_summary: string;
  student_symbolic_claim: string;
  is_final_goal_reached_claim: boolean;
  cited_chunk_id?: number | null;
  verbatim_quote?: string | null;
  socratic_question: string;
}

export interface SymbolicVerdict {
  iteration: number;
  passed: boolean;
  student_step_correct: boolean;
  answer_leaked_in_hint: boolean;
  rejection_reason?: string | null;
  symbolic_rule_checked: string;
  model_used: string;
  latency_ms: number;
}

export interface SocraticTurnRequest {
  session_id?: string | null;
  track: TrackType;
  problem_id?: number | null;
  chapter_id?: number | null;
  student_input: string;
  /** True when the student asks freely (default). False for optional practice problems. */
  chat_mode?: boolean;
}

export interface SocraticTurnResponse {
  session_id: string;
  track: TrackType;
  socratic_reply: string;
  problem_solved: boolean;
  iterations_taken: number;
  circuit_breaker_triggered: boolean;
  audit_trail: SymbolicVerdict[];
}

export interface TurnHistoryItem {
  turn_index: number;
  student_input: string;
  socratic_reply: string;
  problem_solved: boolean;
  iterations_taken: number;
  circuit_breaker_triggered: boolean;
  audit_trail: SymbolicVerdict[];
  created_at: string;
}

export interface SessionHistoryResponse {
  session_id: string;
  track: TrackType;
  is_solved: boolean;
  turns: TurnHistoryItem[];
}

export interface DocumentChunkSchema {
  id: number;
  chapter_id: number;
  chunk_index: number;
  page_number: number;
  content: string;
  similarity?: number | null;
}

export interface TextbookChapterResponse {
  id: number;
  title: string;
  filename: string;
  page_count: number;
  target_concept?: string | null;
  chunk_count: number;
  created_at: string;
}

export interface RagUploadResponse {
  chapter: TextbookChapterResponse;
  chunks_created: number;
  embedding_model: string;
  embedding_dimensions: number;
  preview_chunks: DocumentChunkSchema[];
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

export function setAuthToken(token: string | null): void {
  if (token) {
    apiClient.defaults.headers.common["Authorization"] = `Bearer ${token}`;
  } else {
    delete apiClient.defaults.headers.common["Authorization"];
  }
}
