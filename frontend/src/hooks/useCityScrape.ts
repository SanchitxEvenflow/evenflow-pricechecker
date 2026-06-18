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
  const [orderedIds, setOrderedIds] = useState<string[]>([]);
  const { data: sheetProducts, loading: productsLoading } = useCachedProducts(`${API}/price/${config.brand}/products`);

  const toggleProduct = (id: string) =>
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);

  const parseIds = parseUniqueTokens;

  const handleScrape = async () => {
    const ids = [...new Set([...selectedIds, ...parseIds(idText)])];
    if (!ids.length) { setError(config.emptyInputError); return; }
    setOrderedIds(ids);
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
      const processed = new Set<string>();
      const ctrl = new AbortController();

      await fetchEventSource(`${API}${config.endpoint}`, {
        method: "POST",
        headers,
        signal: ctrl.signal,
        body: JSON.stringify({ product_ids: ids }),
        openWhenHidden: true,
        onmessage(ev) {
          try {
            const d = JSON.parse(ev.data);
            if (d.done) {
              ctrl.abort();
              return;
            }
            
            setResults(prev => {
              const productRow = prev[d.product_id] || {};
              // Prevent unnecessary state updates if the result is identical
              if (productRow[d.city]?.status === d.status && productRow[d.city]?.price === d.price) {
                 return prev;
              }
              
              const next = {
                ...prev,
                [d.product_id]: {
                  ...productRow,
                  [d.city]: d
                }
              };
              
              // Mathematically guarantee stats cannot exceed the total grid cells
              let newSuc = 0;
              let newFail = 0;
              let newDone = 0;
              Object.values(next).forEach(row => {
                Object.values(row).forEach(cell => {
                  if (cell.status === "error") newFail++;
                  else if (cell.status && cell.status !== "pending") newSuc++;
                  
                  if (cell.status && cell.status !== "pending") newDone++;
                });
              });
              
              setStats({ 
                total: ids.length * config.cities.length, 
                done: newDone, 
                success: newSuc, 
                failed: newFail 
              });
              
              return next;
            });
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
    const pids = orderedIds.length ? orderedIds : Object.keys(results);
    if (!pids.length) return;
    const hdr = ["Product ID", "Title", ...config.cities.flatMap(c => [`${c} Price`, `${c} MRP`, `${c} Status`])];
    const rows = pids.map(pid => {
      const firstResultWithTitle = Object.values(results[pid] || {}).find(r => r.title && r.title !== "Not Found" && r.title !== "Unknown Product");
      const sheetTitle = sheetProducts?.find((x: any) => x.id === pid)?.title;
      const title = sheetTitle || firstResultWithTitle?.title || "—";
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

  return { idText, setIdText, results, orderedIds, isScraping, error, stats, parseIds, handleScrape, downloadCSV, sheetProducts, productsLoading, selectedIds, toggleProduct };
}
