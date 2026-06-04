"use client";
import { useState, useEffect, useCallback } from "react";
import Image from "next/image";

const API = process.env.NEXT_PUBLIC_API_URL || "";

// ─── Types ──────────────────────────────────────────────────────────────────
interface RatingBreakdown {
  "5_star"?: string | null; "4_star"?: string | null; "3_star"?: string | null;
  "2_star"?: string | null; "1_star"?: string | null;
}
interface ScrapeResult {
  asin: string; price?: string; rating?: string; rating_count?: string;
  rating_breakdown?: RatingBreakdown | null;
  parent_node?: string | null; rank_value?: string | null;
  child_node?: string | null; sub_rank_value?: string | null;
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
interface FlipkartScrapeResult {
  fsn: string; price?: string; mrp?: string; discount?: string;
  rating?: string; rating_count?: string; fulfilled_by?: string; status: string;
  url?: string; resolved_url?: string; checked_at?: string;
  progress?: number; total?: number; done?: boolean;
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
          <a href="#/" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "home" ? "bg-[#FF9900] text-black" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Amazon
          </a>
          <a href="#/flipkart" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "flipkart" ? "bg-[#2874F0] text-white" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Flipkart
          </a>
          <a href="#/blinkit" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "blinkit" ? "bg-[#F8CB46] text-black" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Blinkit
          </a>
          <a href="#/zepto" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "zepto" ? "bg-[#FF3269] text-white" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Zepto
          </a>
          <a href="#/scheduler" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "scheduler" ? "bg-[#FF9900] text-black" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Scheduler
          </a>
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
      const res = await fetch(`${API}/api/amazon/scrape-manual`, {
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

  const downloadCSV = () => {
    if (results.length === 0) return;

    const headers = [
      "ASIN", "Status", "Price", "Rating", "Rating Count", "Rating Breakdown",
      "Parent Node", "Parent Rank", "Child Node", "Child Rank", "URL"
    ];

    const rows = results.map(r => {
      const bd = r.rating_breakdown;
      const bdStr = bd
        ? ["5_star","4_star","3_star","2_star","1_star"]
            .map(k => bd[k as keyof RatingBreakdown] ? `${k[0]}★:${bd[k as keyof RatingBreakdown]}` : null)
            .filter(Boolean).join(" ")
        : "";

      const row = [
        r.asin,
        r.status,
        r.price || "",
        r.rating ? `${r.rating} ★` : "",
        r.rating_count || "",
        bdStr,
        r.parent_node || "",
        r.rank_value ? `#${r.rank_value}` : "",
        r.child_node || "",
        r.sub_rank_value ? `#${r.sub_rank_value}` : "",
        `https://www.amazon.in/dp/${r.asin}`
      ];

      return row.map(field => `"${String(field).replace(/"/g, '""')}"`).join(",");
    });

    const csvContent = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `manual_scrape_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
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
          <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
            <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Scrape Results</p>
            <button onClick={downloadCSV} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all flex items-center gap-2`}>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
              Download CSV
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className={`border-b ${t.border} ${t.thead}`}>
                  {["ASIN", "Status", "Price", "Rating", "Rating Count", "Rating Breakdown", "Parent Node", "Parent Rank", "Child Node", "Child Rank", "URL"].map(h => (
                    <th key={h} className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={`divide-y ${t.border}`}>
                {results.map(r => {
                  const bd = r.rating_breakdown;
                  const bdStr = bd
                    ? ["5_star","4_star","3_star","2_star","1_star"]
                        .map(k => bd[k as keyof RatingBreakdown] ? `${k[0]}★:${bd[k as keyof RatingBreakdown]}` : null)
                        .filter(Boolean).join(" ")
                    : null;
                  return (
                    <tr key={r.asin} className="transition-colors">
                      <td className="px-4 py-4 whitespace-nowrap text-sm font-medium font-mono">{r.asin}</td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm"><Badge status={r.status} /></td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.price || "—"}</td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rating ? `${r.rating} ★` : "—"}</td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rating_count || "—"}</td>
                      <td className={`px-4 py-4 text-xs ${t.muted} font-mono`}>{bdStr || "—"}</td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.parent_node || "—"}</td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.rank_value ? `#${r.rank_value}` : "—"}</td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.child_node || "—"}</td>
                      <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.sub_rank_value ? `#${r.sub_rank_value}` : "—"}</td>
                      <td className="px-4 py-4 whitespace-nowrap text-sm">
                        <a href={`https://www.amazon.in/dp/${r.asin}`} target="_blank" rel="noopener noreferrer" className="text-[#FF9900] hover:underline flex items-center gap-1">
                          View <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                        </a>
                      </td>
                    </tr>
                  );
                })}
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
  const [blinkitStatus, setBlinkitStatus] = useState<CronStatus | null>(null);
  const [flipkartStatus, setFlipkartStatus] = useState<CronStatus | null>(null);
  const [zeptoStatus, setZeptoStatus] = useState<CronStatus | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [isBlinkitTriggering, setIsBlinkitTriggering] = useState(false);
  const [isFlipkartTriggering, setIsFlipkartTriggering] = useState(false);
  const [isZeptoTriggering, setIsZeptoTriggering] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [toast, setToast] = useState<{ type: string; msg: string } | null>(null);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/amazon/api/logs`);
      const data = await res.json();
      if (data.logs) setLogs(data.logs);
    } catch {}
  }, []);

  const fetchCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/amazon/cron-status`);
      if (res.ok) setCronStatus(await res.json());
    } catch {}
  }, []);

  const fetchBlinkitCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/price/blinkit/cron-status`);
      if (res.ok) setBlinkitStatus(await res.json());
    } catch {}
  }, []);

  const fetchFlipkartCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/flipkart/cron-status`);
      if (res.ok) setFlipkartStatus(await res.json());
    } catch {}
  }, []);

  const fetchZeptoCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/price/zepto/cron-status`);
      if (res.ok) setZeptoStatus(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    fetchCron(); fetchBlinkitCron(); fetchFlipkartCron(); fetchZeptoCron(); fetchLogs();
    const i1 = setInterval(fetchCron, 10000);
    const i2 = setInterval(fetchLogs, 30000);
    const i3 = setInterval(fetchBlinkitCron, 10000);
    const i4 = setInterval(fetchFlipkartCron, 10000);
    const i5 = setInterval(fetchZeptoCron, 10000);
    return () => { clearInterval(i1); clearInterval(i2); clearInterval(i3); clearInterval(i4); clearInterval(i5); };
  }, [fetchCron, fetchBlinkitCron, fetchFlipkartCron, fetchZeptoCron, fetchLogs]);

  const handleTrigger = async () => {
    setIsTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/sheets/amazon/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Amazon manual scrape triggered! Check progress below." });
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

  const handleBlinkitTrigger = async () => {
    setIsBlinkitTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/price/blinkit/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Blinkit manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger Blinkit scrape" });
      }
    } catch (e: any) {
      setToast({ type: "error", msg: e.message });
    } finally {
      setIsBlinkitTriggering(false);
    }
  };

  const handleFlipkartTrigger = async () => {
    setIsFlipkartTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/sheets/flipkart/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Flipkart manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger Flipkart scrape" });
      }
    } catch (e: any) {
      setToast({ type: "error", msg: e.message });
    } finally {
      setIsFlipkartTriggering(false);
    }
  };

  const handleZeptoTrigger = async () => {
    setIsZeptoTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/price/zepto/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Zepto manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger Zepto scrape" });
      }
    } catch (e: any) {
      setToast({ type: "error", msg: e.message });
    } finally {
      setIsZeptoTriggering(false);
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

      {/* Amazon Manual Trigger Card */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#FF9900]">amazon</span> — Manual Trigger</h2>
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

      {/* Blinkit Manual Trigger Card */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#F8CB46]">blinkit</span> — Manual Trigger</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Run a full scrape of all PIDs from the Blinkit Google Sheet across all 10 cities. Results are written to a new tab: <code className={`text-xs px-1.5 py-0.5 rounded ${dark ? "bg-neutral-800" : "bg-neutral-100"}`}>Blinkit_Manual_YYYY-MM-DD_HH-MM</code></p>
          </div>
          <button
            onClick={handleBlinkitTrigger}
            disabled={isBlinkitTriggering || blinkitStatus?.is_running === true}
            className="bg-[#F8CB46] hover:bg-[#e5b93d] text-black px-8 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shrink-0"
          >
            {isBlinkitTriggering ? <><Spin /> Starting...</> : blinkitStatus?.is_running ? "Scrape Running..." : "Manual Trigger"}
          </button>
        </div>

        {/* Blinkit Progress */}
        {blinkitStatus?.is_running && blinkitStatus.progress != null && blinkitStatus.total != null && blinkitStatus.total > 0 && (
          <div className="mt-6">
            <div className="flex justify-between text-xs mb-2">
              <span className={t.muted}>Progress</span>
              <span className="text-blue-500 font-medium">{blinkitStatus.progress} / {blinkitStatus.total}</span>
            </div>
            <div className={`h-2.5 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
              <div className="h-full bg-[#F8CB46] rounded-full transition-all duration-500" style={{ width: `${Math.round((blinkitStatus.progress / blinkitStatus.total) * 100)}%` }} />
            </div>
          </div>
        )}
      </div>

      {/* Flipkart Manual Trigger Card */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#2874F0]">flipkart</span> — Manual Trigger</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Run a full scrape of all FSNs from the Flipkart Google Sheet. Results are written to a new tab: <code className={`text-xs px-1.5 py-0.5 rounded ${dark ? "bg-neutral-800" : "bg-neutral-100"}`}>Flipkart_Manual_YYYY-MM-DD_HH-MM</code></p>
          </div>
          <button
            onClick={handleFlipkartTrigger}
            disabled={isFlipkartTriggering || flipkartStatus?.is_running === true}
            className="bg-[#2874F0] hover:bg-[#1a5dc8] text-white px-8 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shrink-0"
          >
            {isFlipkartTriggering ? <><Spin /> Starting...</> : flipkartStatus?.is_running ? "Scrape Running..." : "Manual Trigger"}
          </button>
        </div>

        {/* Flipkart Progress */}
        {flipkartStatus?.is_running && flipkartStatus.progress != null && flipkartStatus.total != null && flipkartStatus.total > 0 && (
          <div className="mt-6">
            <div className="flex justify-between text-xs mb-2">
              <span className={t.muted}>Progress</span>
              <span className="text-blue-500 font-medium">{flipkartStatus.progress} / {flipkartStatus.total}</span>
            </div>
            <div className={`h-2.5 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
              <div className="h-full bg-[#2874F0] rounded-full transition-all duration-500" style={{ width: `${Math.round((flipkartStatus.progress / flipkartStatus.total) * 100)}%` }} />
            </div>
          </div>
        )}
      </div>

      {/* Zepto Manual Trigger Card */}
      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#FF3269]">zepto</span> — Manual Trigger</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Run a full scrape of all PIDs from the Zepto Google Sheet across all 9 cities. Results are written to a new tab: <code className={`text-xs px-1.5 py-0.5 rounded ${dark ? "bg-neutral-800" : "bg-neutral-100"}`}>Zepto_Manual_YYYY-MM-DD_HH-MM</code></p>
          </div>
          <button
            onClick={handleZeptoTrigger}
            disabled={isZeptoTriggering || zeptoStatus?.is_running === true}
            className="bg-[#FF3269] hover:bg-[#e02b5c] text-white px-8 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 shrink-0"
          >
            {isZeptoTriggering ? <><Spin /> Starting...</> : zeptoStatus?.is_running ? "Scrape Running..." : "Manual Trigger"}
          </button>
        </div>

        {/* Zepto Progress */}
        {zeptoStatus?.is_running && zeptoStatus.progress != null && zeptoStatus.total != null && zeptoStatus.total > 0 && (
          <div className="mt-6">
            <div className="flex justify-between text-xs mb-2">
              <span className={t.muted}>Progress</span>
              <span className="text-blue-500 font-medium">{zeptoStatus.progress} / {zeptoStatus.total}</span>
            </div>
            <div className={`h-2.5 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
              <div className="h-full bg-[#FF3269] rounded-full transition-all duration-500" style={{ width: `${Math.round((zeptoStatus.progress / zeptoStatus.total) * 100)}%` }} />
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
                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                      log.type === "manual" ? "bg-purple-500/10 text-purple-500" :
                      log.type === "blinkit_manual" ? "bg-yellow-500/10 text-yellow-500" :
                      log.type === "flipkart_manual" ? "bg-blue-500/10 text-blue-400" :
                      "bg-blue-500/10 text-blue-500"
                    }`}>
                      {log.type === "manual" ? "Amazon" : log.type === "blinkit_manual" ? "Blinkit" : log.type === "flipkart_manual" ? "Flipkart" : log.type === "zepto_manual" ? "Zepto" : "Auto"}
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
// BLINKIT PAGE
// ═══════════════════════════════════════════════════════════════════════════
const BLINKIT_CITIES = ["Bangalore","NCR","Mumbai","Hyderabad","Kolkata","Pune","Ahmedabad","Chennai","Patna","Dehradun"];

interface BlinkitResult { product_id: string; city: string; title?: string|null; price?: number|null; mrp?: number|null; status: string; is_sold_out?: boolean; url?: string; checked_at?: string; }

function BlinkitPage({ t, dark }: { t: any; dark: boolean }) {
  const [idText, setIdText] = useState("");
  const [results, setResults] = useState<Record<string, Record<string, BlinkitResult>>>({});
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, done: 0, success: 0, failed: 0 });

  const parseIds = (text: string) => [...new Set(text.split(/[\n,]+/).map(a => a.trim()).filter(Boolean))];

  const handleScrape = async () => {
    const ids = parseIds(idText);
    if (!ids.length) { setError("Enter at least one product ID"); return; }
    setError(""); setIsScraping(true);
    setResults({}); setStats({ total: ids.length * BLINKIT_CITIES.length, done: 0, success: 0, failed: 0 });

    try {
      const res = await fetch(`${API}/price/blinkit/all-cities`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_ids: ids }),
      });
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No stream");
      const decoder = new TextDecoder();
      let buffer = "", suc = 0, fail = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n"); buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const d = JSON.parse(line.slice(6));
          if (d.done) continue;
          if (d.status === "error") fail++; else suc++;
          setResults(prev => {
            const next = { ...prev };
            if (!next[d.product_id]) next[d.product_id] = {};
            next[d.product_id] = { ...next[d.product_id], [d.city]: d };
            return next;
          });
          setStats({ total: ids.length * BLINKIT_CITIES.length, done: suc + fail, success: suc, failed: fail });
        }
      }
    } catch (e: any) { setError("Scrape failed: " + e.message); }
    finally { setIsScraping(false); }
  };

  const downloadCSV = () => {
    const pids = Object.keys(results);
    if (!pids.length) return;
    const hdr = ["Product ID", ...BLINKIT_CITIES.flatMap(c => [`${c} Price`, `${c} MRP`, `${c} Status`])];
    const rows = pids.map(pid => {
      const cells = [pid];
      BLINKIT_CITIES.forEach(c => {
        const r = results[pid]?.[c];
        cells.push(r?.price != null ? String(r.price) : "", r?.mrp != null ? String(r.mrp) : "", r?.status || "");
      });
      return cells.map(f => `"${String(f).replace(/"/g, '""')}"`).join(",");
    });
    const blob = new Blob([[hdr.join(","), ...rows].join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `blinkit_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  const statusColor = (s: string) => {
    if (s === "available") return "bg-green-500/15 text-green-400 border-green-500/30";
    if (s === "out_of_stock") return "bg-red-500/15 text-red-400 border-red-500/30";
    if (s === "unserviceable") return "bg-neutral-500/15 text-neutral-400 border-neutral-500/30";
    return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  };

  const pids = Object.keys(results);

  return (
    <main className="max-w-[95vw] mx-auto px-6 py-8 space-y-8">
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-500 rounded-xl text-sm font-medium flex items-center">
          <svg className="w-5 h-5 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          {error}
        </div>
      )}

      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#F8CB46]">blinkit</span> — All Cities Scrape</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Paste Blinkit product IDs (one per line). Scrapes all 10 cities concurrently.</p>
          </div>
        </div>
        <textarea value={idText} onChange={e => setIdText(e.target.value)} placeholder={"12345\n67890"} rows={4}
          className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 focus:ring-[#F8CB46]/50 resize-y ${t.input}`} disabled={isScraping} />
        <div className="flex items-center justify-between mt-4">
          <p className={`text-xs ${t.muted}`}>{parseIds(idText).length} product ID(s) × 10 cities = {parseIds(idText).length * 10} requests</p>
          <button onClick={handleScrape} disabled={isScraping || !parseIds(idText).length}
            className="bg-[#F8CB46] hover:bg-[#e5b93d] text-black px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
            {isScraping ? <><Spin /> Scraping...</> : "Scrape All Cities"}
          </button>
        </div>
      </div>

      {stats.total > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Total", value: stats.total, color: "" },
            { label: "Done", value: stats.done, color: "" },
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

      {isScraping && stats.total > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
          <div className="flex justify-between text-xs mb-2">
            <span className={t.muted}>Progress</span>
            <span className="text-blue-500 font-medium">{stats.done} / {stats.total}</span>
          </div>
          <div className={`h-2 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
            <div className="h-full bg-[#F8CB46] rounded-full transition-all duration-300" style={{ width: `${Math.round((stats.done / stats.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {pids.length > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
          <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
            <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Results — {BLINKIT_CITIES.length} Cities</p>
            <button onClick={downloadCSV} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all flex items-center gap-2`}>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
              Download CSV
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className={`border-b ${t.border} ${t.thead}`}>
                  <th className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider sticky left-0 ${t.card} z-10`}>Product ID</th>
                  {BLINKIT_CITIES.map(c => (
                    <th key={c} className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider text-center`}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={`divide-y ${t.border}`}>
                {pids.map(pid => (
                  <tr key={pid} className="transition-colors">
                    <td className={`px-4 py-3 whitespace-nowrap text-sm font-medium font-mono sticky left-0 ${t.card} z-10`}>{pid}</td>
                    {BLINKIT_CITIES.map(city => {
                      const r = results[pid]?.[city];
                      if (!r) return <td key={city} className={`px-4 py-3 text-center text-xs ${t.muted}`}>—</td>;
                      return (
                        <td key={city} className="px-3 py-3 text-center">
                          <span className={`inline-block px-2 py-1 rounded-lg text-xs font-semibold border ${statusColor(r.status)}`}>
                            {r.price != null ? `₹${r.price}` : r.status.replace("_", " ")}
                          </span>
                          {r.mrp != null && r.price != null && r.mrp > r.price && (
                            <p className={`text-[10px] mt-0.5 line-through ${t.muted}`}>₹{r.mrp}</p>
                          )}
                        </td>
                      );
                    })}
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
// ZEPTO PAGE
// ═══════════════════════════════════════════════════════════════════════════
const ZEPTO_CITIES = ["Bangalore","NCR","Mumbai","Hyderabad","Kolkata","Pune","Ahmedabad","Chennai","Dehradun"];

interface ZeptoResult { product_id: string; city: string; title?: string|null; price?: number|null; mrp?: number|null; status: string; is_sold_out?: boolean; url?: string; checked_at?: string; }

function ZeptoPage({ t, dark }: { t: any; dark: boolean }) {
  const [idText, setIdText] = useState("");
  const [results, setResults] = useState<Record<string, Record<string, ZeptoResult>>>({});
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, done: 0, success: 0, failed: 0 });

  const parseIds = (text: string) => [...new Set(text.split(/[\n,]+/).map(a => a.trim()).filter(Boolean))];

  const handleScrape = async () => {
    const ids = parseIds(idText);
    if (!ids.length) { setError("Enter at least one product ID"); return; }
    setError(""); setIsScraping(true);
    setResults({}); setStats({ total: ids.length * ZEPTO_CITIES.length, done: 0, success: 0, failed: 0 });

    try {
      const res = await fetch(`${API}/price/zepto/all-cities`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_ids: ids }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}: ${res.statusText}`);
      const reader = res.body?.getReader();
      if (!reader) throw new Error("No stream");
      const decoder = new TextDecoder();
      let buffer = "", suc = 0, fail = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n"); buffer = lines.pop() || "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const d = JSON.parse(line.slice(6));
          if (d.done) continue;
          if (d.status === "error") fail++; else suc++;
          setResults(prev => {
            const next = { ...prev };
            if (!next[d.product_id]) next[d.product_id] = {};
            next[d.product_id] = { ...next[d.product_id], [d.city]: d };
            return next;
          });
          setStats({ total: ids.length * ZEPTO_CITIES.length, done: suc + fail, success: suc, failed: fail });
        }
      }
    } catch (e: any) { setError("Scrape failed: " + e.message); }
    finally { setIsScraping(false); }
  };

  const downloadCSV = () => {
    const pids = Object.keys(results);
    if (!pids.length) return;
    const hdr = ["Product ID", ...ZEPTO_CITIES.flatMap(c => [`${c} Price`, `${c} MRP`, `${c} Status`])];
    const rows = pids.map(pid => {
      const cells = [pid];
      ZEPTO_CITIES.forEach(c => {
        const r = results[pid]?.[c];
        cells.push(r?.price != null ? String(r.price) : "", r?.mrp != null ? String(r.mrp) : "", r?.status || "");
      });
      return cells.map(f => `"${String(f).replace(/"/g, '""')}"`).join(",");
    });
    const blob = new Blob([[hdr.join(","), ...rows].join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `zepto_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  const statusColor = (s: string) => {
    if (s === "available") return "bg-green-500/15 text-green-400 border-green-500/30";
    if (s === "out_of_stock") return "bg-red-500/15 text-red-400 border-red-500/30";
    if (s === "unserviceable" || s === "not_found") return "bg-neutral-500/15 text-neutral-400 border-neutral-500/30";
    return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  };

  const pids = Object.keys(results);

  return (
    <main className="max-w-[95vw] mx-auto px-6 py-8 space-y-8">
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-500 rounded-xl text-sm font-medium flex items-center">
          <svg className="w-5 h-5 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          {error}
        </div>
      )}

      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#FF3269]">zepto</span> — All Cities Scrape</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Paste Zepto product IDs (one per line). Scrapes all 10 cities concurrently.</p>
          </div>
        </div>
        <textarea value={idText} onChange={e => setIdText(e.target.value)} placeholder={"c834d3ca-...\n4f54ea62-..."} rows={4}
          className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 focus:ring-[#FF3269]/50 resize-y ${t.input}`} disabled={isScraping} />
        <div className="flex items-center justify-between mt-4">
          <p className={`text-xs ${t.muted}`}>{parseIds(idText).length} product ID(s) × 10 cities = {parseIds(idText).length * 10} requests</p>
          <button onClick={handleScrape} disabled={isScraping || !parseIds(idText).length}
            className="bg-[#FF3269] hover:bg-[#e02b5c] text-white px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2">
            {isScraping ? <><Spin /> Scraping...</> : "Scrape All Cities"}
          </button>
        </div>
      </div>

      {stats.total > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Total", value: stats.total, color: "" },
            { label: "Done", value: stats.done, color: "" },
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

      {isScraping && stats.total > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
          <div className="flex justify-between text-xs mb-2">
            <span className={t.muted}>Progress</span>
            <span className="text-blue-500 font-medium">{stats.done} / {stats.total}</span>
          </div>
          <div className={`h-2 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
            <div className="h-full bg-[#FF3269] rounded-full transition-all duration-300" style={{ width: `${Math.round((stats.done / stats.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {pids.length > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
          <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
            <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Results — {ZEPTO_CITIES.length} Cities</p>
            <button onClick={downloadCSV} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all flex items-center gap-2`}>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
              Download CSV
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className={`border-b ${t.border} ${t.thead}`}>
                  <th className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider sticky left-0 ${t.card} z-10`}>Product ID</th>
                  {ZEPTO_CITIES.map(c => (
                    <th key={c} className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider text-center`}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={`divide-y ${t.border}`}>
                {pids.map(pid => (
                  <tr key={pid} className="transition-colors">
                    <td className={`px-4 py-3 whitespace-nowrap text-sm font-medium font-mono sticky left-0 ${t.card} z-10`}>{pid}</td>
                    {ZEPTO_CITIES.map(city => {
                      const r = results[pid]?.[city];
                      if (!r) return <td key={city} className={`px-4 py-3 text-center text-xs ${t.muted}`}>—</td>;
                      return (
                        <td key={city} className="px-3 py-3 text-center">
                          <span className={`inline-block px-2 py-1 rounded-lg text-xs font-semibold border ${statusColor(r.status)}`}>
                            {r.price != null ? `₹${r.price}` : (r.error_message || r.status).replace(/_/g, " ")}
                          </span>
                          {r.mrp != null && r.price != null && r.mrp > r.price && (
                            <p className={`text-[10px] mt-0.5 line-through ${t.muted}`}>₹{r.mrp}</p>
                          )}
                        </td>
                      );
                    })}
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
// FLIPKART PAGE — Manual FSN Scraping
// ═══════════════════════════════════════════════════════════════════════════
function FlipkartPage({ t, dark }: { t: any; dark: boolean }) {
  const [fsnText, setFsnText] = useState("");
  const [results, setResults] = useState<FlipkartScrapeResult[]>([]);
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, processed: 0, remaining: 0, success: 0, failed: 0 });

  const parseFsns = (text: string) => {
    const raw = text.split(/[\n,]+/).map(a => a.trim()).filter(Boolean);
    const seen = new Set<string>();
    return raw.filter(a => { if (seen.has(a)) return false; seen.add(a); return true; });
  };

  const handleScrape = async () => {
    const fsns = parseFsns(fsnText);
    if (fsns.length === 0) { setError("Please enter at least one FSN"); return; }
    setError("");
    setIsScraping(true);
    setResults(fsns.map(f => ({ fsn: f, status: "pending" })));
    setStats({ total: fsns.length, processed: 0, remaining: fsns.length, success: 0, failed: 0 });

    try {
      const res = await fetch(`${API}/api/flipkart/scrape-manual`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fsns }),
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
          if (["error", "not_found", "blocked", "unavailable"].includes(st)) fail++; else suc++;

          setResults(prev => prev.map(r => r.fsn === data.fsn ? { ...r, ...data, status: st } : r));
          setStats({ total: fsns.length, processed: suc + fail, remaining: fsns.length - suc - fail, success: suc, failed: fail });
        }
      }
    } catch (e: any) {
      setError("Scrape failed: " + e.message);
    } finally {
      setIsScraping(false);
    }
  };

  const downloadCSV = () => {
    if (results.length === 0) return;
    const headers = ["FSN", "Status", "Price", "MRP", "Discount", "Rating", "Rating Count", "Fulfilled By", "URL"];
    const rows = results.map(r => {
      const row = [r.fsn, r.status, r.price || "", r.mrp || "", r.discount || "", r.rating || "", r.rating_count || "", r.fulfilled_by || "", r.url || ""];
      return row.map(field => `"${String(field).replace(/"/g, '""')}"`).join(",");
    });
    const csvContent = [headers.join(","), ...rows].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.setAttribute("download", `flipkart_scrape_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
      {error && (
        <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-500 rounded-xl text-sm font-medium flex items-center">
          <svg className="w-5 h-5 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          {error}
        </div>
      )}

      <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold"><span className="text-[#2874F0]">flipkart</span> — Manual Scrape</h2>
            <p className={`mt-1 text-sm ${t.muted}`}>Paste FSNs below (one per line or comma-separated) to test scraping. Results stay in browser — no sheet writes.</p>
          </div>
        </div>
        <textarea
          value={fsnText}
          onChange={e => setFsnText(e.target.value)}
          placeholder={"LSTMOBHYG9NXBANFHKFB0NVY\nLSTPERHYUFAJGR3DPAKRQNP8F"}
          rows={5}
          className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 focus:ring-[#2874F0]/50 resize-y ${t.input}`}
          disabled={isScraping}
        />
        <div className="flex items-center justify-between mt-4">
          <p className={`text-xs ${t.muted}`}>{parseFsns(fsnText).length} unique FSN(s) detected</p>
          <button
            onClick={handleScrape}
            disabled={isScraping || parseFsns(fsnText).length === 0}
            className="bg-[#2874F0] hover:bg-[#1a5dc8] text-white px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            {isScraping ? <><Spin /> Scraping...</> : "Run Scraper"}
          </button>
        </div>
      </div>

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

      {isScraping && stats.total > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl p-5 shadow-sm`}>
          <div className="flex justify-between text-xs mb-2">
            <span className={t.muted}>Progress</span>
            <span className="text-blue-500 font-medium">{stats.processed} / {stats.total}</span>
          </div>
          <div className={`h-2 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
            <div className="h-full bg-[#2874F0] rounded-full transition-all duration-300" style={{ width: `${Math.round((stats.processed / stats.total) * 100)}%` }} />
          </div>
        </div>
      )}

      {results.length > 0 && (
        <div className={`${t.card} border ${t.border} rounded-2xl overflow-hidden shadow-sm`}>
          <div className={`flex items-center justify-between px-6 py-4 border-b ${t.border}`}>
            <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Scrape Results</p>
            <button onClick={downloadCSV} className={`px-3 py-1.5 rounded-lg text-xs font-medium ${t.btnSecondary} transition-all flex items-center gap-2`}>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
              Download CSV
            </button>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className={`border-b ${t.border} ${t.thead}`}>
                  {["FSN", "Status", "Price", "MRP", "Discount", "Rating", "Rating Count", "Fulfilled By", "URL"].map(h => (
                    <th key={h} className={`px-4 py-4 text-xs font-semibold ${t.muted} uppercase tracking-wider`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className={`divide-y ${t.border}`}>
                {results.map(r => (
                  <tr key={r.fsn} className="transition-colors">
                    <td className="px-4 py-4 whitespace-nowrap text-sm font-medium font-mono">{r.fsn}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-sm"><Badge status={r.status} /></td>
                    <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.price || "—"}</td>
                    <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.mrp || "—"}</td>
                    <td className={`px-4 py-4 whitespace-nowrap text-sm ${t.muted}`}>{r.discount || "—"}</td>
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
      )}
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
    const onHash = () => {
      const h = window.location.hash;
      if (h === "#/scheduler") setPage("scheduler");
      else if (h === "#/flipkart") setPage("flipkart");
      else if (h === "#/blinkit") setPage("blinkit");
      else if (h === "#/zepto") setPage("zepto");
      else setPage("home");
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className={`min-h-screen transition-colors duration-300 font-sans ${t.bg} ${t.text}`}>
      <Header dark={dark} setDark={setDark} t={t} page={page} />
      {page === "scheduler" ? <SchedulerPage t={t} dark={dark} /> : page === "flipkart" ? <FlipkartPage t={t} dark={dark} /> : page === "blinkit" ? <BlinkitPage t={t} dark={dark} /> : page === "zepto" ? <ZeptoPage t={t} dark={dark} /> : <HomePage t={t} dark={dark} />}
    </div>
  );
}
