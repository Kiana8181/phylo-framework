"use client";

import { useState } from "react";
import { MailWarning } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/context";
import { authApi } from "@/features/auth/api";
import { needsEmailVerification } from "@/lib/auth/storage";
import { notify } from "@/lib/notify";
import { getApiErrorMessage } from "@/lib/http/errors";

/**
 * Shown to a signed-in account that has not confirmed its email address yet
 * (when the deployment asks for that): explains why uploads and runs are not
 * available and offers a new link.
 */
export default function VerifyEmailBanner() {
  const { user, refreshUser } = useAuth();
  const [sending, setSending] = useState(false);

  if (!needsEmailVerification(user)) return null;

  async function resend() {
    setSending(true);
    try {
      const res = await authApi.resendVerification();
      if (res.email_verified) await refreshUser();
      notify.success(res.message);
    } catch (err: unknown) {
      notify.error("Could not send the email", getApiErrorMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      role="status"
      data-testid="verify-email-banner"
      className="flex flex-wrap items-center gap-3 border-b border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <MailWarning className="size-4 shrink-0" aria-hidden="true" />
      <p className="min-w-0 flex-1">
        <span className="font-medium">Confirm your email address to upload data and start runs.</span>{" "}
        We sent a link to <span className="font-medium">{user?.email}</span>.
      </p>
      <Button type="button" size="sm" variant="outline" onClick={resend} disabled={sending}>
        {sending ? "Sending…" : "Send a new link"}
      </Button>
    </div>
  );
}
