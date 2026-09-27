"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  Home,
  Lock,
  RotateCcw,
  Scale,
  ShieldCheck,
  Truck,
  User as UserIcon,
} from "lucide-react";
import { api, ApiError, session } from "@/lib/api";
import { getHomeForUser } from "@/lib/nav";
import type { User } from "@/lib/types";
import { Btn, Field, inputCls, Notice } from "@/components/ui";

const ROLE_ENTRIES = [
  {
    u: "citizen1",
    p: "demo123",
    label: "Continue as Citizen",
    desc: "Household segregation, collection history & civic sanitation reports (Anita Sharma)",
    icon: Home,
    tone: "border-l-ok-600 hover:border-ok-600 hover:bg-ok-50/40 text-ok-700",
  },
  {
    u: "worker1",
    p: "demo123",
    label: "Continue as Field Worker",
    desc: "Household pickup, random audit gates & sealed trip dispatch (Ramesh Patil)",
    icon: Truck,
    tone: "border-l-track-600 hover:border-track-600 hover:bg-track-50/40 text-track-700",
  },
  {
    u: "facility1",
    p: "demo123",
    label: "Continue as Receiving Operator",
    desc: "Weighbridge intake, stream condition & automated cross-check (Kiran Bhatt)",
    icon: Scale,
    tone: "border-l-track-600 hover:border-track-600 hover:bg-track-50/40 text-track-700",
  },
  {
    u: "facility_ops",
    p: "demo123",
    label: "Continue as Facility Operator",
    desc: "Material recovery, RDF/composting, transfer handoffs & disposition (Suresh Kumar)",
    icon: RotateCcw,
    tone: "border-l-proc-600 hover:border-proc-600 hover:bg-proc-50/40 text-proc-700",
  },
  {
    u: "facility2",
    p: "demo123",
    label: "Continue as Independent Verifier",
    desc: "Cross-facility audit, evidence corroboration & root-cause resolution (Meera Joshi)",
    icon: ClipboardCheck,
    tone: "border-l-auth-600 hover:border-auth-600 hover:bg-auth-50/40 text-auth-700",
  },
  {
    u: "admin1",
    p: "demo123",
    label: "Continue as Municipal Authority",
    desc: "City-wide read-only governance & SHA-256 ledger integrity (Dr. Neha Kulkarni)",
    icon: Building2,
    tone: "border-l-proc-600 hover:border-proc-600 hover:bg-proc-50/40 text-proc-700",
  },
];

const WASTE_JOURNEY_STAGES = [
  { label: "Collection", icon: Home, desc: "Household segregation & random verification" },
  { label: "Digital Load", icon: Truck, desc: "Auto-generated from completed trip" },
  { label: "Receiving", icon: Scale, desc: "Authoritative weighbridge cross-check" },
  { label: "Processing & Disposition", icon: RotateCcw, desc: "Verifiable recovery & disposal trail" },
];

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeRoleIndex, setActiveRoleIndex] = useState<number | null>(null);

  async function signIn(u: string, p: string, roleIndex?: number) {
    const cleanU = u.trim();
    if (!cleanU || !p) {
      setErr("Please enter both username and password.");
      return;
    }
    setUsername(cleanU);
    setPassword(p);
    setBusy(true);
    setErr(null);
    if (roleIndex !== undefined) setActiveRoleIndex(roleIndex);

    try {
      const res = await api<{ access_token: string; user: User }>("/auth/login", {
        body: { username: cleanU, password: p },
      });
      session.save(res.access_token, res.user);
      router.replace(getHomeForUser(res.user));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Authentication failed. Please check credentials.");
      setBusy(false);
      setActiveRoleIndex(null);
    }
  }


  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 selection:bg-track-100 selection:text-track-700">
      <div className="mx-auto flex min-h-screen max-w-7xl flex-col justify-center px-4 py-8 sm:px-6 lg:px-8">
        <div className="grid gap-8 lg:grid-cols-12 lg:gap-12 items-center">
          
          {/* Left Column: Product Identity & Waste Journey */}
          <div className="space-y-6 lg:col-span-6 lg:pr-4">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink p-2 shadow-md">
                <svg width="28" height="28" viewBox="0 0 26 26" aria-hidden>
                  <rect x="1" y="1" width="11" height="11" rx="2.5" className="fill-ok-500" />
                  <rect x="14" y="1" width="11" height="11" rx="2.5" className="fill-track-500" />
                  <rect x="1" y="14" width="11" height="11" rx="2.5" className="fill-auth-500" />
                  <rect x="14" y="14" width="11" height="11" rx="2.5" className="fill-proc-500" />
                </svg>
              </div>
              <div>
                <span className="text-2xl font-bold tracking-tight text-ink">CivicGrid</span>
                <span className="ml-2 rounded-md bg-paper px-2 py-0.5 text-xs font-semibold text-ink-soft border border-line">
                  Operations
                </span>
              </div>
            </div>

            <div>
              <h1 className="text-3xl font-extrabold tracking-tight text-ink sm:text-4xl sm:leading-tight">
                Civic infrastructure, connected.
              </h1>
              <p className="mt-3 text-base text-ink-soft sm:text-lg leading-relaxed">
                Track waste from household collection through verification, processing, and final disposition — while connecting sanitation reports with municipal action.
              </p>
            </div>

            {/* Subtle Waste Journey Progression Card */}
            <div className="rounded-2xl border border-line bg-white/80 p-5 shadow-sm backdrop-blur-sm">
              <p className="text-xs font-semibold uppercase tracking-wider text-ink-faint mb-3">
                Connected Waste Lifecycle
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {WASTE_JOURNEY_STAGES.map((s, idx) => {
                  const Icon = s.icon;
                  return (
                    <div key={idx} className="flex items-start gap-3 rounded-xl border border-line/60 bg-paper/60 p-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white shadow-xs border border-line/60 text-track-600">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-ink">{s.label}</p>
                        <p className="text-[11px] text-ink-soft truncate">{s.desc}</p>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="mt-4 flex items-center justify-between border-t border-line/60 pt-3 text-xs text-ink-soft">
                <span className="flex items-center gap-1.5 font-medium text-ok-700">
                  <CheckCircle2 className="h-3.5 w-3.5" /> SHA-256 Tamper-Evident Trail
                </span>
                <span className="font-medium text-auth-700">Independent Cross-Check Engine</span>
              </div>
            </div>
          </div>

          {/* Right Column: Sign In Card & Role Portals */}
          <div className="space-y-5 lg:col-span-6">
            <div className="rounded-2xl border border-line bg-white p-6 sm:p-8 shadow-xl shadow-slate-200/50">
              <div className="mb-6">
                <h2 className="text-xl font-bold text-ink tracking-tight">Sign In</h2>
                <p className="mt-1 text-sm text-ink-soft">
                  Access your role-specific CivicGrid workspace
                </p>
              </div>

              {/* Standard Credentials Form */}
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void signIn(username, password);
                }}
                className="space-y-4"
              >
                <Field label="Username">
                  <div className="relative">
                    <input
                      type="text"
                      className={`${inputCls} pl-10`}
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="Enter your username"
                      autoComplete="username"
                      disabled={busy}
                    />
                    <UserIcon className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-faint" />
                  </div>
                </Field>

                <Field label="Password">
                  <div className="relative">
                    <input
                      type="password"
                      className={`${inputCls} pl-10`}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Enter your password"
                      autoComplete="current-password"
                      disabled={busy}
                    />
                    <Lock className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-ink-faint" />
                  </div>
                </Field>

                <Btn
                  type="submit"
                  tone="neutral"
                  busy={busy && activeRoleIndex === null}
                  disabled={!username.trim() || !password || busy}
                  className="w-full py-2.5 font-semibold text-sm shadow-md"
                >
                  Sign in to CivicGrid
                </Btn>
              </form>

              {err && (
                <div className="mt-4">
                  <Notice tone="flag" title="Authentication Error">
                    {err}
                  </Notice>
                </div>
              )}

              {/* Professional Role Entry Quick-Access */}
              <div className="relative my-6 text-center">
                <div className="absolute inset-0 flex items-center" aria-hidden>
                  <div className="w-full border-t border-line" />
                </div>
                <div className="relative flex justify-center">
                  <span className="bg-white px-3 text-xs font-semibold uppercase tracking-wider text-ink-faint">
                    Quick Role Access
                  </span>
                </div>
              </div>

              <div className="grid gap-2.5 sm:grid-cols-2">
                {ROLE_ENTRIES.map((role, idx) => {
                  const Icon = role.icon;
                  const isThisBusy = busy && activeRoleIndex === idx;
                  return (
                    <button
                      key={role.u}
                      type="button"
                      disabled={busy}
                      onClick={() => signIn(role.u, role.p, idx)}
                      className={`group flex items-start gap-3 rounded-xl border border-l-4 border-line bg-white p-3 text-left transition-all duration-150 hover:shadow-sm disabled:opacity-60 ${role.tone}`}
                    >
                      <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-paper border border-line text-ink-soft group-hover:text-ink">
                        <Icon className="h-3.5 w-3.5" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <span className="block text-xs font-bold text-ink tracking-tight">
                          {role.label}
                        </span>
                        <span className="block text-[11px] text-ink-soft leading-tight mt-0.5 line-clamp-1">
                          {role.desc}
                        </span>
                      </div>
                      <ArrowRight className="h-3.5 w-3.5 text-ink-faint group-hover:translate-x-0.5 transition-transform" />
                    </button>
                  );
                })}
              </div>
            </div>

            <p className="text-center text-xs text-ink-faint">
              CivicGrid Municipal Operating Platform · Secure Role-Based Access
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}
