"use client";

import type { Dispatch, SetStateAction } from "react";
import { ProductPicker, type SheetProduct } from "@/components/shared/ProductPicker";
import { Spin } from "@/components/shared/Spin";
import { useSheetConfig } from "@/hooks/useSheetConfig";
import type { ThemeClasses } from "@/types/price-scraper";

function SheetsIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm-7 3h2v2h-2V6zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2zm-4-8h2v2H8V6zm0 4h2v2H8v-2zm0 4h2v2H8v-2zm8-8h2v2h-2V6zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z"/>
    </svg>
  );
}

export function FlipkartInputCard({ t, fsnText, setFsnText, isScraping, fsnCount, onScrape, dark, sheetProducts, productsLoading, selectedIds, onToggleProduct }: {
  t: ThemeClasses;
  fsnText: string;
  setFsnText: Dispatch<SetStateAction<string>>;
  isScraping: boolean;
  fsnCount: number;
  onScrape: () => void;
  dark: boolean;
  sheetProducts: SheetProduct[];
  productsLoading: boolean;
  selectedIds: string[];
  onToggleProduct: (id: string) => void;
}) {
  const sheets = useSheetConfig();
  const sheetUrl = sheets["flipkart"];

  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-2xl font-bold"><span className="text-[#2874F0]">flipkart</span> — Manual Scrape</h2>
          <p className={`mt-1 text-sm ${t.muted}`}>Paste FSNs below (one per line or comma-separated) to test scraping. Results stay in browser — no sheet writes.</p>
        </div>
        {sheetUrl && (
          <a href={sheetUrl} target="_blank" rel="noopener noreferrer" title="Open Google Sheet"
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border shrink-0 ${dark ? "border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-200" : "border-neutral-300 bg-white hover:bg-neutral-50 text-neutral-700"}`}>
            <SheetsIcon />
            View Sheet
          </a>
        )}
      </div>
      <ProductPicker products={sheetProducts} selectedIds={selectedIds} onToggle={onToggleProduct}
        loading={productsLoading} accentFocus="focus:ring-[#2874F0]/50" t={t} dark={dark} />
      <textarea
        value={fsnText}
        onChange={e => setFsnText(e.target.value)}
        placeholder={"LSTMOBHYG9NXBANFHKFB0NVY\nLSTPERHYUFAJGR3DPAKRQNP8F"}
        rows={5}
        className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 focus:ring-[#2874F0]/50 resize-y ${t.input}`}
        disabled={isScraping}
      />
      <div className="flex items-center justify-between mt-4">
        <p className={`text-xs ${t.muted}`}>
          {selectedIds.length > 0
            ? `${selectedIds.length} from sheet + ${fsnCount} pasted`
            : `${fsnCount} unique FSN(s) detected`
          }
        </p>
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
