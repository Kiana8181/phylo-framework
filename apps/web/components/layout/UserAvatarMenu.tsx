"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/features/auth/context";
import type { StoredUser } from "@/lib/auth/storage";

function getInitials(user: StoredUser): string {
  const source = user.username?.trim() || user.email?.trim() || "?";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }
  return source.slice(0, 2).toUpperCase();
}

function AvatarRing({
  user,
  size = "sm",
  className,
}: {
  user: StoredUser;
  size?: "sm" | "lg";
  className?: string;
}) {
  const dim = size === "sm" ? "h-9 w-9" : "h-16 w-16";
  const text = size === "sm" ? "text-xs" : "text-lg";

  return (
    <div
      className={cn(
        "rounded-full bg-gradient-to-br from-primary via-chart-2 to-primary p-[2px] shadow-sm",
        dim,
        className,
      )}
    >
      <div className="flex h-full w-full items-center justify-center rounded-full bg-background">
        <div
          className={cn(
            "flex h-[calc(100%-2px)] w-[calc(100%-2px)] items-center justify-center rounded-full bg-primary/10 font-semibold text-primary",
            text,
          )}
        >
          {getInitials(user)}
        </div>
      </div>
    </div>
  );
}

export function UserAvatarMenu() {
  const { user, isAuthenticated, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!isAuthenticated || !user) {
    return (
      <Link href="/auth">
        <Button variant="outline" size="sm" className="rounded-full px-4">
          Log in
        </Button>
      </Link>
    );
  }

  const displayName = user.username?.trim() || user.email.split("@")[0];

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="rounded-full transition-transform hover:scale-105 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
        aria-expanded={open}
        aria-haspopup="true"
        aria-label="Open account menu"
      >
        <AvatarRing user={user} size="sm" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+0.5rem)] z-50 w-64 rounded-xl border bg-popover p-4 shadow-lg animate-in fade-in-0 zoom-in-95 duration-150"
        >
          <div className="flex flex-col items-center gap-2 text-center">
            <AvatarRing user={user} size="lg" />
            <div className="min-w-0 space-y-0.5">
              <p className="truncate text-sm font-semibold text-foreground">{displayName}</p>
              <p className="truncate text-xs text-muted-foreground">{user.email}</p>
            </div>
          </div>

          <Separator className="my-3" />

          <Button
            variant="ghost"
            size="sm"
            role="menuitem"
            className="w-full justify-center gap-2 rounded-lg text-destructive/90 hover:bg-destructive/10 hover:text-destructive"
            onClick={() => {
              setOpen(false);
              void logout();
            }}
          >
            <LogOut className="h-4 w-4" />
            Log out
          </Button>
        </div>
      )}
    </div>
  );
}
