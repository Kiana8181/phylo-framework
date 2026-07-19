import type { Metadata } from "next";
import { DataRequirementsDoc } from "@/components/docs/DataRequirementsDoc";

export const metadata: Metadata = {
  title: "Data requirements — Documentation",
  description:
    "Which input columns each method needs, the columns accepted by every method, file-format compatibility, and a sample dataset.",
};

export default function DataRequirementsPage() {
  return <DataRequirementsDoc />;
}
