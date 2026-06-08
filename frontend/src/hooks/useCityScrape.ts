"use client";

import { useState } from "react";
import { API } from "@/lib/api";
import { csvEscape } from "@/lib/csv";
import { errorMessage } from "@/lib/errors";
import { parseUniqueTokens } from "@/lib/parsers";
import type { CityResult, CityScrapeConfig } from "@/types/price-scraper";

export function useCityScrape<T extends CityResult>(config: CityScrapeConfig<T>) {
  const [idText, setIdText] = useState("");
  const [results, setResults] = useState<Record<string, Record<string, T>>>({});
  const [isScraping, setIsScraping] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState({ total: 0, done: 0, success: 0, failed: 0 });

  const parseIds = parseUniqueTokens;

  const handleScrape = async () => {
    const ids = parseIds(idText);
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
      const cells = [pid];
      config.cities.forEach(c => {
        const r = results[pid]?.[c];
        cells.push(r?.price != null ? String(r.price) : "", r?.mrp != null ? String(r.mrp) : "", r?.status || "");
      });
      return cells.map(csvEscape).join(",");
    });
    const blob = new Blob([[hdr.join(","), ...rows].join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
    a.download = `${config.filenamePrefix}_${new Date().toISOString().slice(0,10)}.csv`;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  };

  return { idText, setIdText, results, isScraping, error, stats, parseIds, handleScrape, downloadCSV };
}
