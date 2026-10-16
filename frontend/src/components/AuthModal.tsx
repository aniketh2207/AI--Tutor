import React, { useState } from "react";
import { ShieldCheck, Lock, Mail, User as UserIcon } from "lucide-react";
import {
  apiClient,
  AuthTokenResponse,
  setAuthToken,
  UserResponse,
} from "../types/api";
import { GoogleSignInButton } from "./GoogleSignInButton";

interface AuthModalProps {
  onAuthenticated: (user: UserResponse, token: string) => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ onAuthenticated }) => {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const response =
        mode === "register"
          ? await apiClient.post<AuthTokenResponse>("/api/auth/register", {
              email,
              password,
              full_name: fullName,
            })
          : await apiClient.post<AuthTokenResponse>("/api/auth/login", {
              email,
              password,
            });
      const { access_token, user } = response.data;
      setAuthToken(access_token);
      onAuthenticated(user, access_token);
    } catch (err: unknown) {
      if (
        err &&
        typeof err === "object" &&
        "response" in err &&
        err.response &&
        typeof err.response === "object" &&
        "data" in err.response &&
        err.response.data &&
        typeof err.response.data === "object" &&
        "detail" in err.response.data
      ) {
        setError(String(err.response.data.detail));
      } else {
        setError("Authentication failed. Please check your credentials.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center app-shell px-4">
      <div className="w-full max-w-md bg-white/80 border border-green-900/10 rounded-2xl shadow-xl p-8 backdrop-blur animate-fade-up">
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2.5 rounded-xl bg-green-500/15 border border-green-600/25 text-green-700">
            <ShieldCheck className="w-7 h-7" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-semibold text-stone-900 tracking-tight">
              Socratic Tutor
            </h1>
            <p className="text-xs text-stone-500">
              Chat with a verified study tutor — ask your own questions
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-1 p-1 bg-green-50/80 rounded-lg mb-5 border border-green-900/10">
          {(["login", "register"] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => {
                setMode(tab);
                setError(null);
              }}
              className={`py-2 text-xs font-semibold rounded-md capitalize transition ${
                mode === tab
                  ? "bg-green-600 text-white shadow"
                  : "text-stone-500 hover:text-stone-800"
              }`}
            >
              {tab === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg bg-rose-50 border border-rose-200 text-xs text-rose-700">
            {error}
          </div>
        )}

        <GoogleSignInButton
          onAuthenticated={onAuthenticated}
          onError={setError}
          disabled={loading}
        />

        <div className="flex items-center gap-3 my-5">
          <div className="h-px flex-1 bg-stone-200" />
          <span className="text-[11px] uppercase tracking-wide text-stone-400">
            or use email
          </span>
          <div className="h-px flex-1 bg-stone-200" />
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "register" && (
            <div>
              <label className="block text-xs font-medium text-stone-600 mb-1">
                Full Name
              </label>
              <div className="relative">
                <UserIcon className="w-4 h-4 text-stone-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  required
                  minLength={2}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Ada Lovelace"
                  className="w-full pl-9 pr-3 py-2 bg-white border border-stone-200 rounded-lg text-sm text-stone-900 focus:outline-none focus:border-green-500"
                />
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-stone-600 mb-1">
              Email Address
            </label>
            <div className="relative">
              <Mail className="w-4 h-4 text-stone-400 absolute left-3 top-2.5" />
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="student@university.edu"
                className="w-full pl-9 pr-3 py-2 bg-white border border-stone-200 rounded-lg text-sm text-stone-900 focus:outline-none focus:border-green-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-stone-600 mb-1">
              Password (min 8 chars)
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-stone-400 absolute left-3 top-2.5" />
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-9 pr-3 py-2 bg-white border border-stone-200 rounded-lg text-sm text-stone-900 focus:outline-none focus:border-green-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 bg-green-600 hover:bg-green-500 disabled:opacity-50 text-white text-sm font-semibold rounded-lg transition"
          >
            {loading
              ? "Authenticating..."
              : mode === "register"
              ? "Create account & start chatting"
              : "Sign in with email"}
          </button>
        </form>
      </div>
    </div>
  );
};
