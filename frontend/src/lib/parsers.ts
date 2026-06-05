export function parseUniqueUppercaseTokens(text: string) {
  const raw = text.split(/[\n,]+/).map(a => a.trim().toUpperCase()).filter(Boolean);
  const seen = new Set<string>();
  return raw.filter(a => { if (seen.has(a)) return false; seen.add(a); return true; });
}

export function parseUniqueTokens(text: string) {
  const raw = text.split(/[\n,]+/).map(a => a.trim()).filter(Boolean);
  const seen = new Set<string>();
  return raw.filter(a => { if (seen.has(a)) return false; seen.add(a); return true; });
}
