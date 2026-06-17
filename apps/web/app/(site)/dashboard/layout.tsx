"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/features/auth/context";
import Sidebar from "@/components/dashboard/Sidebar";
import { Loading } from "@/components/ui/loading";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      router.replace("/auth");
    }
  }, [isAuthenticated, isLoading, router]);

  if (isLoading) {
    return <Loading fullScreen illustration="dna" label="Loading..." />;
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <Sidebar />
      <div className="min-w-0 flex-1 overflow-y-auto overflow-x-hidden overscroll-contain">
        {children}
      </div>
    </div>
  );
}
