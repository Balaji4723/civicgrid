"use client";
import type { TicketStatus } from "@/lib/types";
import { Badge, type Tone } from "./ui";

export const ticketTone: Record<TicketStatus, Tone> = { SUBMITTED: "neutral", ROUTED: "proc", IN_PROGRESS: "track", RESOLVED: "ok", UNROUTABLE: "flag" };

/** UNROUTABLE is shown as "manual triage": the ticket is not lost, a person has to place it. */
export const TicketBadge = ({ s }: { s: TicketStatus }) => <Badge tone={ticketTone[s]}>{s === "UNROUTABLE" ? "MANUAL TRIAGE" : s.replace("_", " ")}</Badge>;
