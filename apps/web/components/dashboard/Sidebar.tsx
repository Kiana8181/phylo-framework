"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { FileStack, FolderOpen, GitCompare, Play, PanelLeftClose, PanelLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PhyloLogo } from "@/components/layout/PhyloLogo";
import { useEffect, useState } from "react";

const SIDEBAR_COLLAPSED_KEY = "phylo-sidebar-collapsed";

const navItems = [
  { href: "/dashboard", label: "Run model", icon: Play },
  { href: "/dashboard/history", label: "Run history", icon: FileStack },
  { href: "/dashboard/files", label: "File management", icon: FolderOpen },
  { href: "/dashboard/comparison", label: "Sequence Trace", icon: GitCompare },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    const raw = typeof window !== "undefined" ? localStorage.getItem(SIDEBAR_COLLAPSED_KEY) : null;
    if (raw !== null) setCollapsed(raw === "1");
  }, []);

  const toggle = () => {
    setCollapsed((c) => {
      const next = !c;
      if (typeof window !== "undefined") localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      return next;
    });
  };

  return (
    <aside
      className={cn(
        "relative flex shrink-0 flex-col border-r bg-sidebar/80 transition-[width] duration-200 ease-in-out overflow-hidden",
        collapsed ? "w-[4.25rem]" : "w-60",
      )}
    >
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -right-10 -top-10 h-36 w-36 rounded-full bg-primary/15 blur-2xl" />
        <div className="absolute -left-14 bottom-8 h-44 w-44 rounded-full bg-chart-2/12 blur-3xl" />
        <div className="absolute -left-6 bottom-24 h-20 w-20 rounded-full bg-primary/10 blur-xl" />
      </div>

      <div
        className={cn(
          "relative z-10 border-b border-sidebar-border/80 px-3 py-4",
          collapsed ? "flex justify-center" : "px-4",
        )}
      >
        <PhyloLogo collapsed={collapsed} />
      </div>

      <nav className="relative z-10 flex flex-1 flex-col gap-1.5 p-3 min-h-0">
        {!collapsed && (
          <p className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/80">
            Workspace
          </p>
        )}
        {navItems.map(({ href, label, icon: Icon }) => {
          const isActive =
            href === "/dashboard" ? pathname === "/dashboard" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              className={cn(
                "group relative flex items-center gap-3 rounded-xl py-2.5 text-sm font-medium transition-all min-w-0",
                collapsed ? "justify-center px-2" : "px-3",
                isActive
                  ? "bg-primary/12 text-primary shadow-sm"
                  : "text-muted-foreground hover:bg-sidebar-accent/80 hover:text-foreground",
              )}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-primary" />
              )}
              <span
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-colors",
                  isActive
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "bg-muted/60 text-muted-foreground group-hover:bg-primary/10 group-hover:text-primary",
                )}
              >
                <Icon className="h-4 w-4" />
              </span>
              {!collapsed && <span className="truncate">{label}</span>}
            </Link>
          );
        })}
      </nav>

      <div className="relative z-10 border-t border-sidebar-border/80 p-3">
        <Button
          variant="ghost"
          size={collapsed ? "icon" : "sm"}
          onClick={toggle}
          className={cn("w-full text-muted-foreground hover:text-foreground", !collapsed && "justify-start gap-2")}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          {!collapsed && <span className="text-sm">Collapse</span>}
        </Button>
      </div>
    </aside>
  );
}
