import { clearAuth, getToken } from "@/lib/auth";

export const API = process.env.NEXT_PUBLIC_API_URL || "";

export async function authFetch(input: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(input, { ...init, headers });

  if (res.status === 401 && typeof window !== "undefined") {
    clearAuth();
    window.location.href = "/login";
  }

  return res;
}
