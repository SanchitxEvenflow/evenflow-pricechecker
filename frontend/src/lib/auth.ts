const TOKEN_KEY = "pc_token";
const AUTH_COOKIE = "pc_auth";
const TOKEN_MAX_AGE = 60 * 60 * 24; // 24h, matches backend

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
  document.cookie = `${AUTH_COOKIE}=1; path=/; max-age=${TOKEN_MAX_AGE}; SameSite=Lax`;
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  document.cookie = `${AUTH_COOKIE}=; path=/; max-age=0`;
}
