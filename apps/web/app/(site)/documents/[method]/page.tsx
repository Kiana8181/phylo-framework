import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MethodDoc } from "@/components/docs/MethodDoc";
import { getMethodContent } from "@/features/docs/content";
import { METHOD_IDS, type MethodId } from "@/features/docs/types";

export const dynamicParams = false;

export function generateStaticParams() {
  return METHOD_IDS.map((method) => ({ method }));
}

function isMethodId(value: string): value is MethodId {
  return (METHOD_IDS as string[]).includes(value);
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ method: string }>;
}): Promise<Metadata> {
  const { method } = await params;
  if (!isMethodId(method)) return {};
  const content = getMethodContent(method);
  return {
    title: `${content.displayName} — Documentation`,
    description: content.tagline,
  };
}

export default async function MethodDocPage({
  params,
}: {
  params: Promise<{ method: string }>;
}) {
  const { method } = await params;
  if (!isMethodId(method)) notFound();
  return <MethodDoc id={method} />;
}
