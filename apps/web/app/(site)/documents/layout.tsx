import DocsSidebar from "@/components/docs/DocsSidebar";

export default function DocumentsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <div className="md:sticky md:top-0 md:h-[calc(100vh-3.5rem)] md:shrink-0 md:overflow-y-auto">
        <DocsSidebar />
      </div>
      <main className="min-w-0 flex-1 px-4 py-8 sm:px-6 lg:px-10">{children}</main>
    </div>
  );
}
