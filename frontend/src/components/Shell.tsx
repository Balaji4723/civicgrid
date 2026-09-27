"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Building2,
  ChevronRight,
  Home,
  LogOut,
  Menu,
  Scale,
  ShieldCheck,
  Truck,
  User as UserIcon,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { session } from "@/lib/api";
import { useGuard } from "@/lib/hooks";
import { getNavForUser, getPersonaMeta, ROLE_NAV } from "@/lib/nav";
import type { Role } from "@/lib/types";
import { Badge, Spinner, type Tone } from "./ui";

export function Shell({
  allow,
  accent,
  title,
  subtitle,
  subnav,
  children,
}: {
  allow: Role[];
  accent: Tone;
  title: string;
  subtitle?: string;
  subnav?: { href: string; label: string }[];
  children: ReactNode;
}) {
  const user = useGuard(allow);
  const router = useRouter();
  const path = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-paper p-8">
        <Spinner label="Verifying session credentials" />
      </main>
    );
  }

  const roleMeta = getPersonaMeta(user);
  const navItems = getNavForUser(user);

  const handleSignOut = () => {
    session.clear();
    router.replace("/login");
  };

  const sidebarContent = (
    <div className="flex h-full flex-col justify-between p-4 sm:p-5">
      <div className="space-y-6">
        {/* Brand Logo & Portal Identity */}
        <div className="flex items-center gap-3">
          <Link href="/" className="flex items-center gap-2.5 font-bold tracking-tight text-ink">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink p-1.5 shadow-sm">
              <svg width="22" height="22" viewBox="0 0 26 26" aria-hidden>
                <rect x="1" y="1" width="11" height="11" rx="2.5" className="fill-ok-500" />
                <rect x="14" y="1" width="11" height="11" rx="2.5" className="fill-track-500" />
                <rect x="1" y="14" width="11" height="11" rx="2.5" className="fill-auth-500" />
                <rect x="14" y="14" width="11" height="11" rx="2.5" className="fill-proc-500" />
              </svg>
            </div>
            <div>
              <span className="text-base font-bold">CivicGrid</span>
              <span className="block text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
                {roleMeta.portalName}
              </span>
            </div>
          </Link>
        </div>

        {/* Current User Role Identity Pill */}
        <div className="rounded-xl border border-line bg-paper/60 p-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white shadow-xs border border-line text-ink-soft">
              <UserIcon className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-bold text-ink">{user.name}</p>
              <div className="mt-0.5">
                <Badge tone={roleMeta.tone}>{roleMeta.label}</Badge>
              </div>
            </div>
          </div>
        </div>

        {/* Role Specific Navigation Links */}
        <nav className="space-y-1" aria-label="Portal Navigation">
          <p className="px-2 text-[11px] font-bold uppercase tracking-wider text-ink-faint mb-2">
            Navigation
          </p>
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = item.exact ? path === item.href : path.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all ${
                  active
                    ? "bg-ink text-white shadow-sm"
                    : "text-ink-soft hover:bg-paper hover:text-ink"
                }`}
              >
                <Icon className={`h-4 w-4 shrink-0 ${active ? "text-white" : "text-ink-soft"}`} />
                <span className="truncate">{item.label}</span>
                {active && <ChevronRight className="ml-auto h-3.5 w-3.5 text-white/70" />}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Bottom Footer & Sign Out */}
      <div className="border-t border-line pt-4 space-y-3">
        <div className="flex items-center justify-between text-[11px] text-ink-faint px-1">
          <span>SHA-256 Verified</span>
          <span className="flex items-center gap-1 font-medium text-ok-700">
            <span className="h-1.5 w-1.5 rounded-full bg-ok-600 animate-pulse" /> Live
          </span>
        </div>
        <button
          type="button"
          onClick={handleSignOut}
          className="flex w-full items-center gap-2.5 rounded-lg border border-line bg-white px-3 py-2 text-xs font-semibold text-ink-soft hover:bg-flag-50 hover:text-flag-700 hover:border-flag-100 transition-colors"
        >
          <LogOut className="h-4 w-4" />
          Sign out of session
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-paper text-ink flex">
      {/* Desktop Fixed Left Sidebar */}
      <aside className="hidden lg:flex w-64 shrink-0 flex-col border-r border-line bg-white sticky top-0 h-screen z-30">
        <div className={`h-1.5 w-full ${roleMeta.accentColor}`} />
        {sidebarContent}
      </aside>

      {/* Mobile Drawer Backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/60 backdrop-blur-xs lg:hidden transition-opacity"
          onClick={() => setMobileOpen(false)}
          aria-hidden
        />
      )}

      {/* Mobile Slide-over Drawer */}
      <div
        className={`fixed inset-y-0 left-0 z-50 w-72 bg-white shadow-2xl transition-transform duration-200 ease-in-out lg:hidden flex flex-col ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <span className="text-sm font-bold text-ink">CivicGrid Navigation</span>
          <button
            type="button"
            onClick={() => setMobileOpen(false)}
            className="rounded-lg p-1 text-ink-soft hover:bg-paper"
            aria-label="Close navigation"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">{sidebarContent}</div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Header */}
        <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur-sm">
          <div className="flex items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileOpen(true)}
                className="lg:hidden rounded-lg border border-line p-2 text-ink-soft hover:bg-paper focus:outline-none"
                aria-label="Open mobile menu"
              >
                <Menu className="h-5 w-5" />
              </button>
              <div>
                <h1 className="text-lg font-bold tracking-tight text-ink leading-tight sm:text-xl">
                  {title}
                </h1>
                {subtitle && (
                  <p className="text-xs text-ink-soft mt-0.5 line-clamp-1">{subtitle}</p>
                )}
              </div>
            </div>

            <div className="flex items-center gap-3 text-xs">
              <div className="hidden sm:flex flex-col text-right">
                <span className="font-semibold text-ink">{user.name}</span>
                <span className="text-[11px] text-ink-soft">{user.username}</span>
              </div>
              <Badge tone={roleMeta.tone}>{roleMeta.label}</Badge>
              <button
                type="button"
                onClick={handleSignOut}
                className="hidden sm:flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-xs font-medium text-ink-soft hover:bg-paper hover:text-ink transition-colors"
              >
                <LogOut className="h-3.5 w-3.5" />
                Sign out
              </button>
            </div>
          </div>

          {/* Subnavigation Bar (when present) */}
          {subnav && subnav.length > 0 && (
            <div className="border-t border-line/80 px-4 sm:px-6 lg:px-8 bg-paper/30 overflow-x-auto">
              <nav className="flex gap-2 py-1.5 min-w-max" aria-label="Section Tabs">
                {subnav.map((s) => {
                  const active = s.href === path;
                  return (
                    <Link
                      key={s.href}
                      href={s.href}
                      aria-current={active ? "page" : undefined}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                        active
                          ? "bg-white text-ink font-semibold shadow-xs border border-line"
                          : "text-ink-soft hover:text-ink hover:bg-paper"
                      }`}
                    >
                      {s.label}
                    </Link>
                  );
                })}
              </nav>
            </div>
          )}
        </header>

        {/* Page Main Content Container */}
        <main className="flex-1 px-4 py-6 sm:px-6 lg:px-8 max-w-7xl w-full mx-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
