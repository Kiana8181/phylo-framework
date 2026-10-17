import { redirect } from "next/navigation";

// The sign-in form lives at /auth. This address is kept for old links.
export default function LoginPage() {
  redirect("/auth?mode=login");
}
