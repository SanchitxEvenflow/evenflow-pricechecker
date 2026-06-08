"use client";

import type { Dispatch, SetStateAction } from "react";
<<<<<<< HEAD
=======
import { ProductPicker, type SheetProduct } from "@/components/shared/ProductPicker";
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79
import { Spin } from "@/components/shared/Spin";
import { useSheetConfig } from "@/hooks/useSheetConfig";
import type { CityResult, CityScrapeConfig, ThemeClasses } from "@/types/price-scraper";

<<<<<<< HEAD
// Google Sheets icon
=======
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79
function SheetsIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm-7 3h2v2h-2V6zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2zm-4-8h2v2H8V6zm0 4h2v2H8v-2zm0 4h2v2H8v-2zm8-8h2v2h-2V6zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z"/>
    </svg>
  );
}

<<<<<<< HEAD
export function CityInputCard<T extends CityResult>({ t, dark, text, setText, isScraping, parsedCount, config, onScrape }: {
=======
export function CityInputCard<T extends CityResult>({ t, dark, text, setText, isScraping, parsedCount, config, onScrape, sheetProducts, productsLoading, selectedIds, onToggleProduct }: {
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79
  t: ThemeClasses;
  dark: boolean;
  text: string;
  setText: Dispatch<SetStateAction<string>>;
  isScraping: boolean;
  parsedCount: number;
  config: CityScrapeConfig<T>;
  onScrape: () => void;
<<<<<<< HEAD
=======
  sheetProducts: SheetProduct[];
  productsLoading: boolean;
  selectedIds: string[];
  onToggleProduct: (id: string) => void;
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79
}) {
  const sheets = useSheetConfig();
  const sheetUrl = sheets[config.brand];
  const cityCount = config.cities.length;
<<<<<<< HEAD
=======
  const totalIds = selectedIds.length + parsedCount;
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79

  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-2xl font-bold"><span className={config.headingBrandClass}>{config.headingBrandText}</span> — {config.headingSuffix}</h2>
          <p className={`mt-1 text-sm ${t.muted}`}>{config.description}</p>
        </div>
        {sheetUrl && (
<<<<<<< HEAD
          <a
            href={sheetUrl}
            target="_blank"
            rel="noopener noreferrer"
            title="Open Google Sheet"
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border shrink-0 ${dark ? "border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-200" : "border-neutral-300 bg-white hover:bg-neutral-50 text-neutral-700"}`}
          >
=======
          <a href={sheetUrl} target="_blank" rel="noopener noreferrer" title="Open Google Sheet"
            className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all border shrink-0 ${dark ? "border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-200" : "border-neutral-300 bg-white hover:bg-neutral-50 text-neutral-700"}`}>
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79
            <SheetsIcon />
            View Sheet
          </a>
        )}
      </div>
<<<<<<< HEAD
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={config.placeholder} rows={4}
        className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 ${config.focusRingClass} resize-y ${t.input}`} disabled={isScraping} />
      <div className="flex items-center justify-between mt-4">
        <p className={`text-xs ${t.muted}`}>{parsedCount} product ID(s) × {cityCount} cities = {parsedCount * cityCount} requests</p>
        <button onClick={onScrape} disabled={isScraping || !parsedCount}
=======
      <ProductPicker products={sheetProducts} selectedIds={selectedIds} onToggle={onToggleProduct}
        loading={productsLoading} accentFocus={config.focusRingClass} t={t} dark={dark} />
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={config.placeholder} rows={4}
        className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 ${config.focusRingClass} resize-y ${t.input}`} disabled={isScraping} />
      <div className="flex items-center justify-between mt-4">
        <p className={`text-xs ${t.muted}`}>
          {selectedIds.length > 0
            ? `${selectedIds.length} from sheet + ${parsedCount} pasted`
            : `${parsedCount} product ID(s)`
          } × {cityCount} cities = {totalIds * cityCount} requests
        </p>
        <button onClick={onScrape} disabled={isScraping || totalIds === 0}
>>>>>>> f3b9221745d678d06b6e9a19f66e76812a93db79
          className={`${config.buttonClass} px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2`}>
          {isScraping ? <><Spin /> Scraping...</> : config.buttonText}
        </button>
      </div>
    </div>
  );
}
