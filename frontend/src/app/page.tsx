"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { session } from "@/lib/api";
import { HOME } from "@/lib/hooks";

export default function Index() {
  const router = useRouter();
  useEffect(() => {
    const u = session.user();
    router.replace(u ? HOME[u.role] : "/login");
  }, [router]);
  return null;
}
