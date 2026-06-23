"use client";

import { CityInputCard } from "@/components/quick-commerce/CityInputCard";
import { CityResultsMatrix } from "@/components/quick-commerce/CityResultsMatrix";
import { ErrorBanner } from "@/components/shared/ErrorBanner";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatsGrid } from "@/components/shared/StatsGrid";
import { useCityScrape } from "@/hooks/useCityScrape";
import type { CityResult, CityScrapeConfig, ThemeClasses } from "@/types/price-scraper";

export function CityScrapePage<T extends CityResult>({ t, dark, config }: { t: ThemeClasses; dark: boolean; config: CityScrapeConfig<T> }) {
  const scrape = useCityScrape(config);
  const parsedCount = scrape.parseIds(scrape.idText).length;

  return (
    <main className="max-w-[95vw] mx-auto px-6 py-8 space-y-8">
      <ErrorBanner error={scrape.error} />
      <CityInputCard t={t} dark={dark} text={scrape.idText} setText={scrape.setIdText} isScraping={scrape.isScraping} parsedCount={parsedCount} config={config} onScrape={scrape.handleScrape}
        sheetProducts={scrape.sheetProducts} productsLoading={scrape.productsLoading} selectedIds={scrape.selectedIds} onToggleProduct={scrape.toggleProduct} />
      {scrape.stats.total > 0 && (
        <StatsGrid t={t} columnsClass="grid-cols-2 md:grid-cols-4" items={[
          { label: "Total", value: scrape.stats.total, color: "" },
          { label: "Done", value: scrape.stats.done, color: "" },
          { label: "Success", value: scrape.stats.success, color: "text-green-500" },
          { label: "Failed", value: scrape.stats.failed, color: "text-red-500" },
        ]} />
      )}
      {scrape.isScraping && scrape.stats.total > 0 && (
        <ProgressBar dark={dark} t={t} processed={scrape.stats.done} total={scrape.stats.total} colorClass={config.progressColor} />
      )}
      <CityResultsMatrix t={t} results={scrape.results} orderedIds={scrape.orderedIds} config={config} onDownloadCSV={scrape.downloadCSV} sheetProducts={scrape.sheetProducts} />
    </main>
  );
}
