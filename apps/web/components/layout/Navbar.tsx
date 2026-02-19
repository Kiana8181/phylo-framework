"use client";

import Link from "next/link";
import { useTheme } from "next-themes";
import { Moon, Sun, LogOut, User } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/context";

export default function Navbar() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const { user, isAuthenticated, logout } = useAuth();

  useEffect(() => {
    setMounted(true);
  }, []);

  const isDark = mounted && (resolvedTheme ?? theme) === "dark";

  return (
    <header className="sticky top-0 z-50 w-full shrink-0 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center justify-between gap-2 px-3 sm:px-4 md:px-6 min-w-0 w-full">
        <div className="flex items-center gap-2 sm:gap-4 min-w-0 flex-1">
          <Link
            href="/"
            className="text-base font-semibold text-foreground hover:text-primary transition-colors sm:text-lg truncate shrink-0"
          >
            Phylo Runner
          </Link>
          <nav className="flex items-center gap-2 sm:gap-4 shrink-0">
            <Link
              href="/"
              className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap"
            >
              Home
            </Link>
            <Link
              href="/dashboard"
              className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors whitespace-nowrap"
            >
              Dashboard
            </Link>
          </nav>
        </div>
        <div className="flex items-center gap-1 sm:gap-2 shrink-0">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(isDark ? "light" : "dark")}
            aria-label="Toggle theme"
            className="cursor-pointer"
          >
            {mounted ? (
              isDark ? (
                <Moon className="h-5 w-5" />
              ) : (
                <Sun className="h-5 w-5" />
              )
            ) : (
              <span className="h-5 w-5" />
            )}
          </Button>
          {isAuthenticated && user ? (
            <>
              <span className="flex items-center gap-2 text-sm text-muted-foreground px-2 select-none">
                <User className="h-4 w-4 shrink-0" />
                <span className="truncate max-w-[8rem] sm:max-w-[12rem]">
                  {user.username || user.email}
                </span>
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="text-sm gap-1"
                onClick={() => logout()}
              >
                <LogOut className="h-4 w-4" />
                Log out
              </Button>
            </>
          ) : (
            <>
              <Link href="/auth">
                <Button variant="ghost" size="sm" className="text-sm">
                  Log in
                </Button>
              </Link>
              <Link href="/auth?mode=signup">
                <Button size="sm" className="text-sm">
                  Sign up
                </Button>
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
