import { Badge } from "@/components/shared/Badge";
import type { LogEntry, ThemeClasses } from "@/types/price-scraper";

export function RunHistoryTable({ t, logs, onRefresh, formatDate }: { t: ThemeClasses; logs: LogEntry[]; onRefresh: () => void; formatDate: (iso: string) => string }) {
  return (
    <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
      <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
        <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Run History</p>
        <button onClick={onRefresh} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all`}>Refresh</button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className={`border-b ${t.border} ${t.thead}`}>
              {["Type", "Triggered At", "Total", "Success", "Failed", "Sheet Tab", "Status"].map(h => (
                <th key={h} className={`px-6 py-3 text-xs font-semibold ${t.muted} uppercase tracking-wider`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className={`divide-y ${t.border}`}>
            {logs.length === 0 ? (
              <tr><td colSpan={7} className={`px-6 py-8 text-center text-sm ${t.muted}`}>No runs logged yet</td></tr>
            ) : logs.map(log => (
              <tr key={log.run_id} className="transition-colors">
                <td className="px-6 py-3 whitespace-nowrap text-sm">
                  <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                    log.type === "manual" ? "bg-purple-500/10 text-purple-500" :
                    log.type === "blinkit_manual" ? "bg-yellow-500/10 text-yellow-500" :
                    log.type === "zepto_manual" ? "bg-pink-500/10 text-pink-500" :
                    log.type === "flipkart_manual" ? "bg-blue-500/10 text-blue-500" :
                    "bg-cyan-500/10 text-cyan-500"
                  }`}>
                    {log.type === "manual" ? "Amazon" : log.type === "blinkit_manual" ? "Blinkit" : log.type === "zepto_manual" ? "Zepto" : log.type === "flipkart_manual" ? "Flipkart" : "Auto"}
                  </span>
                </td>
                <td className={`px-6 py-3 whitespace-nowrap text-sm ${t.muted}`}>{formatDate(log.triggered_at)}</td>
                <td className="px-6 py-3 whitespace-nowrap text-sm font-medium">{log.total_asins}</td>
                <td className="px-6 py-3 whitespace-nowrap text-sm text-green-500">{log.success_count}</td>
                <td className="px-6 py-3 whitespace-nowrap text-sm text-red-500">{log.failed_count}</td>
                <td className={`px-6 py-3 whitespace-nowrap text-sm font-mono text-xs ${t.muted}`}>{log.sheet_tab || "—"}</td>
                <td className="px-6 py-3 whitespace-nowrap text-sm"><Badge status={log.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
