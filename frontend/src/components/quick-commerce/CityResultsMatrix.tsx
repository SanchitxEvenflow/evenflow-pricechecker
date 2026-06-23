import type { CityResult, CityScrapeConfig, ThemeClasses } from "@/types/price-scraper";

export function CityResultsMatrix<T extends CityResult>({ t, results, orderedIds, config, onDownloadCSV, sheetProducts = [] }: {
  t: ThemeClasses;
  results: Record<string, Record<string, T>>;
  orderedIds?: string[];
  config: CityScrapeConfig<T>;
  onDownloadCSV: () => void;
  sheetProducts?: import("@/components/shared/ProductPicker").SheetProduct[];
}) {
  const pids = orderedIds && orderedIds.length > 0 ? orderedIds : Object.keys(results);
  if (pids.length === 0) return null;

  return (
    <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
      <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
        <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>{config.resultsTitle}</p>
        <button onClick={onDownloadCSV} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all flex items-center gap-2`}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
          Download CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse min-w-max">
          <thead>
            <tr className={`border-b ${t.border} ${t.thead}`}>
              <th className={`w-40 min-w-[160px] max-w-[160px] px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider sticky left-0 ${t.card} z-10 shadow-[1px_0_0_var(--tw-shadow-color)] shadow-neutral-800`}>Product ID</th>
              <th style={{ left: 160 }} className={`w-64 min-w-[256px] max-w-[256px] px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider sticky ${t.card} z-10 shadow-[1px_0_0_var(--tw-shadow-color)] shadow-neutral-800`}>Title</th>
              {config.cities.map(c => (
                <th key={c} className={`w-32 min-w-[128px] max-w-[128px] px-2 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider text-center`}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className={`divide-y ${t.border}`}>
            {pids.map(pid => {
              const firstResultWithTitle = Object.values(results[pid] || {}).find(r => r.title);
              const sheetTitle = sheetProducts?.find((x: any) => x.id === pid)?.title;
              const title = sheetTitle || firstResultWithTitle?.title || "—";
              return (
              <tr key={pid} className="transition-colors">
                <td className={`w-40 min-w-[160px] max-w-[160px] px-4 py-3 whitespace-normal break-all text-sm font-medium font-mono sticky left-0 ${t.card} z-10 align-top shadow-[1px_0_0_var(--tw-shadow-color)] shadow-neutral-800`}>{pid}</td>
                <td style={{ left: 160 }} className={`w-64 min-w-[256px] max-w-[256px] px-4 py-3 whitespace-normal break-words text-sm sticky ${t.card} z-10 align-top shadow-[1px_0_0_var(--tw-shadow-color)] shadow-neutral-800`} title={title}>{title}</td>
                {config.cities.map(city => {
                  const r = results[pid]?.[city];
                  if (!r) return <td key={city} className={`px-4 py-3 text-center text-xs ${t.muted}`}>—</td>;
                  return (
                    <td key={city} className="w-32 min-w-[128px] max-w-[128px] px-2 py-3 text-center align-top">
                      <span className={`inline-block px-2 py-1 rounded-lg text-xs font-semibold border ${config.statusColor(r.status)}`}>
                        {r.price != null ? `₹${r.price}` : config.getCellLabel(r)}
                      </span>
                      {r.mrp != null && r.price != null && r.mrp > r.price && (
                        <p className={`text-[10px] mt-0.5 line-through ${t.muted}`}>₹{r.mrp}</p>
                      )}
                    </td>
                  );
                })}
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
