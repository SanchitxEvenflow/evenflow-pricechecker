"use client";
import { useState, useEffect, useCallback } from "react";
import Image from "next/image";

const API = "";

// ─── Types ──────────────────────────────────────────────────────────────────
interface ScrapeResult {
  asin: string; price?: string; rating?: string; rating_count?: string;
  status: string; progress?: number; total?: number; done?: boolean;
}
interface LogEntry {
  run_id: string; type: string; triggered_at: string; completed_at: string | null;
  total_asins: number; success_count: number; failed_count: number;
  sheet_tab: string | null; status: string; error?: string;
}
interface CronStatus {
  is_running: boolean; last_run_at: string | null; last_run_tab: string | null;
  last_run_duration_seconds: number | null; last_run_processed: number | null;
  total: number | null; progress: number | null; next_run_at: string | null;
  scheduler_enabled?: boolean; error?: string | null;
}

// ─── Theme hook ─────────────────────────────────────────────────────────────
function useTheme() {
  const [dark, setDark] = useState(true);
  const t = {
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

// ─── Spinner SVG ────────────────────────────────────────────────────────────
const Spin = () => (
  <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
  </svg>
);

// ─── Status Badge ───────────────────────────────────────────────────────────
function Badge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: "bg-green-500/10 text-green-500", available: "bg-green-500/10 text-green-500",
    price_found: "bg-green-500/10 text-green-500", processing: "bg-blue-500/10 text-blue-500",
    pending: "bg-neutral-500/10 text-neutral-400", in_progress: "bg-blue-500/10 text-blue-500",
    completed: "bg-green-500/10 text-green-500", error: "bg-red-500/10 text-red-500",
    failed: "bg-red-500/10 text-red-500", not_found: "bg-red-500/10 text-red-500",
    blocked: "bg-orange-500/10 text-orange-500", invalid_format: "bg-yellow-500/10 text-yellow-500",
    unavailable: "bg-neutral-500/10 text-neutral-400",
  };
  const c = colors[status] || "bg-neutral-500/10 text-neutral-400";
  return <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold capitalize ${c}`}>{status.replace("_", " ")}</span>;
}

// ═══════════════════════════════════════════════════════════════════════════
// HEADER
// ═══════════════════════════════════════════════════════════════════════════
function Header({ dark, setDark, t, page }: { dark: boolean; setDark: (v: boolean) => void; t: any; page: string }) {
  return (
    <header className="sticky top-0 z-20 border-b border-neutral-800 bg-neutral-950 text-neutral-100">
      <div className="max-w-6xl mx-auto px-6 py-4 flex justify-between items-center">
        <a href="#/" className="flex items-center space-x-3 hover:opacity-80 transition-opacity">
          <Image src="/logo.png" alt="Logo" width={90} height={45} className="rounded object-contain" unoptimized />
          <h1 className="text-xl font-bold tracking-tight text-neutral-100">Price Scraper</h1>
        </a>
        <div className="flex items-center gap-3">
          {page === "home" ? (
            <a href="#/scheduler" className="px-4 py-2 rounded-xl text-sm font-medium bg-[#FF9900] hover:bg-[#e88a00] text-black transition-all">
              Run Scheduler
            </a>
          ) : (
            <a href="#/" className="px-4 py-2 rounded-xl text-sm font-medium bg-neutral-800 hover:bg-neutral-700 text-white transition-all">
              ← Back
            </a>
          )}
          <button onClick={() => setDark(!dark)} className="p-2 rounded-full border border-neutral-800 hover:opacity-80 transition-opacity" aria-label="Toggle Theme">
            {dark ? (
              <svg className="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
            ) : (
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// HOME PAGE — Manual ASIN Scraping
// ═══════════════════════════════════════════════════════════════════════════
function HomePage({ t, dark }: { t: any; dark: boolean }) {
  const [asinText, setAsinText] = useState("");
  const [results, setResults] = useState<ScrapeResult[]>([]);
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, processed: 0, remaining: 0, success: 0, failed: 0 });

  const parseAsins = (text: string) => {
    const raw = text.split(/[\n,]+/).map(a => a.trim().toUpperCase()).filter(Boolean);
    const seen = new Set<string>();
    return raw.filter(a => { if (seen.has(a)) return false; seen.add(a); return true; });
  };

  const handleScrape = async () => {
    const asins = parseAsins(asinText);
    if (asins.length === 0) { setError("Please enter at least one ASIN"); return; }
    setError("");
    setIsScraping(true);
    setResults(asins.map(a => ({ asin: a, status: "pending" })));
    setStats({ total: asins.length, processed: 0, remaining: asins.length, success: 0, failed: 0 });

    try {
      const res = await fetch(`${API}/api/scrape-manual`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asins }),
      });
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No response stream");
      const decoder = new TextDecoder();
      let buffer = "";
      let suc = 0, fail = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = JSON.parse(line.slice(6));
          if (data.done) continue;

          const st = data.status || "error";
          if (["error", "not_found", "blocked", "invalid_format"].includes(st)) fail++; else suc++;

          setResults(prev => prev.map(r => r.asin === data.asin ? { ...r, ...data, status: st } : r));
          setStats({ total: asins.length, processed: suc + fail, remaining: asins.length - suc - fail, success: suc, failed: fail });
        }
      }
    } catch (e: any) {
      setError("Scrape failed: " + e.message);
    } finally {
      setIsScraping(false);
    }
  };

  return (
    <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-500 rounded-xl text-sm font-medium flex items-center">
          <svg className="w-5 h-5 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          {error}
        </div>
      )}

      {/* Manual ASIN Input */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#FF9900]">amazon</span> — Manual Scrape</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Paste ASINs below (one per line) to test scraping. Results stay in browser — no sheet writes.</p>
          </div>
        </div>
        <textarea
          value={asinText}
          onChange={e => setAsinText(e.target.value)}
          placeholder={"B0DSWQVWJQ\nB09G9FPHY6\nB08N5WRWNW"}
          rows={5}
          className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 focus:ring-[#FF9900]/50 resize-y ${t.input}`}
          disabled={isScraping}
        />
        <div className="flex items-center justify-between mt-4">
          <p className={`text-xs ${t.muted}`}>{parseAsins(asinText).length} unique ASIN(s) detected</p>
          <button
            onClick={handleScrape}
            disabled={isScraping || parseAsins(asinText).length === 0}
            className="bg-[#FF9900] hover:bg-[#e88a00] text-black px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isScraping ? <><Spin /> Scraping...</> : "Run Scraper"}
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats.total > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: "Total", value: stats.total, color: "" },
            { label: "Processed", value: stats.processed, color: "" },
            { label: "Remaining", value: stats.remaining, color: "text-yellow-500" },
            { label: "Success", value: stats.success, color: "text-green-500" },
            { label: "Failed", value: stats.failed, color: "text-red-500" },
          ].map(s => (
            <div key={s.label} className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
              <p className={`text-xs ${t.muted} font-semibold uppercase tracking-wider`}>{s.label}</p>
              <p className={`text-3xl font-bold mt-1 ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Progress Bar */}
      {isScraping && stats.total > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
          <div className="flex justify-between text-xs mb-2">
            <span className={t.muted}>Progress</span>
            <span className="text-blue-500 font-medium">{stats.processed} / {stats.total}</span>
          </div>
          <div className={`h-2 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
            <div className="h-full bg-[#FF9900] rounded-full transition-all duration-300" style={{ width: `${Math.round((stats.processed / stats.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {/* Results Table */}
      {results.length > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className={`border-b ${t.border} ${t.thead}`}>
                  {["ASIN", "Status", "Price", "Rating", "Rating Count"].map(h => (
                    <th key={h} className={`px-6 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={`divide-y ${t.border}`}>
                {results.map(r => (
                  <tr key={r.asin} className="transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium font-mono">{r.asin}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm"><Badge status={r.status} /></td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.price || "—"}</td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rating ? `${r.rating} ★` : "—"}</td>
                    <td className={`px-6 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rating_count || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </main>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// SCHEDULER PAGE
// ═══════════════════════════════════════════════════════════════════════════
function SchedulerPage({ t, dark }: { t: any; dark: boolean }) {
  const [cronStatus, setCronStatus] = useState<CronStatus | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [toast, setToast] = useState<{ type: string; msg: string } | null>(null);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/api/logs`);
      const data = await res.json();
      if (data.logs) setLogs(data.logs);
    } catch {}
  }, []);

  const fetchCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/cron-status`);
      if (res.ok) setCronStatus(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    fetchCron(); fetchLogs();
    const i1 = setInterval(fetchCron, 10000);
    const i2 = setInterval(fetchLogs, 30000);
    return () => { clearInterval(i1); clearInterval(i2); };
  }, [fetchCron, fetchLogs]);

  const handleTrigger = async () => {
    setIsTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/sheets/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger" });
      }
    } catch (e: any) {
      setToast({ type: "error", msg: e.message });
    } finally {
      setIsTriggering(false);
    }
  };

  const fmtDate = (iso: string) => new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

  return (
    <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
      {/* Toast */}
      {toast && (
        <div className={`p-4 border rounded-xl text-sm font-medium flex items-center justify-between ${toast.type === "success" ? "bg-green-500/10 border-green-500/30 text-green-500" : "bg-red-500/10 border-red-500/30 text-red-500"}`}>
          <span>{toast.msg}</span>
          <button onClick={() => setToast(null)} className="ml-4 hover:opacity-60">✕</button>
        </div>
      )}

      {/* Manual Trigger Card */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold">Manual Trigger</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Run a full scrape of all ASINs from the Google Sheet. Results are written to a new tab: <code className={`text-xs px-1.5 py-0.5 rounded ${dark ? "bg-neutral-800" : "bg-neutral-100"}`}>Manual_Trigger_YYYY-MM-DD_HH-MM</code></p>
          </div>
          <button
            onClick={handleTrigger}
            disabled={isTriggering || cronStatus?.is_running === true}
            className="bg-[#FF9900] hover:bg-[#e88a00] text-black px-8 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shrink-0"
          >
            {isTriggering ? <><Spin /> Starting...</> : cronStatus?.is_running ? "Scrape Running..." : "Manual Trigger"}
          </button>
        </div>

        {/* Progress */}
        {cronStatus?.is_running && cronStatus.progress != null && cronStatus.total != null && cronStatus.total > 0 && (
          <div className="mt-6">
            <div className="flex justify-between text-xs mb-2">
              <span className={t.muted}>Progress</span>
              <span className="text-blue-500 font-medium">{cronStatus.progress} / {cronStatus.total}</span>
            </div>
            <div className={`h-2.5 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
              <div className="h-full bg-[#FF9900] rounded-full transition-all duration-500" style={{ width: `${Math.round((cronStatus.progress / cronStatus.total) * 100)}%` }} />
            </div>
          </div>
        )}
      </div>

      {/* Cron Status */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-6 shadow-sm`}>
        <div className="flex items-center justify-between mb-3">
          <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Scheduler Status</p>
          <Badge status={cronStatus?.scheduler_enabled === false ? "disabled" : cronStatus?.is_running ? "in_progress" : "completed"} />
        </div>
        {cronStatus && (
          <div className="space-y-2 text-sm">
            {cronStatus.last_run_tab && <div className="flex justify-between"><span className={t.muted}>Last tab</span><span className="font-mono text-xs">{cronStatus.last_run_tab}</span></div>}
            {cronStatus.last_run_at && <div className="flex justify-between"><span className={t.muted}>Started</span><span>{fmtDate(cronStatus.last_run_at)}</span></div>}
            {cronStatus.last_run_duration_seconds != null && <div className="flex justify-between"><span className={t.muted}>Duration</span><span>{Math.floor(cronStatus.last_run_duration_seconds / 60)}m {cronStatus.last_run_duration_seconds % 60}s</span></div>}
            {cronStatus.next_run_at && <div className="flex justify-between"><span className={t.muted}>Next run</span><span>{fmtDate(cronStatus.next_run_at)}</span></div>}
          </div>
        )}
      </div>

      {/* Logs */}
      <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
        <div className="flex items-center justify-between px-6 py-4 border-b ${t.border}">
          <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Run History</p>
          <button onClick={fetchLogs} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all`}>Refresh</button>
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
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${log.type === "manual" ? "bg-purple-500/10 text-purple-500" : "bg-blue-500/10 text-blue-500"}`}>
                      {log.type === "manual" ? "Manual" : "Auto"}
                    </span>
                  </td>
                  <td className={`px-6 py-3 whitespace-nowrap text-sm ${t.muted}`}>{fmtDate(log.triggered_at)}</td>
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
    </main>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// ROOT — Hash Router
// ═══════════════════════════════════════════════════════════════════════════
export default function App() {
  const { dark, setDark, t } = useTheme();
  const [page, setPage] = useState("home");

  useEffect(() => {
    const onHash = () => setPage(window.location.hash === "#/scheduler" ? "scheduler" : "home");
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className={`min-h-screen transition-colors duration-300 font-sans ${t.bg} ${t.text}`}>
      <Header dark={dark} setDark={setDark} t={t} page={page} />
      {page === "scheduler" ? <SchedulerPage t={t} dark={dark} /> : <HomePage t={t} dark={dark} />}
    </div>
  );
}
