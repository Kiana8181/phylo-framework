import Navbar from "@/components/layout/Navbar";

export default function SiteLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <Navbar />
      <div className="flex-1 min-h-0 overflow-auto">{children}</div>
    </div>
  );
}
