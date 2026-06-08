"use client";

import { useEffect, useState } from "react";
import type { PageKey } from "@/types/price-scraper";

export function useHashPage() {
  const [page, setPage] = useState<PageKey>("home");

  useEffect(() => {
    const onHash = () => {
      const h = window.location.hash;
      if (h === "#/scheduler") setPage("scheduler");
      else if (h === "#/flipkart") setPage("flipkart");
      else if (h === "#/blinkit") setPage("blinkit");
      else if (h === "#/zepto") setPage("zepto");
      else if (h === "#/instamart") setPage("instamart");
      else setPage("home");
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return { page };
}
