import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function SignupPage() {
  return (
    <main className="mx-auto max-w-md p-4 sm:p-6 space-y-6">
      <h1 className="text-xl font-semibold sm:text-2xl">Sign up</h1>
      <p className="text-muted-foreground text-sm">
        Sign up page. Authentication will be connected in a future release.
      </p>
      <Link href="/">
        <Button variant="outline">Back to Home</Button>
      </Link>
    </main>
  );
}
