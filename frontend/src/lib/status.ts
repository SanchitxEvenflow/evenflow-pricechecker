export function badgeClassForStatus(status: string) {
  const colors: Record<string, string> = {
    success: "bg-green-500/10 text-green-500", available: "bg-green-500/10 text-green-500",
    price_found: "bg-green-500/10 text-green-500", processing: "bg-blue-500/10 text-blue-500",
    pending: "bg-neutral-500/10 text-neutral-400", in_progress: "bg-blue-500/10 text-blue-500",
    completed: "bg-green-500/10 text-green-500", error: "bg-red-500/10 text-red-500",
    failed: "bg-red-500/10 text-red-500", not_found: "bg-red-500/10 text-red-500",
    blocked: "bg-orange-500/10 text-orange-500", invalid_format: "bg-yellow-500/10 text-yellow-500",
    unavailable: "bg-neutral-500/10 text-neutral-400",
  };
  return colors[status] || "bg-neutral-500/10 text-neutral-400";
}

export function blinkitStatusColor(s: string) {
  if (s === "available") return "bg-green-500/15 text-green-400 border-green-500/30";
  if (s === "out_of_stock") return "bg-red-500/15 text-red-400 border-red-500/30";
  if (s === "unavailable") return "text-red-500 bg-red-500/10";
  return "text-neutral-500 bg-neutral-500/10";
}

export function flipkartMinutesStatusColor(s: string) {
  if (s === "available") return "text-green-500 bg-green-500/10";
  if (s === "out_of_stock") return "text-orange-500 bg-orange-500/10";
  if (s === "unserviceable") return "text-purple-500 bg-purple-500/10";
  if (s === "not_found") return "text-red-500 bg-red-500/10";
  if (s === "error") return "text-red-500 bg-red-500/10";
  if (s === "blocked") return "text-red-500 bg-red-500/10";
  if (s === "unavailable") return "text-red-500 bg-red-500/10";
  return "text-neutral-500 bg-neutral-500/10";
}

export function zeptoStatusColor(s: string) {
  if (s === "available") return "bg-green-500/15 text-green-400 border-green-500/30";
  if (s === "out_of_stock") return "bg-red-500/15 text-red-400 border-red-500/30";
  if (s === "unserviceable" || s === "not_found") return "bg-neutral-500/15 text-neutral-400 border-neutral-500/30";
  return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
}

export function instamartStatusColor(s: string) {
  if (s === "available") return "bg-green-500/15 text-green-400 border-green-500/30";
  if (s === "out_of_stock") return "bg-red-500/15 text-red-400 border-red-500/30";
  if (s === "unserviceable" || s === "not_found") return "bg-neutral-500/15 text-neutral-400 border-neutral-500/30";
  return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
}
