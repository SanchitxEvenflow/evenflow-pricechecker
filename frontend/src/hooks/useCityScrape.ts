"use client";

import { useEffect, useState } from "react";
import { API } from "@/lib/api";
import { csvEscape } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueTokens } from "@/lib/parsers";
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
    setResults({}); setStats({ total: ids.length * config.cities.length, done: 0, success: 0, failed: 0 });

    try {
      const res = await fetch(`${API}${config.endpoint}`, {
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
        
        const chunkUpdates: any[] = [];
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const d = JSON.parse(line.slice(6));
            if (d.done) continue;
            if (d.status === "error") fail++; else suc++;
            chunkUpdates.push(d);
          } catch (e) {
            // Silently skip malformed JSON events instead of aborting
            continue;
          }
        }

        if (chunkUpdates.length > 0) {
          setResults(prev => {
            const next = { ...prev };
            for (const d of chunkUpdates) {
              if (!next[d.product_id]) next[d.product_id] = {};
              next[d.product_id] = { ...next[d.product_id], [d.city]: d };
            }
            return next;
          });
          setStats({ total: ids.length * config.cities.length, done: suc + fail, success: suc, failed: fail });
        }
      }
    } catch (e: unknown) { setError("Scrape failed: " + errorMessage(e)); }
    finally { setIsScraping(false); }
  };

  const downloadCSV = () => {
    const pids = Object.keys(results);
    if (!pids.length) return;
    const hdr = ["Product ID", ...config.cities.flatMap(c => [`${c} Price`, `${c} MRP`, `${c} Status`])];
    const rows = pids.map(pid => {
      const cells: string[] = [csvEscape(pid)];
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
