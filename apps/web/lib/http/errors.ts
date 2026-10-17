import { isEnvelope } from "@phylo/contracts";

type ValidationErrorItem = { msg?: string };

function detailMessage(detail: unknown): string | undefined {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as ValidationErrorItem | string | undefined;
    if (typeof first === "object" && first?.msg) return String(first.msg);
    if (first != null) return String(first);
  }
  return undefined;
}

function messageFromBody(data: unknown): string | undefined {
  if (typeof data !== "object" || data === null) return undefined;

  if (isEnvelope(data) && data.status === "error") {
    if (data.message && data.message !== "Validation error") {
      return String(data.message);
    }
    if (Array.isArray(data.data)) {
      const first = data.data[0] as ValidationErrorItem | undefined;
      if (first?.msg) return String(first.msg);
    }
    if (data.message) return String(data.message);
  }

  const body = data as { message?: string | null; detail?: unknown; error?: string };
  if (body.message) return String(body.message);
  const fromDetail = detailMessage(body.detail);
  if (fromDetail) return fromDetail;
  if (body.error) return String(body.error);
  return undefined;
}

function isGenericAxiosMessage(message: string): boolean {
  return message.startsWith("Request failed with status code");
}

/** Extract a user-facing message from an API or axios error. */
export function getApiErrorMessage(err: unknown, fallback = "Something went wrong"): string {
  if (typeof err === "object" && err !== null) {
    const maybeAxios = err as { response?: { data?: unknown }; message?: string };
    const fromBody = messageFromBody(maybeAxios.response?.data);
    if (fromBody) return fromBody;

    if (maybeAxios.message && !isGenericAxiosMessage(maybeAxios.message)) {
      return maybeAxios.message;
    }
  }

  if (err instanceof Error && !isGenericAxiosMessage(err.message)) {
    return err.message;
  }

  return fallback;
}

export function isAuthRequestUrl(url: string | undefined): boolean {
  if (!url) return false;
  return (
    url.includes("/auth/login") ||
    url.includes("/auth/register") ||
    url.includes("/auth/forgot-password") ||
    url.includes("/auth/reset-password") ||
    url.includes("/auth/verify-email") ||
    url.includes("/auth/challenge") ||
    url.includes("/auth/google")
  );
}
