"use client";

import type { Dispatch, SetStateAction } from "react";
import { Spin } from "@/components/shared/Spin";
import type { ThemeClasses } from "@/types/price-scraper";

export function AmazonInputCard({ t, asinText, setAsinText, isScraping, asinCount, onScrape }: {
  t: ThemeClasses;
  asinText: string;
  setAsinText: Dispatch<SetStateAction<string>>;
  isScraping: boolean;
  asinCount: number;
  onScrape: () => void;
}) {
  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold"><span className="text-[#FF9900]">amazon</span> — Manual Scrape</h2>
          <p className={`mt-1 text-sm ${t.muted}`}>Paste ASINs below (one per line) to test scraping. Results stay in browser — no sheet writes.</p>
        </div>
      </div>
      <textarea
        value={asinText}
        onChange={e => setAsinText(e.target.value)}
        placeholder={"B0DSWQVWJQ\nB09G9FPHY6\nB08N5WRWNW"}
        rows={5}
        className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 focus:ring-[#FF9900]/50 resize-y ${t.input}`}
        disabled={isScraping}
      />
      <div className="flex items-center justify-between mt-4">
        <p className={`text-xs ${t.muted}`}>{asinCount} unique ASIN(s) detected</p>
        <button
          onClick={onScrape}
          disabled={isScraping || asinCount === 0}
          className="bg-[#FF9900] hover:bg-[#e88a00] text-black px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {isScraping ? <><Spin /> Scraping...</> : "Run Scraper"}
        </button>
      </div>
    </div>
  );
}
