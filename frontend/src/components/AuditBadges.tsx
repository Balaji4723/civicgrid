"use client";
import type { AuditMethod, AuditStatus } from "@/lib/types";
import { Badge, type Tone } from "./ui";

const methodTone: Record<AuditMethod, Tone> = { RANDOM: "track", RISK_BASED: "proc", MANUAL: "auth" };
const statusTone: Record<AuditStatus, Tone> = { PENDING: "proc", IN_PROGRESS: "track", COMPLETED: "ok", CANCELLED: "neutral" };
export const MethodBadge = ({ m }: { m: AuditMethod }) => <Badge tone={methodTone[m]}>{m === "RISK_BASED" ? "RISK-BASED" : m}</Badge>;
export const AuditStatusBadge = ({ s }: { s: AuditStatus }) => <Badge tone={statusTone[s]}>{s.replace("_", " ")}</Badge>;
export const VERDICT_TEXT: Record<string, string> = {
  SUPPORTS_WORKER: "Supports the worker's declaration", SUPPORTS_FACILITY: "Supports the facility's record",
  BOTH_AGREE: "Agrees with both records", INCONCLUSIVE: "Disagrees with both records", NOT_DISPUTED: "Not disputed",
};
