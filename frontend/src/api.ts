// ── Type definitions matching backend schemas ──

export interface UserInfo {
  id: number;
  name: string;
}

export interface AccountInfo {
  id: number;
  name: string;
  account_type: string;
}

export interface AccountCreate {
  name: string;
  account_type: string;
}

export interface UnderlyingStatus {
  ticker: string;
  name: string | null;
  initial_price: number;
  coupon_barrier_price: number;
  downside_barrier_price: number;
  current_price: number | null;
  pct_of_initial: number | null;
  above_coupon_barrier: boolean | null;
  above_downside_barrier: boolean | null;
}

export interface InstrumentSummary {
  cusip: string;
  issuer: string;
  product_type: string | null;
  coupon_rate_annual: number;
  coupon_barrier_pct: number;
  downside_barrier_pct: number;
  pricing_date: string;
  maturity_date: string;
  status: string;
  principal: number | null;
  coupons_received: number;
  coupons_missed: number;
  total_coupon_income: number;
  call_date: string | null;
}

export interface InstrumentDetail extends InstrumentSummary {
  coupon_rate_monthly: number;
  autocall_barrier_pct: number;
  underlyings: UnderlyingStatus[];
  next_valuation_date: string | null;
}

export interface PortfolioSummary {
  total_principal: number;
  total_coupon_income: number;
  active_instruments: number;
  called_instruments: number;
  upcoming_valuation_dates: UpcomingDate[];
}

export interface UpcomingDate {
  cusip: string;
  issuer: string;
  date: string;
  autocall_eligible: boolean;
  sequence_number: number;
  is_paid: boolean | null;
}

export interface BarrierStatus {
  cusip: string;
  issuer: string;
  ticker: string;
  initial_price: number;
  coupon_barrier_price: number;
  downside_barrier_price: number;
  current_price: number | null;
  pct_of_initial: number | null;
  distance_to_coupon_barrier_pct: number | null;
  distance_to_downside_barrier_pct: number | null;
}

export interface CouponUnderlyingDetail {
  ticker: string;
  close_price: number;
  initial_price: number;
  pct_of_initial: number;
  coupon_barrier_price: number;
  actual_price_date: string;
}

export interface CouponCalendarEntry {
  cusip: string;
  issuer: string;
  date: string;
  sequence_number: number;
  status: string;
  coupon_amount: number | null;
  worst_performer_ticker: string | null;
  worst_performer_pct: number | null;
  details: CouponUnderlyingDetail[] | null;
}

export interface PerformanceMetrics {
  total_principal: number;
  total_coupon_income: number;
  total_return_pct: number;
  annualized_twr: number | null;
  xirr: number | null;
  holding_period_days: number;
}

export interface SpyComparison {
  portfolio_total_return_pct: number;
  spy_total_return_pct: number;
  alpha_pct: number;
  portfolio_annualized: number | null;
  spy_annualized: number | null;
}

export interface ChartDataPoint {
  date: string;
  portfolio_value: number;
  spy_value: number | null;
}

export interface TaxComparison {
  gross_coupon_income: number;
  federal_tax_on_coupons: number;
  state_tax_on_coupons: number;
  net_coupon_income: number;
  effective_coupon_tax_rate: number;
  spy_gross_return_dollars: number;
  spy_federal_tax: number;
  spy_state_tax: number;
  spy_net_return_dollars: number;
  spy_effective_tax_rate: number;
  net_advantage: number;
  tax_drag_pct: number;
}

export interface RefreshResult {
  prices_updated: number;
  coupons_evaluated: number;
  autocalls_evaluated: number;
}

// ── Current user tracking ──

let _currentUserId: number | null = null;
let _currentAccountIds: number[] | null = null;

export function setCurrentUserId(id: number | null) {
  _currentUserId = id;
}

export function setCurrentAccountIds(ids: number[] | null) {
  _currentAccountIds = ids;
}

function userHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (_currentUserId != null) {
    headers['X-User-Id'] = String(_currentUserId);
  }
  if (_currentAccountIds != null) {
    headers['X-Account-Ids'] = _currentAccountIds.join(',');
  }
  return headers;
}

// ── Fetch helpers ──

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: userHeaders() });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

// ── User API ──

export async function fetchUsers(): Promise<UserInfo[]> {
  // User endpoints don't need X-User-Id header
  const res = await fetch('/api/users/');
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

export async function createUser(name: string): Promise<UserInfo> {
  const res = await fetch('/api/users/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

// ── Account API ──

export async function fetchAccounts(): Promise<AccountInfo[]> {
  return fetchJson('/api/accounts/');
}

export async function createAccount(name: string, accountType: string): Promise<AccountInfo> {
  const res = await fetch('/api/accounts/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...userHeaders() },
    body: JSON.stringify({ name, account_type: accountType }),
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

// ── Data API ──

export function fetchInstruments(): Promise<InstrumentSummary[]> {
  return fetchJson('/api/instruments/');
}

export function fetchInstrumentDetail(cusip: string): Promise<InstrumentDetail> {
  return fetchJson(`/api/instruments/${cusip}`);
}

export function fetchDashboardSummary(): Promise<PortfolioSummary> {
  return fetchJson('/api/dashboard/summary');
}

export function fetchBarrierStatus(): Promise<BarrierStatus[]> {
  return fetchJson('/api/dashboard/barrier-status');
}

export function fetchCouponCalendar(): Promise<CouponCalendarEntry[]> {
  return fetchJson('/api/coupons/calendar');
}

export function fetchPerformanceMetrics(): Promise<PerformanceMetrics> {
  return fetchJson('/api/performance/portfolio');
}

export function fetchSpyComparison(): Promise<SpyComparison> {
  return fetchJson('/api/performance/vs-spy');
}

export function fetchChartData(): Promise<ChartDataPoint[]> {
  return fetchJson('/api/performance/chart-data');
}

export function fetchTaxComparison(
  ordinaryRate?: number,
  ltcgRate?: number,
  stateRate?: number,
  spyTaxTreatment?: string,
): Promise<TaxComparison> {
  const params = new URLSearchParams();
  if (ordinaryRate !== undefined) params.set('ordinary_rate', ordinaryRate.toString());
  if (ltcgRate !== undefined) params.set('ltcg_rate', ltcgRate.toString());
  if (stateRate !== undefined) params.set('state_rate', stateRate.toString());
  if (spyTaxTreatment) params.set('spy_tax_treatment', spyTaxTreatment);
  const qs = params.toString();
  return fetchJson(`/api/performance/tax-comparison${qs ? `?${qs}` : ''}`);
}

export async function postRefresh(): Promise<RefreshResult> {
  const res = await fetch('/api/refresh/', {
    method: 'POST',
    headers: userHeaders(),
  });
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

// ── Upload API ──

export interface ParsedUnderlying {
  ticker: string;
  name: string | null;
  initial_price: number | null; // null on preliminary supplements
}

export interface ParsedValuationDate {
  date: string;
  autocall_eligible: boolean;
  sequence_number: number;
}

export interface ParsedInstrumentData {
  cusip: string;
  issuer: string;
  product_type: string | null;
  coupon_rate_annual: number;
  coupon_rate_monthly: number;
  coupon_barrier_pct: number;
  downside_barrier_pct: number;
  autocall_barrier_pct: number;
  pricing_date: string;
  maturity_date: string;
  underlyings: ParsedUnderlying[];
  valuation_dates: ParsedValuationDate[];
}

export interface ParsedFile {
  filename: string;
  parsed: ParsedInstrumentData | null;
  error: string | null;
  existing_cusip: boolean;
  preliminary: boolean; // committing adds a Modeling candidate, not a position
}

export interface CommitItem {
  parsed: ParsedInstrumentData;
  principal: number;
  filename?: string | null;
}

export interface CommitResultItem {
  filename: string | null;
  cusip: string;
  status: 'added' | 'position_added' | 'candidate_added' | 'error';
  message: string | null;
  prices_backfilled: Record<string, number>;
}

export async function parsePdfs(files: File[]): Promise<ParsedFile[]> {
  const form = new FormData();
  for (const f of files) form.append('files', f, f.name);
  const res = await fetch('/api/upload/parse', {
    method: 'POST',
    headers: userHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  const data: { files: ParsedFile[] } = await res.json();
  return data.files;
}

export async function commitInstruments(
  accountId: number,
  items: CommitItem[],
): Promise<CommitResultItem[]> {
  const res = await fetch('/api/upload/commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...userHeaders() },
    body: JSON.stringify({ account_id: accountId, items }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch { /* ignore */ }
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  const data: { results: CommitResultItem[] } = await res.json();
  return data.results;
}

// ── Candidates / Modeling API ──

export interface CandidateOffering {
  cusip: string;
  issuer: string;
  tickers: string[];
  coupon_rate_annual: number;
  coupon_barrier_pct: number;
  downside_barrier_pct: number;
  autocall_barrier_pct: number;
  num_observations: number;
  first_autocall_observation: number;
  pricing_date: string | null;
  maturity_date: string | null;
  offering_month: string;
  source: string;
  source_filename: string | null;
  email_subject: string | null;
  received_at: string | null;
  review_notes: string | null;
  dismissed: boolean;
}

export interface CandidateMonth {
  month: string;
  count: number;
}

export interface ScreenParams {
  stake: number;
  coupon_tax: number;
  state_tax: number;
  loss_tax: number;
  erp: number;
  reversal: number;
  reversal_signal: '3m' | '52w';
}

export interface ReplayResult {
  windows: number;
  first_start: string;
  last_start: string;
  prob_principal_loss: number;
  prob_autocall: number;
  aftertax_return_per_year: number;
  worst_aftertax_pnl: number;
}

export interface ScreenResultRow {
  cusip: string;
  issuer: string;
  tickers: string[];
  coupon_rate_annual: number;
  downside_barrier_pct: number;
  sigma: number[];
  fair_value: number;
  prob_autocall: number;
  expected_life_years: number;
  prob_principal_loss: number;
  expected_loss_given_breach: number;
  pretax_return_per_year: number;
  aftertax_return_per_year: number;
  cvar_5_aftertax: number;
  replay: ReplayResult | null;
  replay_flag: boolean;
  corr_with_book: number | null;
  prob_breach_in_book_tail: number | null;
  tail_add: number | null;
  max_concentration: [string, number] | null;
  overlap_tickers: string[];
}

export interface BookNote {
  cusip: string;
  principal: number;
  levels: { ticker: string; pct: number }[];
  coupon_barrier_pct: number;
  downside_barrier_pct: number;
}

export interface BookSummary {
  principal: number;
  expected_aftertax_pnl: number;
  cvar_5_aftertax: number;
  prob_any_breach: number;
  concentration: [string, number][];
  notes: BookNote[];
}

export interface TickerSignal {
  ticker: string;
  last: number;
  low_52w: number;
  high_52w: number;
  range_position: number;
  off_high: number;
  macd_bullish: boolean | null;
  days_since_cross: number | null;
  above_200dma: boolean | null;
  volume_support: number | null;
  put_oi_support: number | null;
  put_oi_expiry: string | null;
  barrier_pct: number;
}

export interface ScreenResult {
  risk_free: number;
  aftertax_hurdle: number;
  params: ScreenParams & { paths: number };
  book: BookSummary | null;
  results: ScreenResultRow[];
  signals: TickerSignal[];
}

export interface ScreenRun {
  id: number;
  status: 'running' | 'done' | 'error';
  created_at: string;
  finished_at: string | null;
  account_ids: number[];
  error: string | null;
  result: ScreenResult | null;
}

export interface GmailStatus {
  connected: boolean;
  syncing: boolean;
  last_run_at: string | null;
  last_success_at: string | null;
  last_added: number;
  last_error: string | null;
}

async function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json', ...userHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  return res.json();
}

export function fetchCandidateMonths(): Promise<CandidateMonth[]> {
  return fetchJson('/api/candidates/months');
}

export function fetchCandidates(month: string): Promise<CandidateOffering[]> {
  return fetchJson(`/api/candidates/?month=${encodeURIComponent(month)}`);
}

export function setCandidateDismissed(cusip: string, dismissed: boolean): Promise<CandidateOffering> {
  return sendJson(`/api/candidates/${cusip}`, 'PATCH', { dismissed });
}

export function startScreenRun(month: string, params: ScreenParams): Promise<ScreenRun> {
  return sendJson('/api/candidates/screen', 'POST', { month, ...params });
}

export function fetchLatestScreenRun(month: string): Promise<ScreenRun | null> {
  return fetchJson(`/api/candidates/screen/latest?month=${encodeURIComponent(month)}`);
}

export function fetchGmailStatus(): Promise<GmailStatus> {
  return fetchJson('/api/candidates/gmail/status');
}

export function startGmailSync(): Promise<{ started: boolean }> {
  return sendJson('/api/candidates/gmail/sync', 'POST');
}
