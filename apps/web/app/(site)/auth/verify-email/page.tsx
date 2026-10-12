"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { authApi } from "@/features/auth/api";
import { setTokens } from "@/lib/auth/storage";
import { getApiErrorMessage } from "@/lib/http/errors";

/** Landing page of the confirmation link sent after sign-up. */
function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");
  const started = useRef(false);

  useEffect(() => {
    // A link works once: do not send it twice (React runs effects twice in development).
    if (started.current) return;
    started.current = true;
    const token = searchParams.get("token");
    if (!token) {
      setStatus("error");
      setMessage("This confirmation link is incomplete.");
      return;
    }
    authApi
      .verifyEmail(token)
      .then((res) => {
        setTokens(res.access_token, res.refresh_token, res.user);
        setStatus("ok");
        window.location.href = "/dashboard";
      })
      .catch((err) => {
        setStatus("error");
        setMessage(getApiErrorMessage(err, "This confirmation link is not valid or has expired."));
      });
  }, [searchParams]);

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl">Confirm your email</CardTitle>
          <CardDescription>
            {status === "working" && "Confirming your email address…"}
            {status === "ok" && "Your email address is confirmed. Taking you to your dashboard…"}
            {status === "error" && "We could not confirm your email address."}
          </CardDescription>
        </CardHeader>
        {status === "error" && (
          <CardContent className="space-y-3 text-sm">
            <p className="text-destructive" data-testid="verify-email-error">{message}</p>
            <p className="text-muted-foreground">
              Links work once and for a limited time.{" "}
              <Link href="/auth" className="text-primary hover:underline">
                Log in
              </Link>{" "}
              to request a new one.
            </p>
          </CardContent>
        )}
      </Card>
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
          <p className="text-muted-foreground">Confirming your email address…</p>
        </main>
      }
    >
      <VerifyEmailContent />
    </Suspense>
  );
}
