"use client";

import { useEffect, useState, type ReactNode } from "react";
import { getToken } from "@/lib/auth";

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export function AuthGuard({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(!AUTH_ENABLED);

  useEffect(() => {
    if (!AUTH_ENABLED) return;
    if (!getToken()) {
      window.location.replace("/login");
      return;
    }
    setReady(true);
  }, []);

  if (!ready) return null;
  return children;
}
