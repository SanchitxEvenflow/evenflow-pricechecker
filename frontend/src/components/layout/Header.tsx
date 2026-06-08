"use client";

import Image from "next/image";
import type { Dispatch, SetStateAction } from "react";
import type { PageKey, ThemeClasses } from "@/types/price-scraper";

export function Header({ dark, setDark, page }: { dark: boolean; setDark: Dispatch<SetStateAction<boolean>>; t: ThemeClasses; page: PageKey }) {
  return (
    <header className="sticky top-0 z-20 border-b border-neutral-800 bg-neutral-950 text-neutral-100">
      <div className="max-w-6xl mx-auto px-6 py-4 flex justify-between items-center">
        <a href="#/" className="flex items-center space-x-3 hover:opacity-80 transition-opacity">
          <Image src="/logo.png" alt="Logo" width={90} height={45} className="rounded object-contain" unoptimized />
          <h1 className="text-xl font-bold tracking-tight text-neutral-100">Price Scraper</h1>
        </a>
        <div className="flex items-center gap-3">
          <a href="#/" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "home" ? "bg-[#FF9900] text-black" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Amazon
          </a>
          <a href="#/flipkart" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "flipkart" ? "bg-[#2874F0] text-white" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Flipkart
          </a>
          <a href="#/blinkit" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "blinkit" ? "bg-[#F8CB46] text-black" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Blinkit
          </a>
          <a href="#/zepto" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "zepto" ? "bg-[#FF3269] text-white" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Zepto
          </a>
          <a href="#/instamart" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "instamart" ? "bg-[#FC8019] text-white" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Instamart
          </a>
          <a href="#/scheduler" className={`px-4 py-2 rounded-xl text-sm font-medium transition-all ${page === "scheduler" ? "bg-[#FF9900] text-black" : "bg-neutral-800 hover:bg-neutral-700 text-white"}`}>
            Scheduler
          </a>
          <button onClick={() => setDark(!dark)} className="p-2 rounded-full border border-neutral-800 hover:opacity-80 transition-opacity" aria-label="Toggle Theme">
            {dark ? (
              <svg className="w-5 h-5 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
            ) : (
              <svg className="w-5 h-5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
