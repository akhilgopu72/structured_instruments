import { useState, useMemo } from 'react';
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { format, parseISO } from 'date-fns';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts';
import {
  fetchDashboardSummary,
  fetchInstruments,
  fetchBarrierStatus,
  fetchCouponCalendar,
  postRefresh,
  type BarrierStatus,
  type RefreshResult,
} from '../api';
import SummaryCard from '../components/SummaryCard';
import BarrierGauge from '../components/BarrierGauge';
import AccountFilter from '../components/AccountFilter';
import { useUser } from '../contexts/UserContext';
import { useAccounts } from '../contexts/AccountContext';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function CouponCountPopover({ count, items }: { count: number; items: { cusip: string; issuer: string; amount: number }[] }) {
  if (count === 0) return <span className="text-gray-500">({count})</span>;
  return (
    <span className="group/pop relative cursor-help inline-block">
      <span className="text-gray-500 underline decoration-dotted decoration-gray-600">({count})</span>
      <span className="pointer-events-none group-hover/pop:pointer-events-auto absolute right-0 bottom-full pb-2 w-56 opacity-0 group-hover/pop:opacity-100 transition-opacity duration-300 z-20">
        <span className="block rounded-lg bg-gray-900 border border-gray-600 p-3 text-xs shadow-xl">
          {items.map((item, i) => (
            <Link
              key={`${item.cusip}-${i}`}
              to={`/instrument/${item.cusip}`}
              className="flex items-center justify-between py-1.5 px-1 rounded hover:bg-gray-700 transition-colors"
            >
              <span>
                <span className="text-blue-400 hover:underline font-mono">{item.cusip}</span>
                <span className="text-gray-500 ml-1.5">{item.issuer}</span>
              </span>
              <span className="text-gray-300 font-mono ml-2">${item.amount.toFixed(2)}</span>
            </Link>
          ))}
        </span>
      </span>
    </span>
  );
}

export default function Dashboard() {
  const { userId } = useUser();
  const { selectedAccountIds } = useAccounts();
  const accountIds = Array.from(selectedAccountIds).sort().join(',');

  const summaryQuery = useQuery({
    queryKey: ['dashboard', 'summary', userId, accountIds],
    queryFn: fetchDashboardSummary,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const instrumentsQuery = useQuery({
    queryKey: ['instruments', userId, accountIds],
    queryFn: fetchInstruments,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const barrierQuery = useQuery({
    queryKey: ['dashboard', 'barrier-status', userId, accountIds],
    queryFn: fetchBarrierStatus,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const couponQuery = useQuery({
    queryKey: ['coupons', 'calendar', userId, accountIds],
    queryFn: fetchCouponCalendar,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const queryClient = useQueryClient();
  const [refreshing, setRefreshing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [couponView, setCouponView] = useState<'table' | 'chart'>('table');
  const [instrumentFilter, setInstrumentFilter] = useState<'all' | 'coupon-at-risk' | 'autocall-window'>('all');
  const [showCalledNotes, setShowCalledNotes] = useState(false);
  const [vdSort, setVdSort] = useState<{ key: string; dir: 'asc' | 'desc' }>({ key: 'date', dir: 'asc' });

  async function handleRefresh() {
    setRefreshing(true);
    setToast(null);
    try {
      const result: RefreshResult = await postRefresh();
      await queryClient.invalidateQueries();
      setToast(
        `Updated ${result.prices_updated} prices, evaluated ${result.coupons_evaluated} coupons, ${result.autocalls_evaluated} autocalls`,
      );
      setTimeout(() => setToast(null), 5000);
    } catch (err) {
      setToast(`Refresh failed: ${(err as Error).message}`);
      setTimeout(() => setToast(null), 5000);
    } finally {
      setRefreshing(false);
    }
  }

  async function handleExportExcel() {
    setExporting(true);
    try {
      const response = await fetch('/api/export/excel', {
        headers: {
          ...(userId != null ? { 'X-User-Id': String(userId) } : {}),
          ...(accountIds ? { 'X-Account-Ids': accountIds } : {}),
        },
      });
      if (!response.ok) {
        throw new Error(`Export failed: ${response.statusText}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'structured_instruments_export.xlsx';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setToast(`Export failed: ${(err as Error).message}`);
      setTimeout(() => setToast(null), 5000);
    } finally {
      setExporting(false);
    }
  }

  const noAccounts = selectedAccountIds.size === 0;
  const summary = noAccounts ? undefined : summaryQuery.data;
  const instruments = noAccounts ? undefined : instrumentsQuery.data;
  const barriers = noAccounts ? undefined : barrierQuery.data;

  // Aggregate coupon payments by month
  interface CouponInstrument { cusip: string; issuer: string; amount: number }
  interface MonthBucket {
    paidAmount: number; paidCount: number; paidInstruments: CouponInstrument[];
    missedAmount: number; missedCount: number; missedInstruments: CouponInstrument[];
  }
  const couponByMonth = useMemo(() => {
    if (noAccounts || !couponQuery.data) return [];
    const instByCusip: Record<string, { principal: number; monthlyRate: number }> = {};
    instruments?.forEach((inst) => {
      instByCusip[inst.cusip] = {
        principal: inst.principal ?? 0,
        monthlyRate: inst.coupon_rate_annual / 12,
      };
    });

    const monthMap: Record<string, MonthBucket> = {};
    for (const entry of couponQuery.data) {
      if (entry.status === 'upcoming') continue;
      const month = format(parseISO(entry.date), 'MMM yyyy');
      if (!monthMap[month]) monthMap[month] = { paidAmount: 0, paidCount: 0, paidInstruments: [], missedAmount: 0, missedCount: 0, missedInstruments: [] };
      if (entry.status === 'paid' && entry.coupon_amount != null) {
        monthMap[month].paidAmount += entry.coupon_amount;
        monthMap[month].paidCount += 1;
        monthMap[month].paidInstruments.push({ cusip: entry.cusip, issuer: entry.issuer, amount: entry.coupon_amount });
      } else if (entry.status === 'missed') {
        const inst = instByCusip[entry.cusip];
        const missedAmt = inst ? inst.principal * inst.monthlyRate : 0;
        monthMap[month].missedAmount += missedAmt;
        monthMap[month].missedCount += 1;
        monthMap[month].missedInstruments.push({ cusip: entry.cusip, issuer: entry.issuer, amount: missedAmt });
      }
    }
    return Object.entries(monthMap).map(([month, data]) => ({
      month,
      paidAmount: Math.round(data.paidAmount * 100) / 100,
      paidCount: data.paidCount,
      paidInstruments: data.paidInstruments,
      missedAmount: Math.round(data.missedAmount * 100) / 100,
      missedCount: data.missedCount,
      missedInstruments: data.missedInstruments,
    }));
  }, [couponQuery.data, instruments]);

  const isLoading = summaryQuery.isLoading || instrumentsQuery.isLoading || barrierQuery.isLoading;
  const error = summaryQuery.error || instrumentsQuery.error || barrierQuery.error;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400 text-lg">Loading dashboard...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400 text-lg">Error loading dashboard: {(error as Error).message}</div>
      </div>
    );
  }

  // Group barriers by cusip for instrument cards
  const barriersByCusip: Record<string, BarrierStatus[]> = {};
  barriers?.forEach((b) => {
    if (!barriersByCusip[b.cusip]) barriersByCusip[b.cusip] = [];
    barriersByCusip[b.cusip].push(b);
  });

  return (
    <div className="space-y-6">
      {/* Header with action buttons */}
      <div className="flex items-start justify-between">
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <div className="flex flex-col items-end gap-4">
          <AccountFilter />
          <div className="flex items-center gap-3">
          <button
            onClick={handleExportExcel}
            disabled={exporting}
            className="inline-flex items-center gap-2 rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {exporting && (
              <svg
                className="h-4 w-4 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            {exporting ? 'Exporting...' : 'Export Excel'}
          </button>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {refreshing && (
              <svg
                className="h-4 w-4 animate-spin"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            )}
            {refreshing ? 'Refreshing...' : 'Refresh Data'}
          </button>
          </div>
        </div>
      </div>

      {/* Toast notification */}
      {toast && (
        <div
          className={`rounded-md px-4 py-3 text-sm ${
            toast.startsWith('Refresh failed') || toast.startsWith('Export failed')
              ? 'bg-red-900/50 text-red-300 border border-red-700'
              : 'bg-green-900/50 text-green-300 border border-green-700'
          }`}
        >
          {toast}
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <SummaryCard
            label="Total Principal"
            value={formatCurrency(summary.total_principal)}
            accent="blue"
          />
          <SummaryCard
            label="Total Income"
            value={formatCurrency(summary.total_coupon_income)}
            accent="green"
          />
          <SummaryCard
            label="Active Notes"
            value={String(summary.active_instruments)}
            accent="yellow"
          />
          <SummaryCard
            label="Called Notes"
            value={String(summary.called_instruments)}
            accent="red"
            onClick={summary.called_instruments > 0 ? () => setShowCalledNotes((v) => !v) : undefined}
            active={showCalledNotes}
          />
        </div>
      )}

      {/* Instrument cards with barrier gauges */}
      {(() => {
        const activeInstruments = (instruments ?? []).filter((inst) => inst.status !== 'called');
        const calledInstruments = (instruments ?? []).filter((inst) => inst.status === 'called');

        const renderCard = (inst: typeof activeInstruments[number]) => {
          const instBarriers = barriersByCusip[inst.cusip] ?? [];
          const allAboveInitial =
            instBarriers.length > 0 &&
            instBarriers.every((b) => b.pct_of_initial !== null && b.pct_of_initial >= 1.0);
          const hasAutocallDate =
            summary?.upcoming_valuation_dates.some(
              (ud) => ud.cusip === inst.cusip && ud.autocall_eligible,
            ) ?? false;
          const showAutocall = inst.status === 'active' && allAboveInitial && hasAutocallDate;
          const couponAtRisk =
            inst.status === 'active' &&
            instBarriers.some(
              (b) => b.pct_of_initial !== null && b.pct_of_initial < inst.coupon_barrier_pct,
            );
          const principalAtRisk =
            inst.status === 'active' &&
            instBarriers.some(
              (b) => b.pct_of_initial !== null && b.pct_of_initial < inst.downside_barrier_pct,
            );
          const couponColor = couponAtRisk ? 'text-red-400' : 'text-green-400';

          return (
            <Link
              key={inst.cusip}
              to={`/instrument/${inst.cusip}`}
              className="block bg-gray-800 rounded-lg p-5 hover:bg-gray-750 hover:ring-1 hover:ring-blue-500 transition-all"
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <p className="text-white font-semibold">{inst.issuer}</p>
                  <p className="text-gray-400 text-sm font-mono">{inst.cusip}</p>
                  {inst.status === 'called' && inst.call_date && (
                    <p className="text-yellow-300/80 text-xs mt-1">
                      Called {format(parseISO(inst.call_date), 'MMM d, yyyy')}
                    </p>
                  )}
                </div>
                <span
                  className={`text-xs font-medium px-2 py-1 rounded ${
                    inst.status === 'active'
                      ? 'bg-green-900 text-green-300'
                      : inst.status === 'called'
                        ? 'bg-yellow-900 text-yellow-300'
                        : 'bg-gray-700 text-gray-300'
                  }`}
                >
                  {inst.status}
                </span>
              </div>
              {(showAutocall || couponAtRisk || principalAtRisk) && (
                <div className="flex flex-wrap gap-1.5 mb-3">
                  {showAutocall && (
                    <span className="group relative cursor-help text-xs px-2 py-0.5 rounded-full bg-blue-900/50 text-blue-300 border border-blue-700">
                      Autocall Window
                      <span className="pointer-events-none absolute left-0 bottom-full mb-1 w-72 rounded bg-gray-900 border border-gray-600 px-3 py-2 text-xs text-gray-300 font-normal opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        All underlyings are above their initial price. If this holds through the next autocall-eligible date, the note will be redeemed at par plus final coupon.
                      </span>
                    </span>
                  )}
                  {couponAtRisk && (
                    <span className="group relative cursor-help text-xs px-2 py-0.5 rounded-full bg-yellow-900/50 text-yellow-300 border border-yellow-700">
                      Coupon At Risk
                      <span className="pointer-events-none absolute left-0 bottom-full mb-1 w-72 rounded bg-gray-900 border border-gray-600 px-3 py-2 text-xs text-gray-300 font-normal opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        At least one underlying is below its coupon barrier. If prices don&apos;t recover by the next valuation date, the coupon payment will be missed.
                      </span>
                    </span>
                  )}
                  {principalAtRisk && (
                    <span className="group relative cursor-help text-xs px-2 py-0.5 rounded-full bg-red-900/50 text-red-300 border border-red-700">
                      Principal At Risk
                      <span className="pointer-events-none absolute left-0 bottom-full mb-1 w-72 rounded bg-gray-900 border border-gray-600 px-3 py-2 text-xs text-gray-300 font-normal opacity-0 group-hover:opacity-100 transition-opacity z-10">
                        At least one underlying is below its downside protection barrier. If held to maturity at current levels, principal loss would occur.
                      </span>
                    </span>
                  )}
                </div>
              )}
              <div className="grid grid-cols-3 gap-2 text-sm mb-1">
                <div>
                  <span className="text-gray-500">Principal</span>
                  <p className="text-white">{inst.principal != null ? `$${inst.principal.toLocaleString()}` : '—'}</p>
                </div>
                <div>
                  <span className="text-gray-500">Target Coupon</span>
                  <p className={couponColor}>{inst.principal != null ? `$${(inst.principal * inst.coupon_rate_annual / 12).toFixed(2)}` : '—'}</p>
                </div>
                <div>
                  <span className="text-gray-500">Coupon Rate</span>
                  <p className="text-white">{(inst.coupon_rate_annual * 100).toFixed(1)}%</p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-2 text-sm mb-3">
                <div>
                  <span className="text-gray-500">Paid</span>
                  <p className="text-green-400">
                    {inst.principal != null
                      ? `$${(inst.coupons_received * inst.principal * inst.coupon_rate_annual / 12).toFixed(2)}`
                      : '—'}{' '}
                    <span className="text-gray-500">({inst.coupons_received})</span>
                  </p>
                </div>
                <div>
                  <span className="text-gray-500">Missed</span>
                  <p className="text-red-400">
                    {inst.principal != null
                      ? `$${(inst.coupons_missed * inst.principal * inst.coupon_rate_annual / 12).toFixed(2)}`
                      : '—'}{' '}
                    <span className="text-gray-500">({inst.coupons_missed})</span>
                  </p>
                </div>
              </div>
              {inst.status !== 'called' && (
                <div className="space-y-2">
                  {barriersByCusip[inst.cusip]?.map((b) => (
                    <BarrierGauge
                      key={b.ticker}
                      ticker={b.ticker}
                      pctOfInitial={b.pct_of_initial}
                      couponBarrierPct={inst.coupon_barrier_pct}
                      downsideBarrierPct={inst.downside_barrier_pct}
                    />
                  ))}
                </div>
              )}
            </Link>
          );
        };

        const filteredActive = activeInstruments.filter((inst) => {
          if (instrumentFilter === 'all') return true;
          const instBarriers = barriersByCusip[inst.cusip] ?? [];
          if (instrumentFilter === 'coupon-at-risk') {
            return instBarriers.some(
              (b) => b.pct_of_initial !== null && b.pct_of_initial < inst.coupon_barrier_pct,
            );
          }
          const allAboveInitial =
            instBarriers.length > 0 &&
            instBarriers.every((b) => b.pct_of_initial !== null && b.pct_of_initial >= 1.0);
          const hasAutocallDate =
            summary?.upcoming_valuation_dates.some(
              (ud) => ud.cusip === inst.cusip && ud.autocall_eligible,
            ) ?? false;
          return allAboveInitial && hasAutocallDate;
        });

        return (
          <>
            <div>
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-semibold text-white">Instruments</h2>
                <div className="flex items-center bg-gray-700 rounded-md p-0.5 text-sm">
                  <button
                    onClick={() => setInstrumentFilter('all')}
                    className={`px-3 py-1 rounded ${instrumentFilter === 'all' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-gray-200'}`}
                  >
                    All
                  </button>
                  <button
                    onClick={() => setInstrumentFilter('coupon-at-risk')}
                    className={`px-3 py-1 rounded ${instrumentFilter === 'coupon-at-risk' ? 'bg-yellow-900/80 text-yellow-300' : 'text-gray-400 hover:text-gray-200'}`}
                  >
                    Coupon At Risk
                  </button>
                  <button
                    onClick={() => setInstrumentFilter('autocall-window')}
                    className={`px-3 py-1 rounded ${instrumentFilter === 'autocall-window' ? 'bg-blue-900/80 text-blue-300' : 'text-gray-400 hover:text-gray-200'}`}
                  >
                    Autocall Window
                  </button>
                </div>
              </div>
              {activeInstruments.length === 0 ? (
                <div className="bg-gray-800 rounded-lg p-8 text-center text-gray-400">
                  No active instruments found for the selected accounts.
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {filteredActive.map(renderCard)}
                </div>
              )}
            </div>

            {showCalledNotes && calledInstruments.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold text-white">Called Notes</h2>
                  <button
                    onClick={() => setShowCalledNotes(false)}
                    className="text-sm text-gray-400 hover:text-gray-200"
                  >
                    Hide
                  </button>
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {calledInstruments.map(renderCard)}
                </div>
              </div>
            )}
          </>
        );
      })()}

      {/* Coupon income by month */}
      {couponByMonth.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-white">Coupon Income by Month</h2>
            <div className="flex items-center bg-gray-700 rounded-md p-0.5 text-sm">
              <button
                onClick={() => setCouponView('table')}
                className={`px-3 py-1 rounded ${couponView === 'table' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-gray-200'}`}
              >
                Table
              </button>
              <button
                onClick={() => setCouponView('chart')}
                className={`px-3 py-1 rounded ${couponView === 'chart' ? 'bg-gray-600 text-white' : 'text-gray-400 hover:text-gray-200'}`}
              >
                Chart
              </button>
            </div>
          </div>

          {couponView === 'table' ? (
            <div className="bg-gray-800 rounded-lg">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-700 text-gray-400">
                    <th className="text-left px-4 py-3 font-medium">Month</th>
                    <th className="text-right px-4 py-3 font-medium">Coupons Received</th>
                    <th className="text-right px-4 py-3 font-medium">Coupons Missed</th>
                  </tr>
                </thead>
                <tbody>
                  {couponByMonth.map((row, i) => (
                    <tr
                      key={row.month}
                      className={`border-b border-gray-700/50 ${i % 2 === 0 ? 'bg-gray-800' : 'bg-gray-800/50'}`}
                    >
                      <td className="px-4 py-2.5 text-white">{row.month}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-green-400">
                        ${row.paidAmount.toFixed(2)}{' '}
                        <CouponCountPopover count={row.paidCount} items={row.paidInstruments} />
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-red-400">
                        ${row.missedAmount.toFixed(2)}{' '}
                        <CouponCountPopover count={row.missedCount} items={row.missedInstruments} />
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-gray-600 bg-gray-800/80">
                    <td className="px-4 py-2.5 text-white font-semibold">Total</td>
                    <td className="px-4 py-2.5 text-right font-mono font-semibold text-green-400">
                      ${couponByMonth.reduce((s, r) => s + r.paidAmount, 0).toFixed(2)}{' '}
                      <span className="text-gray-500 font-normal">({couponByMonth.reduce((s, r) => s + r.paidCount, 0)})</span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono font-semibold text-red-400">
                      ${couponByMonth.reduce((s, r) => s + r.missedAmount, 0).toFixed(2)}{' '}
                      <span className="text-gray-500 font-normal">({couponByMonth.reduce((s, r) => s + r.missedCount, 0)})</span>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
            <div className="bg-gray-800 rounded-lg p-5">
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={couponByMonth} margin={{ top: 5, right: 20, left: 20, bottom: 5 }}>
                  <XAxis
                    dataKey="month"
                    tick={{ fill: '#9CA3AF', fontSize: 12 }}
                    axisLine={{ stroke: '#374151' }}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: '#9CA3AF', fontSize: 12 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(v: number) => `$${v.toLocaleString()}`}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1F2937',
                      border: '1px solid #374151',
                      borderRadius: '0.5rem',
                      color: '#F9FAFB',
                    }}
                    formatter={(value: number) => [`$${value.toFixed(2)}`, 'Coupon Income']}
                    labelStyle={{ color: '#9CA3AF' }}
                  />
                  <Bar dataKey="paidAmount" radius={[4, 4, 0, 0]} maxBarSize={48}>
                    {couponByMonth.map((entry, index) => (
                      <Cell
                        key={index}
                        fill={entry.missedCount > 0 ? '#F59E0B' : '#10B981'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
              <div className="flex items-center gap-4 mt-2 text-xs text-gray-400 justify-center">
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-3 h-3 rounded-sm bg-emerald-500" />
                  All coupons paid
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-3 h-3 rounded-sm bg-amber-500" />
                  Some coupons missed
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Upcoming valuation dates */}
      {summary && summary.upcoming_valuation_dates.length > 0 && (
        <div>
          <h2 className="text-xl font-semibold text-white mb-4">Upcoming Valuation Dates</h2>
          {(() => {
            // Compute projected coupon for each upcoming date based on current prices
            const rows = summary.upcoming_valuation_dates.map((ud) => {
              const inst = instruments?.find((ins) => ins.cusip === ud.cusip);
              const instBarriers = barriersByCusip[ud.cusip] ?? [];
              const allAboveCoupon =
                instBarriers.length > 0 &&
                instBarriers.every((b) => b.pct_of_initial !== null && b.pct_of_initial >= (inst?.coupon_barrier_pct ?? 0));
              const principal = inst?.principal ?? 0;
              const monthlyRate = (inst?.coupon_rate_annual ?? 0) / 12;
              const targetCoupon = principal * monthlyRate;
              // For already-evaluated dates, use actual outcome instead of projection
              const paid = ud.is_paid === true;
              const missed = ud.is_paid === false;
              const projectedCoupon = paid ? targetCoupon : missed ? 0 : allAboveCoupon ? targetCoupon : 0;
              const projectedMiss = paid ? 0 : missed ? targetCoupon : allAboveCoupon ? 0 : targetCoupon;
              return { ...ud, projectedCoupon, projectedMiss, allAboveCoupon, principal };
            });
            const projectedTotal = rows.reduce((sum, r) => sum + Math.round(r.projectedCoupon * 100) / 100, 0);
            const missedTotal = rows.reduce((sum, r) => sum + Math.round(r.projectedMiss * 100) / 100, 0);

            const sortedRows = [...rows].sort((a, b) => {
              const k = vdSort.key;
              let va: string | number, vb: string | number;
              if (k === 'date') { va = a.date; vb = b.date; }
              else if (k === 'cusip') { va = a.cusip; vb = b.cusip; }
              else if (k === 'issuer') { va = a.issuer; vb = b.issuer; }
              else if (k === 'sequence_number') { va = a.sequence_number; vb = b.sequence_number; }
              else if (k === 'principal') { va = a.principal; vb = b.principal; }
              else if (k === 'projectedCoupon') { va = a.projectedCoupon; vb = b.projectedCoupon; }
              else if (k === 'projectedMiss') { va = a.projectedMiss; vb = b.projectedMiss; }
              else { va = a.date; vb = b.date; }
              if (va < vb) return vdSort.dir === 'asc' ? -1 : 1;
              if (va > vb) return vdSort.dir === 'asc' ? 1 : -1;
              return 0;
            });

            function toggleSort(key: string) {
              setVdSort((prev) =>
                prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
              );
            }
            const arrow = (key: string) => vdSort.key === key ? (vdSort.dir === 'asc' ? ' ▲' : ' ▼') : '';

            return (
              <div className="bg-gray-800 rounded-lg">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-700 text-gray-400">
                      <th className="w-10 px-4 py-3 font-medium"></th>
                      <th className="text-left px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-200" onClick={() => toggleSort('date')}>Date{arrow('date')}</th>
                      <th className="text-left px-4 py-3 font-medium">CUSIP</th>
                      <th className="text-left px-4 py-3 font-medium">Issuer</th>
                      <th className="text-left px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-200" onClick={() => toggleSort('sequence_number')}>#{ arrow('sequence_number')}</th>
                      <th className="text-right px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-200" onClick={() => toggleSort('principal')}>Principal{arrow('principal')}</th>
                      <th
                        className="text-right px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-200"
                        title="Estimated coupon payment if all underlyings remain above their coupon barrier on valuation date."
                        onClick={() => toggleSort('projectedCoupon')}
                      >
                        Projected Coupon{arrow('projectedCoupon')}
                      </th>
                      <th
                        className="text-right px-4 py-3 font-medium cursor-pointer select-none hover:text-gray-200"
                        title="Coupon amount at risk of being missed. Shown when any underlying is currently below its coupon barrier."
                        onClick={() => toggleSort('projectedMiss')}
                      >
                        Projected Miss{arrow('projectedMiss')}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRows.map((ud, i) => {
                      const todayStr = new Date().toISOString().split('T')[0];
                      const isPast = ud.date <= todayStr;
                      return (
                      <tr
                        key={`${ud.cusip}-${ud.date}`}
                        className={`border-b border-gray-700/50 ${i % 2 === 0 ? 'bg-gray-800' : 'bg-gray-800/50'}`}
                      >
                        <td className="px-4 py-2.5 text-center">
                          {!isPast ? (
                            <span className="inline-block w-3 h-3 rounded-full border-2 border-gray-500" title="Pending" />
                          ) : ud.is_paid === true ? (
                            <span className="inline-block w-3 h-3 rounded-full bg-green-500" title="Paid" />
                          ) : ud.is_paid === false ? (
                            <span className="inline-block w-3 h-3 rounded-full bg-red-500" title="Missed" />
                          ) : (
                            <span className="inline-block w-3 h-3 rounded-full border-2 border-gray-500" title="Pending" />
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-white font-mono">
                          {format(parseISO(ud.date), 'MMM d, yyyy')}
                        </td>
                        <td className="px-4 py-2.5">
                          <Link to={`/instrument/${ud.cusip}`} className="text-blue-400 hover:underline font-mono">
                            {ud.cusip}
                          </Link>
                        </td>
                        <td className="px-4 py-2.5 text-gray-300">{ud.issuer}</td>
                        <td className="px-4 py-2.5 text-gray-400">{ud.sequence_number}</td>
                        <td className="px-4 py-2.5 text-right font-mono text-gray-300">
                          ${ud.principal.toLocaleString('en-US', { minimumFractionDigits: 0 })}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-green-400">
                          {ud.projectedCoupon > 0 ? `$${ud.projectedCoupon.toFixed(2)}` : '—'}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-red-400">
                          {ud.projectedMiss > 0 ? `$${ud.projectedMiss.toFixed(2)}` : '—'}
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-gray-600 bg-gray-800/80">
                      <td colSpan={5} className="px-4 py-2.5 text-white font-semibold">
                        Total
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono font-semibold text-gray-300">
                        ${rows.reduce((sum, r) => sum + r.principal, 0).toLocaleString('en-US', { minimumFractionDigits: 0 })}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono font-semibold ${projectedTotal > 0 ? 'text-green-400' : 'text-gray-400'}`}>
                        ${projectedTotal.toFixed(2)}
                      </td>
                      <td className={`px-4 py-2.5 text-right font-mono font-semibold ${missedTotal > 0 ? 'text-red-400' : 'text-gray-400'}`}>
                        ${missedTotal.toFixed(2)}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
