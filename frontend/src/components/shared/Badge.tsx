import { badgeClassForStatus } from "@/lib/status";

export function Badge({ status }: { status: string }) {
  const c = badgeClassForStatus(status);
  return <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold capitalize ${c}`}>{status.replace("_", " ")}</span>;
}
