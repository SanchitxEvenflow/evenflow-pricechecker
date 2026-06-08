"use client";

import { ManualTriggerCard } from "@/components/scheduler/ManualTriggerCard";
import { RunHistoryTable } from "@/components/scheduler/RunHistoryTable";
import { SchedulerStatusCard } from "@/components/scheduler/SchedulerStatusCard";
import { SchedulerToast } from "@/components/scheduler/SchedulerToast";
import { formatIndiaDate } from "@/lib/format";
import { useSchedulerData } from "@/hooks/useSchedulerData";
import type { ThemeClasses } from "@/types/price-scraper";

export function SchedulerPage({ t, dark }: { t: ThemeClasses; dark: boolean }) {
  const scheduler = useSchedulerData();

  return (
    <main className="max-w-6xl mx-auto px-6 py-8 space-y-8">
      <SchedulerToast toast={scheduler.toast} onDismiss={() => scheduler.setToast(null)} />
      <ManualTriggerCard t={t} dark={dark} brand="amazon" status={scheduler.cronStatus} isTriggering={scheduler.isTriggering} onTrigger={scheduler.handleTrigger} />
      <ManualTriggerCard t={t} dark={dark} brand="blinkit" status={scheduler.blinkitStatus} isTriggering={scheduler.isBlinkitTriggering} onTrigger={scheduler.handleBlinkitTrigger} />
      <ManualTriggerCard t={t} dark={dark} brand="flipkart" status={scheduler.flipkartStatus} isTriggering={scheduler.isFlipkartTriggering} onTrigger={scheduler.handleFlipkartTrigger} />
      <ManualTriggerCard t={t} dark={dark} brand="zepto" status={scheduler.zeptoStatus} isTriggering={scheduler.isZeptoTriggering} onTrigger={scheduler.handleZeptoTrigger} />
      <ManualTriggerCard t={t} dark={dark} brand="instamart" status={scheduler.instamartStatus} isTriggering={scheduler.isInstamartTriggering} onTrigger={scheduler.handleInstamartTrigger} />
      <SchedulerStatusCard t={t} cronStatus={scheduler.cronStatus} formatDate={formatIndiaDate} />
      <RunHistoryTable t={t} logs={scheduler.logs} onRefresh={scheduler.fetchLogs} formatDate={formatIndiaDate} />
    </main>
  );
}
