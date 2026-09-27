import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  Coins,
  FileText,
  Home,
  MapPin,
  Package,
  RotateCcw,
  Scale,
  ShieldCheck,
  Truck,
  type LucideIcon,
} from "lucide-react";
import type { Role, User } from "./types";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
}

export type FacilityCapabilityType =
  | "RECEIVING"
  | "PROCESSING"
  | "INDEPENDENT_VERIFIER"
  | "MUNICIPAL"
  | "WORKER"
  | "CITIZEN"
  | "UNKNOWN";

export interface PersonaMeta {
  label: string;
  portalName: string;
  subtitle: string;
  tone: "ok" | "track" | "proc" | "auth" | "flag" | "neutral";
  icon: LucideIcon;
  accentColor: string;
}

export function getUserCapability(user?: User | null): FacilityCapabilityType {
  if (!user) return "UNKNOWN";
  if (user.role === "CITIZEN") return "CITIZEN";
  if (user.role === "WORKER") return "WORKER";
  if (user.role === "MUNICIPAL_ADMIN") return "MUNICIPAL";

  if (user.role === "FACILITY") {
    const cap = (user.capability || "").toUpperCase();
    if (cap.includes("PROCESSING")) return "PROCESSING";
    if (
      cap.includes("INDEPENDENT_VERIFIER") ||
      cap.includes("VERIFIER") ||
      cap.includes("AUDITOR")
    )
      return "INDEPENDENT_VERIFIER";
    if (cap.includes("RECEIVING")) return "RECEIVING";

    const u = (user.username || "").toLowerCase();
    if (u.includes("ops") || u.includes("proc")) return "PROCESSING";
    if (
      u.includes("facility2") ||
      u.includes("verifier") ||
      u.includes("auditor")
    )
      return "INDEPENDENT_VERIFIER";
    return "RECEIVING";
  }
  return "UNKNOWN";
}

export function getPersonaMeta(user?: User | null): PersonaMeta {
  const cap = getUserCapability(user);
  switch (cap) {
    case "CITIZEN":
      return {
        label: "Citizen",
        portalName: "Citizen Services",
        subtitle: "Household Segregation & Civic Action",
        tone: "ok",
        icon: Home,
        accentColor: "bg-ok-600",
      };
    case "WORKER":
      return {
        label: "Field Worker",
        portalName: "Collection Operations",
        subtitle: "Household Collection & Route Operations",
        tone: "track",
        icon: Truck,
        accentColor: "bg-track-600",
      };
    case "RECEIVING":
      return {
        label: "Receiving Operator",
        portalName: "Receiving & Weighbridge",
        subtitle: "Intake Weighbridge & Cross-Check",
        tone: "track",
        icon: Scale,
        accentColor: "bg-track-600",
      };
    case "PROCESSING":
      return {
        label: "Downstream Facility Operator",
        portalName: "Facility Operations",
        subtitle: "Downstream Processing & Material Recovery",
        tone: "proc",
        icon: RotateCcw,
        accentColor: "bg-proc-600",
      };
    case "INDEPENDENT_VERIFIER":
      return {
        label: "Independent Verifier",
        portalName: "Independent Verification",
        subtitle: "Evidence • Corroboration • Investigation",
        tone: "auth",
        icon: ClipboardCheck,
        accentColor: "bg-auth-600",
      };
    case "MUNICIPAL":
      return {
        label: "Municipal Authority",
        portalName: "City-Wide Oversight",
        subtitle: "Read-Only Waste Management Oversight",
        tone: "proc",
        icon: Building2,
        accentColor: "bg-proc-600",
      };
    default:
      return {
        label: user?.role ?? "User",
        portalName: "CivicGrid",
        subtitle: "Municipal Operations Platform",
        tone: "neutral",
        icon: ShieldCheck,
        accentColor: "bg-ink",
      };
  }
}

export const ROLE_NAV: Record<Role, NavItem[]> = {
  CITIZEN: [
    { href: "/citizen", label: "My Household", icon: Home, exact: true },
    { href: "/citizen/collections", label: "Collection History", icon: FileText },
    { href: "/citizen/credits", label: "Civic Credits", icon: Coins },
    { href: "/citizen/sanitation", label: "Sanitation Reports", icon: MapPin },
  ],
  WORKER: [
    { href: "/worker", label: "Collection Dashboard", icon: Truck, exact: true },
  ],
  FACILITY: [
    { href: "/receiving", label: "Receiving / Weighbridge", icon: Scale, exact: true },
    { href: "/authority/loads", label: "Incoming Loads", icon: Package },
  ],
  MUNICIPAL_ADMIN: [
    { href: "/municipal", label: "City Overview", icon: Building2, exact: true },
    { href: "/municipal/sanitation", label: "Sanitation Oversight", icon: MapPin },
    { href: "/authority/loads", label: "Digital Loads", icon: Package },
    { href: "/audits", label: "Audit Oversight", icon: ClipboardCheck },
    { href: "/authority/discrepancies", label: "Discrepancy Oversight", icon: AlertTriangle },
    { href: "/authority/processing", label: "Processing Oversight", icon: RotateCcw },
    { href: "/authority/handoffs", label: "Handoffs Oversight", icon: Truck },
    { href: "/authority/final-dispositions", label: "Final Dispositions", icon: CheckCircle2 },
  ],
};

export function getNavForUser(user?: User | null): NavItem[] {
  if (!user) return [];
  const cap = getUserCapability(user);

  if (cap === "CITIZEN") return ROLE_NAV.CITIZEN;
  if (cap === "WORKER") return ROLE_NAV.WORKER;
  if (cap === "MUNICIPAL") return ROLE_NAV.MUNICIPAL_ADMIN;

  if (cap === "PROCESSING") {
    return [
      { href: "/authority/processing", label: "Processing", icon: RotateCcw, exact: true },
      { href: "/authority/handoffs", label: "Handoffs", icon: Truck },
      { href: "/authority/disposal-exceptions", label: "Disposal Exceptions", icon: AlertTriangle },
      { href: "/authority/final-dispositions", label: "Final Disposition", icon: CheckCircle2 },
      { href: "/authority/loads", label: "Digital Loads", icon: Package },
    ];
  }

  if (cap === "INDEPENDENT_VERIFIER") {
    return [
      { href: "/audits", label: "Verification Center", icon: ClipboardCheck, exact: true },
      { href: "/authority/discrepancies", label: "Discrepancy Investigation", icon: AlertTriangle },
      { href: "/authority/loads", label: "Digital Loads", icon: Package },
    ];
  }

  // Default: Receiving Operator (facility1 / RECEIVING)
  return [
    { href: "/receiving", label: "Receiving / Weighbridge", icon: Scale, exact: true },
    { href: "/authority/loads", label: "Incoming Loads", icon: Package },
  ];
}

export const MUNICIPAL_SUBNAV = [
  { href: "/municipal", label: "Overview & Stream Integrity" },
  { href: "/municipal/sanitation", label: "Sanitation Oversight" },
  { href: "/audits", label: "Audit Oversight" },
  { href: "/authority/loads", label: "Digital Loads" },
  { href: "/authority/discrepancies", label: "Discrepancies" },
  { href: "/authority/processing", label: "Processing" },
  { href: "/authority/handoffs", label: "Handoffs" },
  { href: "/authority/final-dispositions", label: "Final Disposition" },
];

export const RECEIVING_SUBNAV = [
  { href: "/receiving", label: "Receiving / Weighbridge" },
  { href: "/authority/loads", label: "Incoming / Digital Loads" },
];

export const PROCESSING_SUBNAV = [
  { href: "/authority/processing", label: "Processing Operations" },
  { href: "/authority/handoffs", label: "Transfer Handoffs" },
  { href: "/authority/disposal-exceptions", label: "Disposal Exceptions" },
  { href: "/authority/final-dispositions", label: "Final Disposition" },
  { href: "/authority/loads", label: "Digital Loads" },
];

export const VERIFIER_SUBNAV = [
  { href: "/audits", label: "Independent Verification Center" },
  { href: "/authority/discrepancies", label: "Discrepancy Investigation" },
  { href: "/authority/loads", label: "Digital Loads (Read-Only)" },
];

export const AUTHORITY_SUBNAV = [
  { href: "/authority/loads", label: "Digital Loads" },
  { href: "/authority/discrepancies", label: "Discrepancies" },
  { href: "/audits", label: "Audits" },
  { href: "/authority/processing", label: "Processing" },
  { href: "/authority/handoffs", label: "Handoffs" },
  { href: "/authority/disposal-exceptions", label: "Disposal Exceptions" },
  { href: "/authority/final-dispositions", label: "Final Disposition" },
];

export function getSubnavForUser(user?: User | null): { href: string; label: string }[] {
  const cap = getUserCapability(user);
  if (cap === "MUNICIPAL") return MUNICIPAL_SUBNAV;
  if (cap === "RECEIVING") return RECEIVING_SUBNAV;
  if (cap === "PROCESSING") return PROCESSING_SUBNAV;
  if (cap === "INDEPENDENT_VERIFIER") return VERIFIER_SUBNAV;
  return RECEIVING_SUBNAV;
}

export function getHomeForUser(user?: User | null): string {
  if (!user) return "/login";
  const cap = getUserCapability(user);
  switch (cap) {
    case "CITIZEN":
      return "/citizen";
    case "WORKER":
      return "/worker";
    case "RECEIVING":
      return "/receiving";
    case "PROCESSING":
      return "/authority/processing";
    case "INDEPENDENT_VERIFIER":
      return "/audits";
    case "MUNICIPAL":
      return "/municipal";
    default:
      if (user.role === "CITIZEN") return "/citizen";
      if (user.role === "WORKER") return "/worker";
      if (user.role === "MUNICIPAL_ADMIN") return "/municipal";
      return "/receiving";
  }
}


export const fmtBytes = (n: number | null) =>
  n == null
    ? ""
    : n < 1024
      ? `${n} B`
      : n < 1048576
        ? `${(n / 1024).toFixed(1)} KB`
        : `${(n / 1048576).toFixed(1)} MB`;

/**
 * Strips development-environment prefixes/suffixes from ward/queue names
 * so that "Demo Ward A", "Ward Demo A", "[DEMO/SYNTHETIC] Ward B" etc.
 * are presented cleanly in the UI without modifying backend data.
 */
export function cleanLabel(raw: string | null | undefined): string {
  if (!raw) return "";
  return raw
    .replace(/\[DEMO\/SYNTHETIC\]\s*/gi, "")
    .replace(/\[DEMO\]\s*/gi, "")
    .replace(/\[SYNTHETIC\]\s*/gi, "")
    .replace(/^Demo\s+/i, "")
    .replace(/\s+Demo$/i, "")
    .replace(/^DEMO\s+/i, "")
    .replace(/^SYNTHETIC\s+/i, "")
    .replace(/^PROTOTYPE\s+/i, "")
    .replace(/\bk\s*fnd2k\b/gi, "")
    .replace(/\bdobe\b/gi, "")
    .trim();
}

