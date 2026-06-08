"use client";

import { useState } from "react";
import type { ThemeClasses } from "@/types/price-scraper";

export interface SheetProduct { id: string; title: string; brand: string; }

export function ProductPicker({ products, selectedIds, onToggle, loading, accentFocus, t, dark }: {
  products: SheetProduct[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  loading: boolean;
  accentFocus: string;
  t: ThemeClasses;
  dark: boolean;
}) {
  const [brandFilter, setBrandFilter] = useState("All Brands");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);

  const brands = [...new Set(products.map(p => p.brand).filter(Boolean))].sort();
  const filtered = products.filter(p =>
    (brandFilter === "All Brands" || p.brand === brandFilter) &&
    (!search || p.title.toLowerCase().includes(search.toLowerCase()) || p.id.toLowerCase().includes(search.toLowerCase())) &&
    !selectedIds.includes(p.id)
  );

  if (!loading && products.length === 0) return null;

  return (
    <div className="mb-5">
      <div className="flex items-center justify-between mb-2">
        <p className={`text-sm font-semibold ${t.text}`}>
          Pick from Sheet {loading && <span className={`text-xs font-normal ${t.muted}`}>(loading…)</span>}
        </p>
        {brands.length > 0 && (
          <select value={brandFilter} onChange={e => setBrandFilter(e.target.value)}
            className={`text-xs rounded-lg px-3 py-1.5 border focus:outline-none ${t.input}`}>
            <option value="All Brands">All Brands</option>
            {brands.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
        )}
      </div>

      <div className="relative">
        <input
          type="text"
          placeholder={loading ? "Loading products…" : `Search ${products.length} product${products.length !== 1 ? "s" : ""}…`}
          value={search}
          disabled={loading || products.length === 0}
          onChange={e => { setSearch(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          className={`w-full rounded-xl px-4 py-2.5 text-sm border focus:outline-none focus:ring-2 ${accentFocus} ${t.input}`}
        />
        {open && filtered.length > 0 && (
          <div className={`absolute z-20 w-full mt-1 rounded-xl border ${t.border} ${t.card} shadow-lg max-h-52 overflow-y-auto`}>
            {filtered.map(p => (
              <button key={p.id} onMouseDown={() => { onToggle(p.id); setSearch(""); setOpen(false); }}
                className={`w-full text-left px-4 py-2.5 flex items-center justify-between gap-3 ${dark ? "hover:bg-neutral-800" : "hover:bg-neutral-100"}`}>
                <div className="min-w-0">
                  <p className={`text-sm font-medium truncate ${t.text}`}>{p.title || p.id}</p>
                  {p.brand && <p className={`text-xs ${t.muted}`}>{p.brand}</p>}
                </div>
                <span className={`text-xs ${t.muted} font-mono shrink-0`}>{p.id}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedIds.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {selectedIds.map(id => {
            const p = products.find(x => x.id === id);
            return (
              <span key={id} className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium border ${dark ? "bg-neutral-800 border-neutral-700 text-neutral-200" : "bg-neutral-100 border-neutral-300 text-neutral-700"}`}>
                <span className="max-w-[200px] truncate">{p?.title || id}</span>
                <button onClick={() => onToggle(id)} className={`${t.muted} hover:text-red-400 transition-colors font-bold`}>×</button>
              </span>
            );
          })}
        </div>
      )}

      <div className="flex items-center gap-3 mt-4">
        <div className={`flex-1 border-t ${t.border}`} />
        <span className={`text-xs ${t.muted}`}>or paste IDs directly</span>
        <div className={`flex-1 border-t ${t.border}`} />
      </div>
    </div>
  );
}
