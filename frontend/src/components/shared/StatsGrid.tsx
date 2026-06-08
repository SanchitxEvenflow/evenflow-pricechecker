import type { ThemeClasses } from "@/types/price-scraper";

export function StatsGrid({ t, items, columnsClass }: { t: ThemeClasses; items: Array<{ label: string; value: number; color: string }>; columnsClass: string }) {
  return (
    <div className={`grid ${columnsClass} gap-4`}>
      {items.map(s => (
        <div key={s.label} className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
          <p className={`text-xs ${t.muted} font-semibold uppercase tracking-wider`}>{s.label}</p>
          <p className={`text-3xl font-bold mt-1 ${s.color}`}>{s.value}</p>
        </div>
      ))}
    </div>
  );
}
