import type { Metadata } from "next";
import { OverviewDoc } from "@/components/docs/OverviewDoc";

export const metadata: Metadata = {
  title: "Documentation — Phylo Runner",
  description:
    "How Phylo Runner unifies Dowser, GCtree, BrepPhylo and ClonalTree, and per-method input and parameter reference.",
};

export default function DocumentsPage() {
  return <OverviewDoc />;
}
