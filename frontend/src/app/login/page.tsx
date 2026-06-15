"use client";

import { FormEvent, useEffect, useState } from "react";
import Image from "next/image";
import { API } from "@/lib/api";
import { getToken, setToken } from "@/lib/auth";

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";
const USERNAME = "evenflowbrands-pricescraper";

export default function LoginPage() {
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (AUTH_ENABLED && getToken()) window.location.replace("/");
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: USERNAME, password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "Login failed");
      }
      const { access_token } = await res.json();
      setToken(access_token);
      window.location.href = "/";
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-950 text-neutral-100 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center flex flex-col items-center">
          <Image src="/logo.png" alt="Evenflow Brands" width={100} height={50} className="rounded object-contain mb-4" unoptimized />
          <h1 className="text-3xl font-extrabold tracking-tight text-neutral-100">Evenflow Brands</h1>
          <p className="mt-1 text-lg font-semibold text-neutral-400">Price Scraper</p>
          <p className="mt-2 text-sm text-neutral-500">Sign in to continue</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl border border-neutral-800 bg-neutral-900 p-6">
          {error && (
            <div className="rounded-lg bg-red-950/50 border border-red-800 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-neutral-300 mb-1.5">
              Username
            </label>
            <p className="rounded-xl border border-neutral-700 bg-neutral-800/50 px-3 py-2 text-neutral-400 text-sm">
              {USERNAME}
            </p>
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-neutral-300 mb-1.5">
              Password
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={e => setPassword(e.target.value)}
                className="w-full rounded-xl border border-neutral-700 bg-neutral-800 px-3 py-2 pr-10 text-white placeholder-neutral-500 focus:outline-none focus:ring-2 focus:ring-[#FF9900]/50"
              />
              <button
                type="button"
                onClick={() => setShowPassword(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-200 transition-colors"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-[#FF9900] hover:bg-[#e68a00] disabled:opacity-50 text-black font-medium py-2.5 transition-colors"
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
