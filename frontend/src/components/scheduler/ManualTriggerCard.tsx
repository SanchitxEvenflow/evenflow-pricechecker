"use client";

import { Spin } from "@/components/shared/Spin";
import { useSheetConfig } from "@/hooks/useSheetConfig";
import type { CronStatus, ThemeClasses } from "@/types/price-scraper";

const triggerConfig = {
  amazon: {
    color: "bg-[#FF9900] hover:bg-[#e88a00] text-black",
    bar: "bg-[#FF9900]",
    brandClass: "text-[#FF9900]",
    name: "amazon",
    description: "Run a full scrape of all ASINs from the Google Sheet. Results are written to a new tab:",
    code: "Manual_Trigger_YYYY-MM-DD_HH-MM",
  },
  blinkit: {
    color: "bg-[#F8CB46] hover:bg-[#e5b93d] text-black",
    bar: "bg-[#F8CB46]",
    brandClass: "text-[#F8CB46]",
    name: "blinkit",
    description: "Run a full scrape of all PIDs from the Blinkit Google Sheet across all 10 cities. Results are written to a new tab:",
    code: "Blinkit_Manual_YYYY-MM-DD_HH-MM",
  },
  flipkart: {
    color: "bg-[#2874F0] hover:bg-[#1a5dc8] text-white",
    bar: "bg-[#2874F0]",
    brandClass: "text-[#2874F0]",
    name: "flipkart",
    description: "Run a full scrape of all FSNs from the Flipkart Google Sheet. Results are written to a new tab:",
    code: "Flipkart_Manual_YYYY-MM-DD_HH-MM",
  },
  zepto: {
    color: "bg-[#FF3269] hover:bg-[#e02b5c] text-white",
    bar: "bg-[#FF3269]",
    brandClass: "text-[#FF3269]",
    name: "zepto",
    description: "Run a full scrape of all PIDs from the Zepto Google Sheet across all 9 cities. Results are written to a new tab:",
    code: "Zepto_Manual_YYYY-MM-DD_HH-MM",
  },
  instamart: {
    color: "bg-[#FC8019] hover:bg-[#e06b0b] text-white",
    bar: "bg-[#FC8019]",
    brandClass: "text-[#FC8019]",
    name: "instamart",
    description: "Run a full scrape of all PIDs from the Instamart Google Sheet across all 8 cities. Results are written to a new tab:",
    code: "Instamart_Manual_YYYY-MM-DD_HH-MM",
  },
};

// Google Sheets icon (simplified)
function SheetsIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor">
      <path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm-7 3h2v2h-2V6zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2zm-4-8h2v2H8V6zm0 4h2v2H8v-2zm0 4h2v2H8v-2zm8-8h2v2h-2V6zm0 4h2v2h-2v-2zm0 4h2v2h-2v-2z"/>
    </svg>
  );
}

export function ManualTriggerCard({ t, dark, brand, status, isTriggering, onTrigger }: {
  t: ThemeClasses;
  dark: boolean;
  brand: keyof typeof triggerConfig;
  status: CronStatus | null;
  isTriggering: boolean;
  onTrigger: () => void;
}) {
  const cfg = triggerConfig[brand];
  const sheets = useSheetConfig();
  const sheetUrl = sheets[brand];

  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-8 shadow-sm`}>
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold"><span className={cfg.brandClass}>{cfg.name}</span> — Manual Trigger</h2>
          <p className={`mt-1 text-sm ${t.muted}`}>{cfg.description} <code className={`text-xs px-1.5 py-0.5 rounded ${dark ? "bg-neutral-800" : "bg-neutral-100"}`}>{cfg.code}</code></p>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {sheetUrl && (
            <a
              href={sheetUrl}
              target="_blank"
              rel="noopener noreferrer"
              title="Open Google Sheet"
              className={`flex items-center gap-2 px-4 py-3 rounded-xl text-sm font-medium transition-all border ${dark ? "border-neutral-700 bg-neutral-800 hover:bg-neutral-700 text-neutral-200" : "border-neutral-300 bg-white hover:bg-neutral-50 text-neutral-700"}`}
            >
              <SheetsIcon />
              View Sheet
            </a>
          )}
          <button
            onClick={onTrigger}
            disabled={isTriggering || status?.is_running === true}
            className={`${cfg.color} px-8 py-3 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2`}
          >
            {isTriggering ? <><Spin /> Starting...</> : status?.is_running ? "Scrape Running..." : "Manual Trigger"}
          </button>
        </div>
      </div>

      {status?.is_running && status.progress != null && status.total != null && status.total > 0 && (
        <div className="mt-6">
          <div className="flex justify-between text-xs mb-2">
            <span className={t.muted}>Progress</span>
            <span className="text-blue-500 font-medium">{status.progress} / {status.total}</span>
          </div>
          <div className={`h-2.5 rounded-full overflow-hidden ${dark ? "bg-neutral-800" : "bg-neutral-200"}`}>
            <div className={`h-full ${cfg.bar} rounded-full transition-all duration-500`} style={{ width: `${Math.round((status.progress / status.total) * 100)}%` }} />
          </div>
        </div>
      )}
    </div>
  );
}
