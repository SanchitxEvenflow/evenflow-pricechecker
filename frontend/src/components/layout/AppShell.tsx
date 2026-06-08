import type { ReactNode } from "react";
import type { ThemeClasses } from "@/types/price-scraper";

export function AppShell({ t, children }: { dark: boolean; t: ThemeClasses; children: ReactNode }) {
  return <div className={`min-h-screen transition-colors duration-300 font-sans ${t.bg} ${t.text}`}>{children}</div>;
}
