"use client";

import type { Dispatch, SetStateAction } from "react";
import { Spin } from "@/components/shared/Spin";
import type { CityResult, CityScrapeConfig, ThemeClasses } from "@/types/price-scraper";

export function CityInputCard<T extends CityResult>({ t, text, setText, isScraping, parsedCount, config, onScrape }: {
  t: ThemeClasses;
  text: string;
  setText: Dispatch<SetStateAction<string>>;
  isScraping: boolean;
  parsedCount: number;
  config: CityScrapeConfig<T>;
  onScrape: () => void;
}) {
  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-2xl font-bold"><span className={config.headingBrandClass}>{config.headingBrandText}</span> — {config.headingSuffix}</h2>
          <p className={`mt-1 text-sm ${t.muted}`}>{config.description}</p>
        </div>
      </div>
      <textarea value={text} onChange={e => setText(e.target.value)} placeholder={config.placeholder} rows={4}
        className={`w-full rounded-xl px-4 py-3 text-sm font-mono border focus:outline-none focus:ring-2 ${config.focusRingClass} resize-y ${t.input}`} disabled={isScraping} />
      <div className="flex items-center justify-between mt-4">
        <p className={`text-xs ${t.muted}`}>{parsedCount} product ID(s) × 10 cities = {parsedCount * 10} requests</p>
        <button onClick={onScrape} disabled={isScraping || !parsedCount}
          className={`${config.buttonClass} px-6 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2`}>
          {isScraping ? <><Spin /> Scraping...</> : config.buttonText}
        </button>
      </div>
    </div>
  );
}
