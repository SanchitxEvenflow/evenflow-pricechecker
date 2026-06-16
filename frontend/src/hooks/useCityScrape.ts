"use client";

import { useEffect, useState, useRef } from "react";
import { API } from "@/lib/api";
import { getToken, clearAuth } from "@/lib/auth";
import { csvEscape } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueTokens } from "@/lib/parsers";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import type { SheetProduct } from "@/components/shared/ProductPicker";
import type { CityResult, CityScrapeConfig } from "@/types/price-scraper";
import { useCachedProducts } from "@/hooks/useCachedProducts";

export function useCityScrape<T extends CityResult>(config: CityScrapeConfig<T>) {
  const [idText, setIdText] = useState("");
  const [results, setResults] = useState<Record<string, Record<string, T>>>({});
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, done: 0, success: 0, failed: 0 });
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const { data: sheetProducts, loading: productsLoading } = useCachedProducts(`${API}/price/${config.brand}/products`);

  const toggleProduct = (id: string) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const parseIds = parseUniqueTokens;

  const handleScrape = async () => {
    const ids = [...new Set([...selectedIds, ...parseIds(idText)])];
    if (!ids.length) { setError(config.emptyInputError); return; }
    setError(""); setIsScraping(true);
    const initialResults: Record<string, any> = {};
    for (const id of ids) {
      initialResults[id] = {};
      for (const city of config.cities) {
        initialResults[id][city] = { status: "pending", product_id: id, city };
      }
    }
    setResults(initialResults); 
    setStats({ total: ids.length * config.cities.length, done: 0, success: 0, failed: 0 });

    try {
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      let suc = 0, fail = 0;

      await fetchEventSource(`${API}${config.endpoint}`, {
        method: "POST",
        headers,
        body: JSON.stringify({ product_ids: ids }),
        onmessage(ev) {
          try {
            const d = JSON.parse(ev.data);
            if (d.done) return;
            if (d.status === "error") fail++; else suc++;

            setResults(prev => ({
              ...prev,
              [d.product_id]: {
                ...prev[d.product_id],
                [d.city]: d
              }
            }));
            setStats({ total: ids.length * config.cities.length, done: suc + fail, success: suc, failed: fail });
          } catch (e) {
            // ignore malformed chunks
          }
        },
        onerror(err) {
          if (err?.status === 401) {
            clearAuth();
            window.location.href = "/login";
          }
          throw err; // throw to trigger retry or catch block
        }
      });
    } catch (e: unknown) { setError("Scrape failed: " + errorMessage(e)); }
    finally { setIsScraping(false); }
  };

  const downloadCSV = () => {
    const pids = Object.keys(results);
    if (!pids.length) return;
    const hdr = ["Product ID", "Title", ...config.cities.flatMap(c => [`${c} Price`, `${c} MRP`, `${c} Status`])];
    const rows = pids.map(pid => {
      const firstResultWithTitle = Object.values(results[pid] || {}).find(r => r.title);
      const title = sheetProducts?.find(x => x.id === pid)?.title || firstResultWithTitle?.title || "—";
      const cells: string[] = [csvEscape(pid), csvEscape(title)];
      config.cities.forEach(c => {
        const r = results[pid]?.[c];
        cells.push(
          r?.price != null ? String(r.price) : "",
          r?.mrp != null ? String(r.mrp) : "",
          csvEscape(r?.status || ""),
        );
      });
      return cells.join(",");
    });
    const blob = new Blob([[hdr.join(","), ...rows].join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `${config.filenamePrefix}_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  return { idText, setIdText, results, isScraping, error, stats, parseIds, handleScrape, downloadCSV, sheetProducts, productsLoading, selectedIds, toggleProduct };
}
