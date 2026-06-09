"use client";

import { useState, useEffect } from "react";
import { API } from "@/lib/api";
import { csvEscape, downloadCsv } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueTokens } from "@/lib/parsers";
import type { FlipkartScrapeResult } from "@/types/price-scraper";
import { useCachedProducts } from "@/hooks/useCachedProducts";

export function useFlipkartManualScrape() {
  const [fsnText, setFsnText] = useState("");
  const [results, setResults] = useState<FlipkartScrapeResult[]>([]);
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, processed: 0, remaining: 0, success: 0, failed: 0 });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const { data: sheetProducts, loading: productsLoading } = useCachedProducts(`${API}/sheets/flipkart/products`);

  const toggleProduct = (id: string) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const parseFsns = parseUniqueTokens;

  const handleScrape = async () => {
    const fsns = [...new Set([...selectedIds, ...parseFsns(fsnText)])];
    if (fsns.length === 0) { setError("Please enter or select at least one FSN"); return; }
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
    const cleanNum = (v?: string) => v ? v.replace(/[₹,]/g, "") : "";
    const rows = results.map(r => [
      csvEscape(r.fsn),
      csvEscape(r.status),
      cleanNum(r.price),
      cleanNum(r.mrp),
      csvEscape(r.discount || ""),
      csvEscape(r.rating || ""),
      csvEscape(r.rating_count || ""),
      csvEscape(r.fulfilled_by || ""),
      csvEscape(r.url || ""),
    ].join(","));
    const csvContent = [headers.join(","), ...rows].join("\n");
    downloadCsv(csvContent, `flipkart_scrape_${new Date().toISOString().slice(0,10)}.csv`);
  };

  return { fsnText, setFsnText, results, isScraping, error, stats, parseFsns, handleScrape, downloadCSV, sheetProducts, productsLoading, selectedIds, toggleProduct };
}
