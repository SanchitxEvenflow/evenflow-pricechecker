"use client";

import { useState } from "react";
import type { ThemeClasses } from "@/types/price-scraper";

export function useTheme() {
  const [dark, setDark] = useState(true);
  const t: ThemeClasses = {
    bg: dark ? "bg-neutral-950" : "bg-gray-50",
    text: dark ? "text-neutral-100" : "text-neutral-900",
    card: dark ? "bg-neutral-900" : "bg-white",
    border: dark ? "border-neutral-800" : "border-neutral-200",
    muted: dark ? "text-neutral-400" : "text-neutral-500",
    thead: dark ? "bg-neutral-950/50" : "bg-neutral-100",
    headerBg: dark ? "bg-neutral-950/80" : "bg-white/80",
    input: dark ? "bg-neutral-800 border-neutral-700 text-white placeholder-neutral-500" : "bg-white border-neutral-300 text-neutral-900 placeholder-neutral-400",
    btnSecondary: dark ? "bg-neutral-800 hover:bg-neutral-700 text-white" : "bg-neutral-200 hover:bg-neutral-300 text-neutral-900",
  };
  return { dark, setDark, t };
}
