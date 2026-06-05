"use client";

import type { Dispatch, SetStateAction } from "react";
import { Spin } from "@/components/shared/Spin";
import type { ThemeClasses } from "@/types/price-scraper";

export function FlipkartInputCard({ t, fsnText, setFsnText, isScraping, fsnCount, onScrape }: {
  t: ThemeClasses;
  fsnText: string;
  setFsnText: Dispatch<SetStateAction<string>>;
  isScraping: boolean;
  fsnCount: number;
  onScrape: () => void;
}) {
  return (
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
        <p className={`text-xs ${t.muted}`}>{fsnCount} unique FSN(s) detected</p>
        <button
          onClick={onScrape}
          disabled={isScraping || fsnCount === 0}
          className="bg-[#2874F0] hover:bg-[#1a5dc8] text-white px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {isScraping ? <><Spin /> Scraping...</> : "Run Scraper"}
        </button>
      </div>
    </div>
  );
}
