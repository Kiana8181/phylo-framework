"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/context";
import { SAMPLE_PARAMS, TRY_SAMPLE_KEY, type TrySampleIntent } from "@/features/docs/sample";
import type { MethodId } from "@/features/docs/types";

/**
 * Hands a worked example off to the run wizard: records the method and its
 * parameters, then navigates. The dashboard picks the intent up, makes sure the
 * example dataset is uploaded, and opens the wizard on it.
 *
 * Running anything needs an account, so the button is disabled until the reader
 * is signed in.
 */
export function TryItButton({ methodId, label }: { methodId: MethodId; label: string }) {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  const handleClick = () => {
    const intent: TrySampleIntent = { methodId, params: SAMPLE_PARAMS[methodId] };
    try {
      sessionStorage.setItem(TRY_SAMPLE_KEY, JSON.stringify(intent));
    } catch {
      // Private-mode / storage-disabled: still send them to the wizard, just blank.
    }
    router.push("/dashboard");
  };

  return (
    <div className="space-y-1.5">
      <Button
        type="button"
        className="gap-2"
        disabled={isLoading || !isAuthenticated}
        onClick={handleClick}
      >
        <Play className="h-4 w-4" />
        Try {label} yourself
      </Button>
      {!isLoading && !isAuthenticated && (
        <p className="text-sm text-destructive">
          <Link href="/auth" className="underline underline-offset-2">
            Sign in
          </Link>{" "}
          first to test this.
        </p>
      )}
    </div>
  );
}
