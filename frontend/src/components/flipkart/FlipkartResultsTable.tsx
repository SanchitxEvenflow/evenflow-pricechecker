import { Badge } from "@/components/shared/Badge";
import type { FlipkartScrapeResult, ThemeClasses } from "@/types/price-scraper";

export function FlipkartResultsTable({ t, results, onDownloadCSV }: { t: ThemeClasses; results: FlipkartScrapeResult[]; onDownloadCSV: () => void }) {
  if (results.length === 0) return null;
  return (
    <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
      <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
        <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Scrape Results</p>
        <button onClick={onDownloadCSV} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all flex items-center gap-2`}>
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
          Download CSV
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className={`border-b ${t.border} ${t.thead}`}>
              {["FSN", "Title", "Status", "Price", "Rating", "Rating Count", "Fulfilled By", "URL"].map(h => (
                <th key={h} className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className={`divide-y ${t.border}`}>
            {results.map(r => (
              <tr key={r.fsn} className="transition-colors">
                <td className="px-4 py-4 whitespace-nowrap text-sm font-medium font-mono">{r.fsn}</td>
                <td className="px-4 py-4 whitespace-nowrap text-sm truncate max-w-[200px]" title={r.title || ""}>{r.title || "—"}</td>
                <td className="px-4 py-4 whitespace-nowrap text-sm"><Badge status={r.status} /></td>
                <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.price || "—"}</td>
                <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rating ? `${r.rating} ★` : "—"}</td>
                <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rating_count || "—"}</td>
                <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.fulfilled_by || "—"}</td>
                <td className={`px-4 py-4 whitespace-nowrap text-sm`}>
                  {r.url ? <a href={r.url} target="_blank" rel="noopener noreferrer" className="text-[#2874F0] hover:underline truncate block max-w-[200px]">View ↗</a> : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
