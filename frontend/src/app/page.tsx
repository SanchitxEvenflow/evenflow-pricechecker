"use client";

import { AmazonManualPage } from "@/components/amazon/AmazonManualPage";
import { AppShell } from "@/components/layout/AppShell";
import { Header } from "@/components/layout/Header";
import { FlipkartManualPage } from "@/components/flipkart/FlipkartManualPage";
import { CityScrapePage } from "@/components/quick-commerce/CityScrapePage";
import { SchedulerPage } from "@/components/scheduler/SchedulerPage";
import { BLINKIT_CITIES, ZEPTO_CITIES } from "@/constants/cities";
import { useHashPage } from "@/hooks/useHashPage";
import { useTheme } from "@/hooks/useTheme";
import { blinkitStatusColor, zeptoStatusColor } from "@/lib/status";
import type { BlinkitResult, CityScrapeConfig, ZeptoResult } from "@/types/price-scraper";

const blinkitConfig: CityScrapeConfig<BlinkitResult> = {
  brand: "blinkit",
  cities: BLINKIT_CITIES,
  endpoint: "/price/blinkit/all-cities",
  filenamePrefix: "blinkit",
  emptyInputError: "Enter at least one product ID",
  headingBrandClass: "text-[#F8CB46]",
  headingBrandText: "blinkit",
  headingSuffix: "All Cities Scrape",
  description: "Paste Blinkit product IDs (one per line). Scrapes all 10 cities concurrently.",
  placeholder: "12345\n67890",
  focusRingClass: "focus:ring-[#F8CB46]/50",
  buttonClass: "bg-[#F8CB46] hover:bg-[#e5b93d] text-black",
  buttonText: "Scrape All Cities",
  resultsTitle: `Results — ${BLINKIT_CITIES.length} Cities`,
  totalRequestsMultiplierText: "10",
  getCellLabel: result => result.status.replace("_", " "),
  statusColor: blinkitStatusColor,
};

const zeptoConfig: CityScrapeConfig<ZeptoResult> = {
  brand: "zepto",
  cities: ZEPTO_CITIES,
  endpoint: "/price/zepto/all-cities",
  filenamePrefix: "zepto",
  emptyInputError: "Enter at least one product ID",
  headingBrandClass: "text-[#FF3269]",
  headingBrandText: "zepto",
  headingSuffix: "All Cities Scrape",
  description: "Paste Zepto product IDs (one per line). Scrapes all 10 cities concurrently.",
  placeholder: "c834d3ca-...\n4f54ea62-...",
  focusRingClass: "focus:ring-[#FF3269]/50",
  buttonClass: "bg-[#FF3269] hover:bg-[#e02b5c] text-white",
  buttonText: "Scrape All Cities",
  resultsTitle: `Results — ${ZEPTO_CITIES.length} Cities`,
  totalRequestsMultiplierText: "10",
  getCellLabel: result => (result.error_message || result.status).replace(/_/g, " "),
  statusColor: zeptoStatusColor,
};

export default function App() {
  const { dark, setDark, t } = useTheme();
  const { page } = useHashPage();

  return (
    <AppShell dark={dark} t={t}>
      <Header dark={dark} setDark={setDark} t={t} page={page} />
      {page === "scheduler" ? (
        <SchedulerPage t={t} dark={dark} />
      ) : page === "flipkart" ? (
        <FlipkartManualPage t={t} dark={dark} />
      ) : page === "blinkit" ? (
        <CityScrapePage t={t} dark={dark} config={blinkitConfig} />
      ) : page === "zepto" ? (
        <CityScrapePage t={t} dark={dark} config={zeptoConfig} />
      ) : (
        <AmazonManualPage t={t} dark={dark} />
      )}
    </AppShell>
  );
}
