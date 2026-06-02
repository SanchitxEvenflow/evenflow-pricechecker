"use client";

import { useState, useEffect } from "react";
import Image from "next/image";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface RowData {
  row: number;
  asin: string;
  status: string;
  price?: string;
  rating?: string;
  rating_count?: string;
}

export default function Dashboard() {
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [sheetId, setSheetId] = useState("");
  const [tabName, setTabName] = useState("");
  const [rows, setRows] = useState<RowData[]>([]);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isScraping, setIsScraping] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const [stats, setStats] = useState({
    total: 0,
    pending: 0,
    success: 0,
    error: 0,
  });

  useEffect(() => {
    // Fetch default config from backend
    fetch(`${API_BASE}/sheets/config`)
      .then(res => res.json())
      .then(data => {
        if (data.spreadsheet_id) setSheetId(data.spreadsheet_id);
        if (data.worksheet_name) setTabName(data.worksheet_name);
      })
      .catch(err => console.error("Failed to load config", err));
  }, []);

  const handleConnect = async () => {
    setIsConnecting(true);
    setErrorMsg("");
    try {
      const res = await fetch(`${API_BASE}/sheets/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sheet_id: sheetId, tab_name: tabName }),
      });
      const data = await res.json();
      if (res.ok && data.status === "success") {
        const initialRows = data.data.map((r: any) => ({
          ...r,
          status: "pending",
        }));
        setRows(initialRows);
        setStats({
          total: initialRows.length,
          pending: initialRows.length,
          success: 0,
          error: 0,
        });
      } else {
        setErrorMsg(data.detail || "Failed to connect to Google Sheets");
      }
    } catch (e: any) {
      setErrorMsg("Error connecting to backend: " + e.message);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleStartScraping = async () => {
    if (rows.length === 0) return;
    setIsScraping(true);
    setErrorMsg("");

    const batchSize = 5;
    let currentRows = [...rows];
    let newSuccess = 0;
    let newError = 0;

    for (let i = 0; i < currentRows.length; i += batchSize) {
      const batch = currentRows.slice(i, i + batchSize);

      // Update status to processing for this batch
      setRows((prev) =>
        prev.map((r) =>
          batch.find((b) => b.row === r.row) ? { ...r, status: "processing" } : r
        )
      );

      try {
        const res = await fetch(`${API_BASE}/sheets/scrape-batch`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sheet_id: sheetId,
            tab_name: tabName,
            rows: batch.map(b => ({ row: b.row, asin: b.asin })),
          }),
        });

        const data = await res.json();

        if (res.ok && data.status === "success") {
          // Update rows with results
          setRows((prev) =>
            prev.map((r) => {
              const scrapedResult = data.data.find((d: any) => d.row === r.row);
              if (scrapedResult) {
                const isError = scrapedResult.status === "error" || scrapedResult.status === "not_found";
                if (isError) {
                  newError++;
                } else {
                  newSuccess++;
                }
                return {
                  ...r,
                  status: scrapedResult.status,
                  price: scrapedResult.price,
                  rating: scrapedResult.rating,
                  rating_count: scrapedResult.rating_count,
                };
              }
              return r;
            })
          );
        } else {
          // Mark batch as error
          newError += batch.length;
          setRows((prev) =>
            prev.map((r) =>
              batch.find((b) => b.row === r.row) ? { ...r, status: "error" } : r
            )
          );
        }
      } catch (e) {
        // Mark batch as error
        newError += batch.length;
        setRows((prev) =>
          prev.map((r) =>
            batch.find((b) => b.row === r.row) ? { ...r, status: "error" } : r
          )
        );
      }

      setStats({
        total: currentRows.length,
        pending: currentRows.length - (newSuccess + newError),
        success: newSuccess,
        error: newError,
      });
    }

    setIsScraping(false);
  };

  // Theme Classes
  const bgClass = isDarkMode ? "bg-neutral-950" : "bg-neutral-50";
  const textClass = isDarkMode ? "text-neutral-100" : "text-neutral-900";
  const cardBgClass = isDarkMode ? "bg-neutral-900" : "bg-white";
  const borderClass = isDarkMode ? "border-neutral-800" : "border-neutral-200";
  const mutedTextClass = isDarkMode ? "text-neutral-400" : "text-neutral-500";
  const theadBgClass = isDarkMode ? "bg-neutral-950/50" : "bg-neutral-50";

  return (
    <div className={`min-h-screen transition-colors duration-300 font-sans ${bgClass} ${textClass}`}>

      {/* Header */}
      <header className={`sticky top-0 z-20 border-b ${borderClass} ${isDarkMode ? 'bg-neutral-950/80' : 'bg-white/80'} backdrop-blur-md`}>
        <div className="max-w-6xl mx-auto px-6 py-4 flex justify-between items-center">
          <div className="flex items-center space-x-3">
            <Image src="/logo.png" alt="Logo" width={48} height={48} className="rounded object-contain" unoptimized />
            <h1 className="text-xl font-bold tracking-tight">Price Scraper</h1>
          </div>

          <button
            onClick={() => setIsDarkMode(!isDarkMode)}
            className={`p-2 rounded-full border ${borderClass} hover:opacity-80 transition-opacity`}
            aria-label="Toggle Theme"
          >
            {isDarkMode ? (
              <svg className="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"></path>
              </svg>
            ) : (
              <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path>
              </svg>
            )}
          </button>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">

        {errorMsg && (
          <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-500 rounded-xl text-sm font-medium flex items-center">
            <svg className="w-5 h-5 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            {errorMsg}
          </div>
        )}

        {/* Action Block */}
        <div className={`${cardBgClass} border ${borderClass} rounded-2xl p-8 shadow-sm flex flex-col md:flex-row md:items-center justify-between`}>
          <div>
            <h2 className="text-3xl font-bold flex items-center gap-2">
              <span className="text-[#FF9900]">amazon</span>
            </h2>
            <p className={`mt-2 ${mutedTextClass}`}>Automatically fetch price, rating, and nodes directly into your Google Sheet.</p>
          </div>

          <div className="flex flex-col sm:flex-row gap-3 mt-6 md:mt-0">
            <button
              onClick={handleConnect}
              disabled={!sheetId || !tabName || isConnecting || isScraping}
              className={`px-6 py-3 rounded-xl font-medium text-sm transition-all flex items-center justify-center
                ${isDarkMode ? 'bg-neutral-800 hover:bg-neutral-700 text-white' : 'bg-neutral-200 hover:bg-neutral-300 text-neutral-900'}
                disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isConnecting ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  Connecting...
                </span>
              ) : (
                "Connect & Preview"
              )}
            </button>

            <button
              onClick={handleStartScraping}
              disabled={rows.length === 0 || isScraping || stats.pending === 0}
              className="bg-[#FF9900] hover:bg-[#e88a00] text-black px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center"
            >
              {isScraping ? (
                <span className="flex items-center gap-2">
                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  Scraping...
                </span>
              ) : (
                "Start Scraping"
              )}
            </button>
          </div>
        </div>

        {/* Stats */}
        {rows.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className={`${cardBgClass} border ${borderClass} rounded-2xl p-5 shadow-sm`}>
              <p className={`text-xs ${mutedTextClass} font-semibold uppercase tracking-wider`}>Total Rows</p>
              <p className="text-3xl font-bold mt-1">{stats.total}</p>
            </div>
            <div className={`${cardBgClass} border ${borderClass} rounded-2xl p-5 shadow-sm`}>
              <p className={`text-xs ${mutedTextClass} font-semibold uppercase tracking-wider`}>Pending</p>
              <p className="text-3xl font-bold mt-1 text-yellow-500">{stats.pending}</p>
            </div>
            <div className={`${cardBgClass} border ${borderClass} rounded-2xl p-5 shadow-sm`}>
              <p className={`text-xs ${mutedTextClass} font-semibold uppercase tracking-wider`}>Success</p>
              <p className="text-3xl font-bold mt-1 text-green-500">{stats.success}</p>
            </div>
            <div className={`${cardBgClass} border ${borderClass} rounded-2xl p-5 shadow-sm`}>
              <p className={`text-xs ${mutedTextClass} font-semibold uppercase tracking-wider`}>Error</p>
              <p className="text-3xl font-bold mt-1 text-red-500">{stats.error}</p>
            </div>
          </div>
        )}

        {/* Table */}
        {rows.length > 0 && (
          <div className={`${cardBgClass} border ${borderClass} rounded-2xl overflow-hidden shadow-sm`}>
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className={`border-b ${borderClass} ${theadBgClass}`}>
                    <th className={`px-6 py-4 text-xs font-semibold ${mutedTextClass} uppercase tracking-wider w-16`}>Row</th>
                    <th className={`px-6 py-4 text-xs font-semibold ${mutedTextClass} uppercase tracking-wider`}>ASIN</th>
                    <th className={`px-6 py-4 text-xs font-semibold ${mutedTextClass} uppercase tracking-wider`}>Status</th>
                    <th className={`px-6 py-4 text-xs font-semibold ${mutedTextClass} uppercase tracking-wider`}>Price</th>
                    <th className={`px-6 py-4 text-xs font-semibold ${mutedTextClass} uppercase tracking-wider`}>Rating</th>
                  </tr>
                </thead>
                <tbody className={`divide-y ${borderClass}`}>
                  {rows.map((row) => (
                    <tr key={row.row} className={`hover:${isDarkMode ? 'bg-neutral-800/40' : 'bg-neutral-50'} transition-colors`}>
                      <td className={`px-6 py-4 whitespace-nowrap text-sm ${mutedTextClass}`}>{row.row}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">{row.asin}</td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold capitalize
                          ${row.status === 'success' ? 'bg-green-500/10 text-green-600 dark:text-green-400' : ''}
                          ${row.status === 'processing' ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400' : ''}
                          ${row.status === 'pending' ? 'bg-neutral-500/10 text-neutral-600 dark:text-neutral-400' : ''}
                          ${(row.status === 'error' || row.status === 'not_found' || row.status === 'blocked') ? 'bg-red-500/10 text-red-600 dark:text-red-400' : ''}
                        `}>
                          {row.status === 'error' ? 'failed' : row.status}
                        </span>
                      </td>
                      <td className={`px-6 py-4 whitespace-nowrap text-sm ${isDarkMode ? 'text-neutral-300' : 'text-neutral-700'}`}>
                        {row.price || "-"}
                      </td>
                      <td className={`px-6 py-4 whitespace-nowrap text-sm ${isDarkMode ? 'text-neutral-300' : 'text-neutral-700'}`}>
                        {row.rating ? `${row.rating} (${row.rating_count || 0})` : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
