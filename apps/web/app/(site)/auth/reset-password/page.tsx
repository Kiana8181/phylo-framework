"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authApi } from "@/features/auth/api";
import { notify } from "@/lib/notify";

export default function ResetPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) {
      notify.error("Invalid link", "Missing reset token");
    }
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (password !== confirm) {
      notify.error("Passwords do not match");
      return;
    }
    if (password.length < 6) {
      notify.error("Password must be at least 6 characters");
      return;
    }
    setSubmitting(true);
    try {
      await authApi.resetPassword(token, password);
      setDone(true);
      notify.success("Password reset. You can now log in.");
      setTimeout(() => router.replace("/auth"), 1500);
    } catch (err: unknown) {
      const data = (err as { response?: { data?: unknown } })?.response?.data;
      const message =
        (typeof data === "object" && data !== null && "detail" in data)
          ? String((data as { detail: unknown }).detail)
          : err instanceof Error
            ? err.message
            : "Something went wrong";
      notify.error("Reset failed", message);
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardContent className="pt-6">
            <p className="text-sm text-muted-foreground text-center">
              This reset link is invalid or has expired.
            </p>
            <p className="mt-4 text-center">
              <Link href="/auth/forgot-password" className="text-primary hover:underline">
                Request a new link
              </Link>
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  if (done) {
    return (
      <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
        <Card className="w-full max-w-md">
          <CardContent className="pt-6">
            <p className="text-sm text-center text-muted-foreground">
              Password has been reset. Redirecting to log in…
            </p>
            <p className="mt-4 text-center">
              <Link href="/auth" className="text-primary hover:underline">
                Go to Log in
              </Link>
            </p>
          </CardContent>
        </Card>
      </main>
    );
  }

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl">Set new password</CardTitle>
          <CardDescription>
            Enter your new password below.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="password">New password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                autoComplete="new-password"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm">Confirm password</Label>
              <Input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                minLength={6}
                autoComplete="new-password"
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Saving…" : "Reset password"}
            </Button>
          </form>
          <p className="mt-4 text-center">
            <Link href="/auth" className="text-sm text-muted-foreground hover:underline">
              Back to Log in
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
