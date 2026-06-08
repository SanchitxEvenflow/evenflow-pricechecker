"use client";

import { AmazonInputCard } from "@/components/amazon/AmazonInputCard";
import { AmazonResultsTable } from "@/components/amazon/AmazonResultsTable";
import { ErrorBanner } from "@/components/shared/ErrorBanner";
import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatsGrid } from "@/components/shared/StatsGrid";
import { useAmazonManualScrape } from "@/hooks/useAmazonManualScrape";
import type { ThemeClasses } from "@/types/price-scraper";

export function AmazonManualPage({ t, dark }: { t: ThemeClasses; dark: boolean }) {
  const scrape = useAmazonManualScrape();
  const asinCount = scrape.parseAsins(scrape.asinText).length;

  return (
    <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
      <ErrorBanner error={scrape.error} />
      <AmazonInputCard t={t} asinText={scrape.asinText} setAsinText={scrape.setAsinText} isScraping={scrape.isScraping} asinCount={asinCount} onScrape={scrape.handleScrape} />
      {scrape.stats.total > 0 && (
        <StatsGrid t={t} columnsClass="grid-cols-2 md:grid-cols-5" items={[
          { label: "Total", value: scrape.stats.total, color: "" },
          { label: "Processed", value: scrape.stats.processed, color: "" },
          { label: "Remaining", value: scrape.stats.remaining, color: "text-yellow-500" },
          { label: "Success", value: scrape.stats.success, color: "text-green-500" },
          { label: "Failed", value: scrape.stats.failed, color: "text-red-500" },
        ]} />
      )}
      {scrape.isScraping && scrape.stats.total > 0 && <ProgressBar dark={dark} t={t} processed={scrape.stats.processed} total={scrape.stats.total} colorClass="bg-[#FF9900]" />}
      <AmazonResultsTable t={t} results={scrape.results} onDownloadCSV={scrape.downloadCSV} />
    </main>
  );
}
