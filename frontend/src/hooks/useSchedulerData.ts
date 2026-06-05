"use client";

import { useCallback, useEffect, useState } from "react";
import { API } from "@/lib/api";
import { errorMessage } from "@/lib/errors";
import type { CronStatus, LogEntry, SchedulerToast } from "@/types/price-scraper";

export function useSchedulerData() {
  const [cronStatus, setCronStatus] = useState<CronStatus | null>(null);
  const [blinkitStatus, setBlinkitStatus] = useState<CronStatus | null>(null);
  const [flipkartStatus, setFlipkartStatus] = useState<CronStatus | null>(null);
  const [zeptoStatus, setZeptoStatus] = useState<CronStatus | null>(null);
  const [isTriggering, setIsTriggering] = useState(false);
  const [isBlinkitTriggering, setIsBlinkitTriggering] = useState(false);
  const [isFlipkartTriggering, setIsFlipkartTriggering] = useState(false);
  const [isZeptoTriggering, setIsZeptoTriggering] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [toast, setToast] = useState<SchedulerToast | null>(null);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/amazon/api/logs`);
      const data = await res.json();
      if (data.logs) setLogs(data.logs);
    } catch {}
  }, []);

  const fetchCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/amazon/cron-status`);
      if (res.ok) setCronStatus(await res.json());
    } catch {}
  }, []);

  const fetchBlinkitCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/price/blinkit/cron-status`);
      if (res.ok) setBlinkitStatus(await res.json());
    } catch {}
  }, []);

  const fetchFlipkartCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/sheets/flipkart/cron-status`);
      if (res.ok) setFlipkartStatus(await res.json());
    } catch {}
  }, []);

  const fetchZeptoCron = useCallback(async () => {
    try {
      const res = await fetch(`${API}/price/zepto/cron-status`);
      if (res.ok) setZeptoStatus(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    const initial = setTimeout(() => { fetchCron(); fetchBlinkitCron(); fetchFlipkartCron(); fetchZeptoCron(); fetchLogs(); }, 0);
    const i1 = setInterval(fetchCron, 10000);
    const i2 = setInterval(fetchLogs, 30000);
    const i3 = setInterval(fetchBlinkitCron, 10000);
    const i4 = setInterval(fetchFlipkartCron, 10000);
    const i5 = setInterval(fetchZeptoCron, 10000);
    return () => { clearTimeout(initial); clearInterval(i1); clearInterval(i2); clearInterval(i3); clearInterval(i4); clearInterval(i5); };
  }, [fetchCron, fetchBlinkitCron, fetchFlipkartCron, fetchZeptoCron, fetchLogs]);

  const handleTrigger = async () => {
    setIsTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/sheets/amazon/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Amazon manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger" });
      }
    } catch (e: unknown) {
      setToast({ type: "error", msg: errorMessage(e) });
    } finally {
      setIsTriggering(false);
    }
  };

  const handleBlinkitTrigger = async () => {
    setIsBlinkitTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/price/blinkit/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Blinkit manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger Blinkit scrape" });
      }
    } catch (e: unknown) {
      setToast({ type: "error", msg: errorMessage(e) });
    } finally {
      setIsBlinkitTriggering(false);
    }
  };

  const handleFlipkartTrigger = async () => {
    setIsFlipkartTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/sheets/flipkart/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Flipkart manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger Flipkart scrape" });
      }
    } catch (e: unknown) {
      setToast({ type: "error", msg: errorMessage(e) });
    } finally {
      setIsFlipkartTriggering(false);
    }
  };

  const handleZeptoTrigger = async () => {
    setIsZeptoTriggering(true);
    setToast(null);
    try {
      const res = await fetch(`${API}/price/zepto/api/trigger-manual-scheduler`, { method: "POST" });
      if (res.ok) {
        setToast({ type: "success", msg: "Zepto manual scrape triggered! Check progress below." });
        setTimeout(fetchLogs, 2000);
      } else {
        const data = await res.json();
        setToast({ type: "error", msg: data.detail || "Failed to trigger Zepto scrape" });
      }
    } catch (e: unknown) {
      setToast({ type: "error", msg: errorMessage(e) });
    } finally {
      setIsZeptoTriggering(false);
    }
  };

  return {
    cronStatus,
    blinkitStatus,
    flipkartStatus,
    zeptoStatus,
    isTriggering,
    isBlinkitTriggering,
    isFlipkartTriggering,
    isZeptoTriggering,
    logs,
    toast,
    setToast,
    fetchLogs,
    handleTrigger,
    handleBlinkitTrigger,
    handleFlipkartTrigger,
    handleZeptoTrigger,
  };
}
