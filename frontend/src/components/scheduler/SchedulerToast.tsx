import type { SchedulerToast as Toast } from "@/types/price-scraper";

export function SchedulerToast({ toast, onDismiss }: { toast: Toast | null; onDismiss: () => void }) {
  if (!toast) return null;
  return (
    <div className={`p-4 border rounded-xl text-sm font-medium flex items-center justify-between ${toast.type === "success" ? "bg-green-500/10 border-green-500/30 text-green-500" : "bg-red-500/10 border-red-500/30 text-red-500"}`}>
      <span>{toast.msg}</span>
      <button onClick={onDismiss} className="ml-4 hover:opacity-60">✕</button>
    </div>
  );
}
