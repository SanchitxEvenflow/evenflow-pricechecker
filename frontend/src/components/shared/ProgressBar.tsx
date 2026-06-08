import type { ThemeClasses } from "@/types/price-scraper";

export function ProgressBar({
  dark,
  t,
  processed,
  total,
  colorClass,
  heightClass = "h-2",
  durationClass = "duration-300",
}: {
  dark: boolean;
  t: ThemeClasses;
  processed: number;
  total: number;
  colorClass: string;
  heightClass?: string;
  durationClass?: string;
}) {
  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
      <div className="flex justify-between text-xs mb-2">
        <span className={t.muted}>Progress</span>
        <span className="text-blue-500 font-medium">{processed} / {total}</span>
      </div>
      <div className={`${heightClass} rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
        <div className={`h-full ${colorClass} rounded-full transition-all ${durationClass}`} style={{ width: `${Math.round((processed / total) * 100)}%` }} />
      </div>
    </div>
  );
}
