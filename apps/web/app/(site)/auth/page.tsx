"use client";

import { Suspense, useState, useEffect } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loading } from "@/components/ui/loading";
import { useAuth } from "@/features/auth/context";
import { authApi } from "@/features/auth/api";
import { notify } from "@/lib/notify";

type Mode = "login" | "signup";

function AuthPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login, register, isAuthenticated, isLoading } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);

  useEffect(() => {
    const m = searchParams.get("mode");
    if (m === "signup") setMode("signup");
    else if (m === "login") setMode("login");
  }, [searchParams]);

  if (isAuthenticated) {
    router.replace("/dashboard");
    return null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
        notify.success("Logged in");
      } else {
        await register(email, username, password);
        notify.success("Account created");
      }
      router.replace("/dashboard");
    } catch (err: unknown) {
      const data = (err as { response?: { data?: unknown } })?.response?.data;
      const message =
        (typeof data === "object" && data !== null && "detail" in data)
          ? String((data as { detail: unknown }).detail)
          : err instanceof Error
            ? err.message
            : "Something went wrong";
      notify.error(mode === "login" ? "Log in failed" : "Sign up failed", message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogleLogin() {
    setGoogleLoading(true);
    try {
      const { auth_url } = await authApi.getGoogleAuthUrl();
      window.location.href = auth_url;
    } catch (err: unknown) {
      const data = (err as { response?: { data?: unknown } })?.response?.data;
      const message =
        (typeof data === "object" && data !== null && "detail" in data)
          ? String((data as { detail: unknown }).detail)
          : "Google sign-in is not configured";
      notify.error("Google sign-in", message);
      setGoogleLoading(false);
    }
  }

  if (isLoading) {
    return <Loading fullScreen label="Loading…" />;
  }

  return (
    <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl">
            {mode === "login" ? "Log in" : "Sign up"}
          </CardTitle>
          <CardDescription>
            {mode === "login"
              ? "Enter your email and password."
              : "Create an account with email and username."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>
            {mode === "signup" && (
              <div className="space-y-2">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  type="text"
                  placeholder="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoComplete="username"
                />
              </div>
            )}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                {mode === "login" && (
                  <Link
                    href="/auth/forgot-password"
                    className="text-xs text-primary hover:underline"
                  >
                    Forgot password?
                  </Link>
                )}
              </div>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </div>
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Please wait..." : mode === "login" ? "Log in" : "Sign up"}
            </Button>
            <div className="relative my-4">
              <span className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </span>
              <span className="relative flex justify-center text-xs uppercase text-muted-foreground">
                Or
              </span>
            </div>
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={googleLoading}
              onClick={handleGoogleLogin}
            >
              {googleLoading ? "Redirecting…" : "Continue with Google"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            {mode === "login" ? (
              <>
                Don&apos;t have an account?{" "}
                <button
                  type="button"
                  className="text-primary font-medium hover:underline"
                  onClick={() => setMode("signup")}
                >
                  Sign up
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  className="text-primary font-medium hover:underline"
                  onClick={() => setMode("login")}
                >
                  Log in
                </button>
              </>
            )}
          </p>
          <p className="mt-2 text-center">
            <Link href="/" className="text-sm text-muted-foreground hover:underline">
              Back to Home
            </Link>
          </p>
        </CardContent>
      </Card>
    </main>
  );
}

export default function AuthPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center p-4">
          <p className="text-muted-foreground">Loading...</p>
        </main>
      }
    >
      <AuthPageContent />
    </Suspense>
  );
}
