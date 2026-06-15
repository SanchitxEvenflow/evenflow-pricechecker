"use client";

import { ErrorBanner } from "@/components/shared/ErrorBanner";
import { FlipkartInputCard } from "@/components/flipkart/FlipkartInputCard";
import { FlipkartResultsTable } from "@/components/flipkart/FlipkartResultsTable";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatsGrid } from "@/components/shared/StatsGrid";
import { useFlipkartManualScrape } from "@/hooks/useFlipkartManualScrape";
import type { ThemeClasses } from "@/types/price-scraper";

export function FlipkartManualPage({ t, dark }: { t: ThemeClasses; dark: boolean }) {
  const scrape = useFlipkartManualScrape();
  const fsnCount = scrape.parseFsns(scrape.fsnText).length;

  return (
    <main className="max-w-[95vw] mx-auto px-6 py-8 space-y-8">
      <ErrorBanner error={scrape.error} />
      <FlipkartInputCard t={t} fsnText={scrape.fsnText} setFsnText={scrape.setFsnText} isScraping={scrape.isScraping} fsnCount={fsnCount} onScrape={scrape.handleScrape} dark={dark} sheetProducts={scrape.sheetProducts} productsLoading={scrape.productsLoading} selectedIds={scrape.selectedIds} onToggleProduct={scrape.toggleProduct} />
      {scrape.stats.total > 0 && (
        <StatsGrid t={t} columnsClass="grid-cols-2 md:grid-cols-5" items={[
          { label: "Total", value: scrape.stats.total, color: "" },
          { label: "Processed", value: scrape.stats.processed, color: "" },
          { label: "Remaining", value: scrape.stats.remaining, color: "text-yellow-500" },
          { label: "Success", value: scrape.stats.success, color: "text-green-500" },
          { label: "Failed", value: scrape.stats.failed, color: "text-red-500" },
        ]} />
      )}
      {scrape.isScraping && scrape.stats.total > 0 && <ProgressBar dark={dark} t={t} processed={scrape.stats.processed} total={scrape.stats.total} colorClass="bg-[#2874F0]" />}
      <FlipkartResultsTable t={t} results={scrape.results} onDownloadCSV={scrape.downloadCSV} />
    </main>
  );
}
