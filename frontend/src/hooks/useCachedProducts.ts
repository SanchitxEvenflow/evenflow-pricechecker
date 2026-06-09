"use client";

import { useState, useEffect } from "react";

// Global cache outside the component to persist across re-mounts
const productCache: Record<string, any[]> = {};
const productLoadingCache: Record<string, Promise<any[]> | undefined> = {};

export function useCachedProducts(url: string) {
  // Initialize with cached data if available to avoid flicker
  const [data, setData] = useState<any[]>(productCache[url] || []);
  // If data is already cached, loading starts as false
  const [loading, setLoading] = useState<boolean>(!productCache[url]);

  useEffect(() => {
    // If it's already cached and loaded, no need to fetch again
    if (productCache[url]) {
      setData(productCache[url]);
      setLoading(false);
      return;
    }

    // If a request is already in-flight for this URL, wait for it
    if (productLoadingCache[url]) {
      setLoading(true);
      productLoadingCache[url].then((res) => {
        setData(res);
        setLoading(false);
      }).catch(() => {
        setLoading(false);
      });
      return;
    }

    // Start a new request
    setLoading(true);
    const promise = fetch(url)
      .then(r => r.ok ? r.json() : [])
      .then(resData => {
        const result = Array.isArray(resData) ? resData : [];
        productCache[url] = result; // Save to global cache
        return result;
      });

    productLoadingCache[url] = promise; // Save promise to prevent duplicate requests

    promise.then((res) => {
      setData(res);
      setLoading(false);
    }).catch(() => {
      setLoading(false);
    });

  }, [url]);

  return { data, loading };
}
