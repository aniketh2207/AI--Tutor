import React, { useEffect, useRef, useState } from "react";
import {
  apiClient,
  AuthTokenResponse,
  PublicAuthConfig,
  setAuthToken,
  UserResponse,
} from "../types/api";

interface GoogleSignInButtonProps {
  onAuthenticated: (user: UserResponse, token: string) => void;
  onError: (message: string) => void;
  disabled?: boolean;
}

async function resolveGoogleClientId(): Promise<string | null> {
  const fromEnv = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim();
  if (fromEnv) return fromEnv;
  try {
    const resp = await apiClient.get<PublicAuthConfig>("/api/auth/public-config");
    if (!resp.data.google_sign_in_enabled) return null;
    const id = resp.data.google_client_id?.trim();
    return id || null;
  } catch {
    return null;
  }
}

function waitForGoogleSdk(timeoutMs = 8000): Promise<boolean> {
  return new Promise((resolve) => {
    if (window.google?.accounts?.id) {
      resolve(true);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      if (window.google?.accounts?.id) {
        window.clearInterval(timer);
        resolve(true);
      } else if (Date.now() - started > timeoutMs) {
        window.clearInterval(timer);
        resolve(false);
      }
    }, 100);
  });
}

export const GoogleSignInButton: React.FC<GoogleSignInButtonProps> = ({
  onAuthenticated,
  onError,
  disabled = false,
}) => {
  const buttonHostRef = useRef<HTMLDivElement>(null);
  const onAuthenticatedRef = useRef(onAuthenticated);
  const onErrorRef = useRef(onError);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(
    null
  );

  onAuthenticatedRef.current = onAuthenticated;
  onErrorRef.current = onError;

  useEffect(() => {
    let cancelled = false;

    const boot = async () => {
      const clientId = await resolveGoogleClientId();
      if (cancelled) return;
      if (!clientId) {
        setUnavailableReason(
          "Set GOOGLE_CLIENT_ID in backend .env (OAuth Web client) and add http://localhost:5173 as an Authorized JavaScript origin."
        );
        return;
      }

      const sdkReady = await waitForGoogleSdk();
      if (cancelled) return;
      const host = buttonHostRef.current;
      if (!sdkReady || !host) {
        setUnavailableReason(
          "Google Sign-In script failed to load. Check your network and refresh."
        );
        return;
      }

      host.innerHTML = "";
      window.google!.accounts.id.initialize({
        client_id: clientId,
        callback: async (response) => {
          if (!response.credential) {
            onErrorRef.current(
              "Google did not return a credential. Please try again."
            );
            return;
          }
          setBusy(true);
          try {
            const authResp = await apiClient.post<AuthTokenResponse>(
              "/api/auth/google",
              { id_token: response.credential }
            );
            setAuthToken(authResp.data.access_token);
            onAuthenticatedRef.current(
              authResp.data.user,
              authResp.data.access_token
            );
          } catch (err: unknown) {
            let message = "Google sign-in failed.";
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
              message = String(err.response.data.detail);
            }
            onErrorRef.current(message);
          } finally {
            setBusy(false);
          }
        },
      });

      window.google!.accounts.id.renderButton(host, {
        theme: "outline",
        size: "large",
        text: "continue_with",
        shape: "rectangular",
        width: 320,
      });
      setReady(true);
    };

    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-2">
      <div
        ref={buttonHostRef}
        className={`flex justify-center min-h-[44px] ${
          disabled || busy ? "pointer-events-none opacity-50" : ""
        }`}
        aria-label="Continue with Google"
      />
      {!ready && !unavailableReason && (
        <p className="text-[11px] text-center text-stone-500">
          Loading Google Sign-In…
        </p>
      )}
      {unavailableReason && (
        <p className="text-[11px] text-center text-stone-500 leading-relaxed">
          {unavailableReason}
        </p>
      )}
    </div>
  );
};
