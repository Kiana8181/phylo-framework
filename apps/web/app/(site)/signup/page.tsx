import { redirect } from "next/navigation";

// The sign-up form lives at /auth. This address is kept for old links.
export default function SignupPage() {
  redirect("/auth?mode=signup");
}
