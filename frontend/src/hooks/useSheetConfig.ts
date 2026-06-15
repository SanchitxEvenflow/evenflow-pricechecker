"use client";

import { useEffect, useState } from "react";
import { API, authFetch } from "@/lib/api";

export type SheetConfig = Record<string, string | null>;

let _cache: SheetConfig | null = null;

/**
 * Fetches /config once on mount and returns a map of platform → Google Sheet URL.
 * Results are cached in module scope so repeated mounts don't re-fetch.
 */
export function useSheetConfig() {
  const [sheets, setSheets] = useState<SheetConfig>(_cache ?? {});

  useEffect(() => {
    if (_cache) return; // already fetched
    authFetch(`${API}/config`)
      .then(r => r.json())
      .then((data: { sheets: SheetConfig }) => {
        _cache = data.sheets;
        setSheets(data.sheets);
      })
      .catch(() => {
        // Silently fail — sheet links are non-critical
      });
  }, []);

  return sheets;
}
