"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { setTokens } from "@/lib/auth/storage";
import { authApi } from "@/features/auth/api";
import { notify } from "@/lib/notify";

function AuthCallbackContent() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");

  useEffect(() => {
    const code = searchParams.get("code");
    if (!code) {
      setStatus("error");
      notify.error("Missing authorization code");
      return;
    }
    authApi
      .loginWithGoogleCode(code)
      .then((res) => {
        setTokens(res.access_token, res.refresh_token, res.user);
        setStatus("ok");
        window.location.href = "/dashboard";
      })
      .catch(() => {
        setStatus("error");
        notify.error("Google sign-in failed");
      });
  }, [searchParams]);

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
      <div className="text-center">
        {status === "loading" && (
          <p className="text-muted-foreground">Signing you in…</p>
        )}
        {status === "ok" && (
          <p className="text-muted-foreground">Redirecting to dashboard…</p>
        )}
        {status === "error" && (
          <p className="text-destructive">
            Sign-in failed.{" "}
            <a href="/auth" className="underline">
              Back to Log in
            </a>
          </p>
        )}
      </div>
    </main>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
          <div className="text-center">
            <p className="text-muted-foreground">Signing you in…</p>
          </div>
        </main>
      }
    >
      <AuthCallbackContent />
    </Suspense>
  );
}
