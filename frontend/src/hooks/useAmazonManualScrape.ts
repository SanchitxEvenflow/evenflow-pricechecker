"use client";

import { useState, useEffect } from "react";
import { API } from "@/lib/api";
import { csvEscape, downloadCsv } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueUppercaseTokens } from "@/lib/parsers";
import type { RatingBreakdown, ScrapeResult } from "@/types/price-scraper";

export function useAmazonManualScrape() {
  const [asinText, setAsinText] = useState("");
  const [results, setResults] = useState<ScrapeResult[]>([]);
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, processed: 0, remaining: 0, success: 0, failed: 0 });
  const [sheetProducts, setSheetProducts] = useState<any[]>([]);
  const [productsLoading, setProductsLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    setProductsLoading(true);
    fetch(`${API}/sheets/amazon/products`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setSheetProducts(Array.isArray(data) ? data : []))
      .catch(() => {})
      .finally(() => setProductsLoading(false));
  }, []);

  const toggleProduct = (id: string) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const parseAsins = parseUniqueUppercaseTokens;

  const handleScrape = async () => {
    const asins = [...new Set([...selectedIds, ...parseAsins(asinText)])];
    if (asins.length === 0) { setError("Please enter or select at least one ASIN"); return; }
    setError("");
    setIsScraping(true);
    setResults(asins.map(a => ({ asin: a, status: "pending" })));
    setStats({ total: asins.length, processed: 0, remaining: asins.length, success: 0, failed: 0 });

    try {
      const res = await fetch(`${API}/api/amazon/scrape-manual`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asins }),
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}: ${res.statusText}`);
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
    } catch (e: unknown) {
      setError("Scrape failed: " + errorMessage(e));
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

      return row.map(csvEscape).join(",");
    });

    const csvContent = [headers.join(","), ...rows].join("\n");
    downloadCsv(csvContent, `manual_scrape_${new Date().toISOString().slice(0,10)}.csv`);
  };

  return { asinText, setAsinText, results, isScraping, error, stats, parseAsins, handleScrape, downloadCSV, sheetProducts, productsLoading, selectedIds, toggleProduct };
}
