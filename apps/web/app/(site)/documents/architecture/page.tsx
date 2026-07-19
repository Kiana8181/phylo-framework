import type { Metadata } from "next";
import { ArchitectureDoc } from "@/components/docs/ArchitectureDoc";

export const metadata: Metadata = {
  title: "Architecture & workflow — Documentation",
  description:
    "Phylo Runner's services, ports and trust boundary, and the happy-path workflow from dataset upload to result.",
};

export default function ArchitecturePage() {
  return <ArchitectureDoc />;
}
