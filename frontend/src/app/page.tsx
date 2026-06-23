"use client";

import { AuthGuard } from "@/components/auth/AuthGuard";
import { AmazonManualPage } from "@/components/amazon/AmazonManualPage";
import { AppShell } from "@/components/layout/AppShell";
import { Header } from "@/components/layout/Header";
import { FlipkartManualPage } from "@/components/flipkart/FlipkartManualPage";
import { CityScrapePage } from "@/components/quick-commerce/CityScrapePage";
import { SchedulerPage } from "@/components/scheduler/SchedulerPage";
import { BLINKIT_CITIES, INSTAMART_CITIES, ZEPTO_CITIES, FLIPKART_MINUTES_CITIES } from "@/constants/cities";
import { useHashPage } from "@/hooks/useHashPage";
import { useTheme } from "@/hooks/useTheme";
import { blinkitStatusColor, instamartStatusColor, zeptoStatusColor, flipkartMinutesStatusColor } from "@/lib/status";
import type { BlinkitResult, CityScrapeConfig, InstamartResult, ZeptoResult, FlipkartMinutesResult } from "@/types/price-scraper";

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
  progressColor: "bg-[#F8CB46]",
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
  description: "Paste Zepto product IDs (one per line). Scrapes all 9 cities concurrently.",
  placeholder: "c834d3ca-...\n4f54ea62-...",
  focusRingClass: "focus:ring-[#FF3269]/50",
  buttonClass: "bg-[#FF3269] hover:bg-[#e02b5c] text-white",
  buttonText: "Scrape All Cities",
  resultsTitle: `Results — ${ZEPTO_CITIES.length} Cities`,
  progressColor: "bg-[#FF3269]",
  getCellLabel: result => (result.error_message || result.status).replace(/_/g, " "),
  statusColor: zeptoStatusColor,
};

const instamartConfig: CityScrapeConfig<InstamartResult> = {
  brand: "instamart",
  cities: INSTAMART_CITIES,
  endpoint: "/price/instamart/all-cities",
  filenamePrefix: "instamart",
  emptyInputError: "Enter at least one product ID",
  headingBrandClass: "text-[#FC8019]",
  headingBrandText: "instamart",
  headingSuffix: "All Cities Scrape",
  description: "Paste Instamart product IDs (one per line). Scrapes all 9 locations concurrently.",
  placeholder: "54ZJRDYZYL\n...",
  focusRingClass: "focus:ring-[#FC8019]/50",
  buttonClass: "bg-[#FC8019] hover:bg-[#e06b0b] text-white",
  buttonText: "Scrape All Cities",
  resultsTitle: `Results — ${INSTAMART_CITIES.length} Cities`,
  progressColor: "bg-[#FC8019]",
  getCellLabel: result => (result.error_message || result.status).replace(/_/g, " "),
  statusColor: instamartStatusColor,
};

const flipkartMinutesConfig: CityScrapeConfig<FlipkartMinutesResult> = {
  brand: "flipkart_minutes",
  cities: FLIPKART_MINUTES_CITIES,
  endpoint: "/price/flipkart-minutes/all-cities",
  filenamePrefix: "fk_minutes",
  emptyInputError: "Enter at least one product ID",
  headingBrandClass: "text-[#2874F0]",
  headingBrandText: "flipkart minutes",
  headingSuffix: "All Cities Scrape",
  description: "Paste Flipkart Minutes product IDs (one per line). Scrapes all locations concurrently.",
  placeholder: "SCMHHUF8MCJY8H4G\n...",
  focusRingClass: "focus:ring-[#2874F0]/50",
  buttonClass: "bg-[#2874F0] hover:bg-[#1a5cbd] text-white",
  buttonText: "Scrape All Cities",
  resultsTitle: `Results — ${FLIPKART_MINUTES_CITIES.length} Cities`,
  progressColor: "bg-[#2874F0]",
  getCellLabel: result => (result.error_message || result.status).replace(/_/g, " "),
  statusColor: flipkartMinutesStatusColor,
};

export default function App() {
  const { dark, setDark, t } = useTheme();
  const { page } = useHashPage();

  return (
    <AuthGuard>
    <AppShell dark={dark} t={t}>
      <Header dark={dark} setDark={setDark} page={page} />
      {page === "scheduler" ? (
        <SchedulerPage t={t} dark={dark} />
      ) : page === "flipkart" ? (
        <FlipkartManualPage t={t} dark={dark} />
      ) : page === "blinkit" ? (
        <CityScrapePage key="blinkit" t={t} dark={dark} config={blinkitConfig} />
      ) : page === "zepto" ? (
        <CityScrapePage key="zepto" t={t} dark={dark} config={zeptoConfig} />
      ) : page === "instamart" ? (
        <CityScrapePage key="instamart" t={t} dark={dark} config={instamartConfig} />
      ) : page === "flipkart_minutes" ? (
        <CityScrapePage key="flipkart_minutes" t={t} dark={dark} config={flipkartMinutesConfig} />
      ) : (
        <AmazonManualPage t={t} dark={dark} />
      )}
    </AppShell>
    </AuthGuard>
  );
}
