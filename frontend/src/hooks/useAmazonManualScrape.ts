"use client";

import { useState, useEffect } from "react";
import { API } from "@/lib/api";
import { getToken, clearAuth } from "@/lib/auth";
import { csvEscape, downloadCsv } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueUppercaseTokens } from "@/lib/parsers";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { RatingBreakdown, ScrapeResult } from "@/types/price-scraper";
import { useCachedProducts } from "@/hooks/useCachedProducts";

export function useAmazonManualScrape() {
  const [asinText, setAsinText] = useState("");
  const [results, setResults] = useState<ScrapeResult[]>([]);
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, processed: 0, remaining: 0, success: 0, failed: 0 });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const { data: rawSheetProducts, loading: productsLoading } = useCachedProducts(`${API}/sheets/amazon/products`);
  const sheetProducts = rawSheetProducts.filter((p, i, arr) => arr.findIndex(x => x.id === p.id) === i);

  const toggleProduct = (id: string) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const parseAsins = parseUniqueUppercaseTokens;

  const handleScrape = async () => {
    const asins = [...new Set([...selectedIds, ...parseAsins(asinText)])];
    if (asins.length === 0) { setError("Please enter or select at least one ASIN"); return; }
    setError("");
    setIsScraping(true);
    setResults(asins.map(a => {
      const p = sheetProducts.find(x => x.id === a);
      return { asin: a, status: "pending", title: p?.title };
    }));
    setStats({ total: asins.length, processed: 0, remaining: asins.length, success: 0, failed: 0 });

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      let suc = 0, fail = 0;
      const processed = new Set<string>();

      await fetchEventSource(`${API}/api/amazon/scrape-manual`, {
        method: "POST",
        headers,
        body: JSON.stringify({ asins }),
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const data = JSON.parse(ev.data);
            if (data.done) return;
            
            if (processed.has(data.asin)) return;
            processed.add(data.asin);

            const st = data.status || "error";
            if (["error", "not_found", "blocked", "invalid_format"].includes(st)) fail++; else suc++;

            setResults(prev => prev.map(r => r.asin === data.asin ? { ...r, ...data, status: st } : r));
            setStats({ total: asins.length, processed: suc + fail, remaining: asins.length - suc - fail, success: suc, failed: fail });
          } catch (e) {
            // Ignore malformed chunks
          }
        },
        onerror(err) {
          if (err?.status === 401) {
            clearAuth();
            window.location.href = "/login";
          }
          throw err;
        }
      });
    } catch (e: unknown) {
      setError("Scrape failed: " + errorMessage(e));
    } finally {
      setIsScraping(false);
    }
  };

  const downloadCSV = () => {
    if (results.length === 0) return;

    const headers = [
      "ASIN", "Title", "Status", "Price", "Rating", "Rating Count", "Rating Breakdown", "Returnable",
      "Parent Node", "Parent Rank", "Child Node", "Child Rank", "URL"
    ];

    const cleanNum = (v?: string | null) => v ? v.replace(/[₹,#]/g, "") : "";
    const rows = results.map(r => {
      const bd = r.rating_breakdown;
      const bdStr = bd
        ? ["5_star","4_star","3_star","2_star","1_star"]
            .map(k => bd[k as keyof RatingBreakdown] ? `${k[0]}★:${bd[k as keyof RatingBreakdown]}` : null)
            .filter(Boolean).join(" ")
        : "";

      return [
        csvEscape(r.asin),
        csvEscape(r.title || ""),
        csvEscape(r.status),
        cleanNum(r.price),
        cleanNum(r.rating),
        cleanNum(r.rating_count),
        csvEscape(bdStr),
        csvEscape(r.returnable || ""),
        csvEscape(r.parent_node || ""),
        cleanNum(r.rank_value),
        csvEscape(r.child_node || ""),
        cleanNum(r.sub_rank_value),
        csvEscape(`https://www.amazon.in/dp/${r.asin}`),
      ].join(",");
    });

    const csvContent = [headers.join(","), ...rows].join("\n");
    downloadCsv(csvContent, `manual_scrape_${new Date().toISOString().slice(0,10)}.csv`);
  };

  return { asinText, setAsinText, results, isScraping, error, stats, parseAsins, handleScrape, downloadCSV, sheetProducts, productsLoading, selectedIds, toggleProduct };
}
