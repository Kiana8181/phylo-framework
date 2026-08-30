import type { Metadata } from "next";
import { TryItYourselfDoc } from "@/components/docs/TryItYourselfDoc";

export const metadata: Metadata = {
  title: "Try it yourself — Documentation",
  description:
    "A real single-clone AIRR dataset run through all four methods: download it, see the exact parameters and resulting tree, and reproduce the run in one click.",
};

export default function TryItYourselfPage() {
  return <TryItYourselfDoc />;
}
