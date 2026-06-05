import { Badge } from "@/components/shared/Badge";
import type { CronStatus, ThemeClasses } from "@/types/price-scraper";

export function SchedulerStatusCard({ t, cronStatus, formatDate }: { t: ThemeClasses; cronStatus: CronStatus | null; formatDate: (iso: string) => string }) {
  return (
    <div className={`${t.card} border ${t.border} rounded-2xl p-6 shadow-sm`}>
      <div className="flex items-center justify-between mb-3">
        <p className={`text-xs font-semibold uppercase tracking-wider ${t.muted}`}>Scheduler Status</p>
        <Badge status={cronStatus?.scheduler_enabled === false ? "disabled" : cronStatus?.is_running ? "in_progress" : "completed"} />
      </div>
      {cronStatus && (
        <div className="space-y-2 text-sm">
          {cronStatus.last_run_tab && <div className="flex justify-between"><span className={t.muted}>Last tab</span><span className="font-mono text-xs">{cronStatus.last_run_tab}</span></div>}
          {cronStatus.last_run_at && <div className="flex justify-between"><span className={t.muted}>Started</span><span>{formatDate(cronStatus.last_run_at)}</span></div>}
          {cronStatus.last_run_duration_seconds != null && <div className="flex justify-between"><span className={t.muted}>Duration</span><span>{Math.floor(cronStatus.last_run_duration_seconds / 60)}m {cronStatus.last_run_duration_seconds % 60}s</span></div>}
          {cronStatus.next_run_at && <div className="flex justify-between"><span className={t.muted}>Next run</span><span>{formatDate(cronStatus.next_run_at)}</span></div>}
        </div>
      )}
    </div>
  );
}
