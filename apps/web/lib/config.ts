export const apiBaseURL = () => {
  const fromEnv = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (fromEnv) return fromEnv;

  // Fallback for cases where NEXT_PUBLIC_API_BASE_URL is missing at build time.
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }

  return "";
};
