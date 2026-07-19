import type { Metadata } from "next";
import { DataModelDoc } from "@/components/docs/DataModelDoc";

export const metadata: Metadata = {
  title: "Data model & I/O — Documentation",
  description:
    "The persistent database entities, and each method's accepted inputs and result outputs.",
};

export default function DataModelPage() {
  return <DataModelDoc />;
}
