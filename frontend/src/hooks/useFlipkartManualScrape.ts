"use client";

import { useState } from "react";
import { API } from "@/lib/api";
import { csvEscape, downloadCsv } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueTokens } from "@/lib/parsers";
import type { FlipkartScrapeResult } from "@/types/price-scraper";

export function useFlipkartManualScrape() {
  const [fsnText, setFsnText] = useState("");
  const [results, setResults] = useState<FlipkartScrapeResult[]>([]);
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, processed: 0, remaining: 0, success: 0, failed: 0 });

  const parseFsns = parseUniqueTokens;

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
    } catch (e: unknown) {
      setError("Scrape failed: " + errorMessage(e));
    } finally {
      setIsScraping(false);
    }
  };

  const downloadCSV = () => {
    if (results.length === 0) return;
    const headers = ["FSN", "Status", "Price", "MRP", "Discount", "Rating", "Rating Count", "Fulfilled By", "URL"];
    const rows = results.map(r => {
      const row = [r.fsn, r.status, r.price || "", r.mrp || "", r.discount || "", r.rating || "", r.rating_count || "", r.fulfilled_by || "", r.url || ""];
      return row.map(csvEscape).join(",");
    });
    const csvContent = [headers.join(","), ...rows].join("\n");
    downloadCsv(csvContent, `flipkart_scrape_${new Date().toISOString().slice(0,10)}.csv`);
  };

  return { fsnText, setFsnText, results, isScraping, error, stats, parseFsns, handleScrape, downloadCSV };
}
