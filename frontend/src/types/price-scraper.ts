export interface RatingBreakdown {
  "5_star"?: string | null;
  "4_star"?: string | null;
  "3_star"?: string | null;
  "2_star"?: string | null;
  "1_star"?: string | null;
}

export interface ScrapeResult {
  asin: string;
  title?: string;
  price?: string;
  rating?: string;
  rating_count?: string;
  rating_breakdown?: RatingBreakdown | null;
  parent_node?: string | null;
  rank_value?: string | null;
  child_node?: string | null;
  sub_rank_value?: string | null;
  status: string;
  progress?: number;
  total?: number;
  done?: boolean;
}

export interface LogEntry {
  run_id: string;
  type: string;
  triggered_at: string;
  completed_at: string | null;
  total_asins: number;
  success_count: number;
  failed_count: number;
  sheet_tab: string | null;
  status: string;
  error?: string;
}

export interface CronStatus {
  is_running: boolean;
  last_run_at: string | null;
  last_run_tab: string | null;
  last_run_duration_seconds: number | null;
  last_run_processed: number | null;
  total: number | null;
  progress: number | null;
  next_run_at: string | null;
  scheduler_enabled?: boolean;
  error?: string | null;
}

export interface FlipkartScrapeResult {
  fsn: string;
  title?: string;
  price?: string;
  mrp?: string;
  discount?: string;
  rating?: string;
  rating_count?: string;
  fulfilled_by?: string;
  status: string;
  url?: string;
  resolved_url?: string;
  checked_at?: string;
  progress?: number;
  total?: number;
  done?: boolean;
}

export interface BlinkitResult {
  product_id: string;
  city: string;
  title?: string | null;
  price?: number | null;
  mrp?: number | null;
  status: string;
  is_sold_out?: boolean;
  url?: string;
  checked_at?: string;
}

export interface ZeptoResult {
  product_id: string;
  city: string;
  title?: string | null;
  price?: number | null;
  mrp?: number | null;
  status: string;
  error_message?: string;
  is_sold_out?: boolean;
  url?: string;
  checked_at?: string;
}

export interface InstamartResult {
  product_id: string;
  city: string;
  title?: string | null;
  price?: number | null;
  mrp?: number | null;
  status: string;
  error_message?: string;
  is_sold_out?: boolean;
  url?: string;
  checked_at?: string;
}

export interface FlipkartMinutesResult {
  product_id: string;
  city: string;
  title?: string | null;
  price?: number | null;
  mrp?: number | null;
  status: string;
  error_message?: string;
  is_sold_out?: boolean;
  url?: string;
  checked_at?: string;
}

export type PageKey = "home" | "flipkart" | "blinkit" | "zepto" | "instamart" | "flipkart_minutes" | "scheduler";

export interface ThemeClasses {
  bg: string;
  text: string;
  card: string;
  border: string;
  muted: string;
  thead: string;
  headerBg: string;
  input: string;
  btnSecondary: string;
}

export type SchedulerToast = { type: string; msg: string };

export type CityResult = BlinkitResult | ZeptoResult | InstamartResult | FlipkartMinutesResult;

export interface CityScrapeConfig<T extends CityResult> {
  brand: "blinkit" | "zepto" | "instamart" | "flipkart_minutes";
  cities: string[];
  endpoint: string;
  filenamePrefix: string;
  emptyInputError: string;
  headingBrandClass: string;
  headingBrandText: string;
  headingSuffix: string;
  description: string;
  placeholder: string;
  focusRingClass: string;
  buttonClass: string;
  buttonText: string;
  resultsTitle: string;
  progressColor: string;
  getCellLabel: (result: T) => string;
  statusColor: (status: string) => string;
}
