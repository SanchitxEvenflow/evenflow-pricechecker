"use client";

import { useCallback, useEffect, useState } from "react";
import { API, authFetch } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CronStatus, LogEntry, SchedulerToast } from "@/types/price-scraper";

export function useSchedulerData() {
  const [cronStatus, setCronStatus] = useState<CronStatus | null>(null);
  const [blinkitStatus, setBlinkitStatus] = useState<CronStatus | null>(null);
  const [flipkartStatus, setFlipkartStatus] = useState<CronStatus | null>(null);
  const [zeptoStatus, setZeptoStatus] = useState<CronStatus | null>(null);
  const [instamartStatus, setInstamartStatus] = useState<CronStatus | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [isBlinkitTriggering, setIsBlinkitTriggering] = useState(false);
  const [isFlipkartTriggering, setIsFlipkartTriggering] = useState(false);
  const [isZeptoTriggering, setIsZeptoTriggering] = useState(false);
  const [isInstamartTriggering, setIsInstamartTriggering] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [toast, setToast] = useState<SchedulerToast | null>(null);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/sheets/amazon/api/logs`);
      const data = await res.json();
      if (data.logs) setLogs(data.logs);
    } catch {}
  }, []);

  const fetchAllStatus = useCallback(async () => {
    try {
      const res = await authFetch(`${API}/cron-status/all`);
      if (res.ok) {
        const data = await res.json();
        setCronStatus(data.amazon);
        setFlipkartStatus(data.flipkart);
        setBlinkitStatus(data.blinkit);
        setZeptoStatus(data.zepto);
        setInstamartStatus(data.instamart);
      }
    } catch {}
  }, []);

  useEffect(() => {
    const initial = setTimeout(() => { fetchAllStatus(); fetchLogs(); }, 0);
    const i1 = setInterval(fetchAllStatus, 10000);
    const i2 = setInterval(fetchLogs, 30000);
    return () => { clearTimeout(initial); clearInterval(i1); clearInterval(i2); };
  }, [fetchAllStatus, fetchLogs]);

  const makeTrigger = (
    endpoint: string,
    setTriggering: (val: boolean) => void,
    successMsg: string
  ) => async () => {
    setTriggering(true);
    setToast(null);
    try {
      const res = await authFetch(`${API}${endpoint}`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: successMsg });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger scrape" });
      }
    } catch (e: unknown) {
      setToast({ type: "error", msg: errorMessage(e) });
    } finally {
      setTriggering(false);
    }
  };

  const handleTrigger = makeTrigger("/sheets/amazon/api/trigger-manual-scheduler", setIsTriggering, "Amazon manual scrape triggered! Check progress below.");
  const handleBlinkitTrigger = makeTrigger("/price/blinkit/api/trigger-manual-scheduler", setIsBlinkitTriggering, "Blinkit manual scrape triggered! Check progress below.");
  const handleFlipkartTrigger = makeTrigger("/sheets/flipkart/api/trigger-manual-scheduler", setIsFlipkartTriggering, "Flipkart manual scrape triggered! Check progress below.");
  const handleZeptoTrigger = makeTrigger("/price/zepto/api/trigger-manual-scheduler", setIsZeptoTriggering, "Zepto manual scrape triggered! Check progress below.");
  const handleInstamartTrigger = makeTrigger("/price/instamart/api/trigger-manual-scheduler", setIsInstamartTriggering, "Instamart manual scrape triggered! Check progress below.");

  return {
    cronStatus,
    blinkitStatus,
    flipkartStatus,
    zeptoStatus,
    instamartStatus,
    isTriggering,
    isBlinkitTriggering,
    isFlipkartTriggering,
    isZeptoTriggering,
    isInstamartTriggering,
    logs,
    toast,
    setToast,
    fetchLogs,
    handleTrigger,
    handleBlinkitTrigger,
    handleFlipkartTrigger,
    handleZeptoTrigger,
    handleInstamartTrigger,
  };
}
