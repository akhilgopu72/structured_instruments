import { useState } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import {
  fetchPerformanceMetrics,
  fetchSpyComparison,
  fetchChartData,
  fetchCouponCalendar,
  fetchTaxComparison,
} from '../api';
import { useUser } from '../contexts/UserContext';
import { useAccounts } from '../contexts/AccountContext';
import AccountFilter from '../components/AccountFilter';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPct(value: number | null): string {
  if (value == null) return '-';
  return `${value.toFixed(2)}%`;
}

export default function Performance() {
  const [ordinaryRate, setOrdinaryRate] = useState(0.37);
  const [ltcgRate, setLtcgRate] = useState(0.20);
  const [stateRate, setStateRate] = useState(0.0);
  const [spyTaxTreatment, setSpyTaxTreatment] = useState<'income' | 'ltcg'>('ltcg');
  const { userId } = useUser();
  const { selectedAccountIds } = useAccounts();
  const accountIds = Array.from(selectedAccountIds).sort().join(',');

  const metricsQuery = useQuery({
    queryKey: ['performance', 'metrics', userId, accountIds],
    queryFn: fetchPerformanceMetrics,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const spyQuery = useQuery({
    queryKey: ['performance', 'spy', userId, accountIds],
    queryFn: fetchSpyComparison,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const chartQuery = useQuery({
    queryKey: ['performance', 'chart-data', userId, accountIds],
    queryFn: fetchChartData,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const calendarQuery = useQuery({
    queryKey: ['coupons', 'calendar', userId, accountIds],
    queryFn: fetchCouponCalendar,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const taxQuery = useQuery({
    queryKey: ['performance', 'tax-comparison', ordinaryRate, ltcgRate, stateRate, spyTaxTreatment, userId, accountIds],
    queryFn: () => fetchTaxComparison(ordinaryRate, ltcgRate, stateRate, spyTaxTreatment),
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const noAccounts = selectedAccountIds.size === 0;
  const isLoading = !noAccounts &&
    (metricsQuery.isLoading || spyQuery.isLoading || chartQuery.isLoading || calendarQuery.isLoading);
  const error = !noAccounts &&
    (metricsQuery.error || spyQuery.error || chartQuery.error || calendarQuery.error);

  if (noAccounts) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-white">Performance</h1>
          <AccountFilter />
        </div>
        <div className="flex items-center justify-center h-64">
          <div className="text-gray-400 text-lg">Select an account to view performance data.</div>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400 text-lg">Loading performance data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400 text-lg">Error: {(error as Error).message}</div>
      </div>
    );
  }

  const metrics = metricsQuery.data!;
  const spy = spyQuery.data!;
  const chartData = (chartQuery.data ?? []).map((d) => ({
    date: d.date,
    portfolio: +d.portfolio_value.toFixed(2),
    spy: d.spy_value != null ? +d.spy_value.toFixed(2) : null,
  }));

  // Build monthly income data from coupon calendar. A paid coupon is income
  // that was actually earned for that month, so it counts regardless of whether
  // the note was later called — called notes still earned interest for the
  // month in which the autocall occurred.
  const monthlyIncome: Record<string, number> = {};
  (calendarQuery.data ?? [])
    .filter((c) => c.status === 'paid' && c.coupon_amount != null)
    .forEach((c) => {
      const month = c.date.substring(0, 7); // YYYY-MM
      monthlyIncome[month] = (monthlyIncome[month] ?? 0) + c.coupon_amount!;
    });

  const incomeData = Object.entries(monthlyIncome)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, amount]) => ({
      month: format(parseISO(`${month}-01`), 'MMM yy'),
      amount: +amount.toFixed(2),
    }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Performance</h1>
        <AccountFilter />
      </div>

      {/* Cumulative return chart */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Portfolio Value vs SPY</h2>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={350}>
            <LineChart data={chartData} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="date"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                stroke="#4b5563"
                tickFormatter={(val: string) => {
                  const d = parseISO(val);
                  const day = d.getDate();
                  return day === 1 || day === 15 ? format(d, 'MMM d') : '';
                }}
                interval={0}
                minTickGap={40}
              />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                stroke="#4b5563"
                domain={['auto', 'auto']}
                tickFormatter={(v: number) => v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid #374151',
                  borderRadius: '0.5rem',
                  color: '#f3f4f6',
                }}
                labelFormatter={(label: string) => format(parseISO(label), 'MMM d, yyyy')}
                formatter={(value: number | undefined, name: string | undefined) => [
                  formatCurrency(value ?? 0),
                  name,
                ]}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="portfolio"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                name="Portfolio"
              />
              <Line
                type="monotone"
                dataKey="spy"
                stroke="#f59e0b"
                strokeWidth={2}
                dot={false}
                name="SPY"
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500">No chart data available.</p>
        )}
      </div>

      {/* Metrics table */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-white mb-4">Portfolio Metrics</h2>
          <table className="w-full text-sm">
            <tbody>
              {[
                ['Total Principal', formatCurrency(metrics.total_principal)],
                ['Total Coupon Income', formatCurrency(metrics.total_coupon_income)],
                ['Total Return', formatPct(metrics.total_return_pct)],
                ['Annualized TWR', formatPct(metrics.annualized_twr)],
                ['XIRR', formatPct(metrics.xirr)],
                ['Holding Period', `${metrics.holding_period_days} days`],
              ].map(([label, val]) => (
                <tr key={label} className="border-b border-gray-700/50">
                  <td className="py-2.5 text-gray-400">{label}</td>
                  <td className="py-2.5 text-white text-right font-mono">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-gray-800 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-white mb-4">vs SPY</h2>
          <table className="w-full text-sm">
            <tbody>
              {[
                ['Portfolio Total Return', formatPct(spy.portfolio_total_return_pct)],
                ['SPY Total Return', formatPct(spy.spy_total_return_pct)],
                [
                  <span key="alpha-label" className="group relative cursor-help">
                    Alpha
                    <span className="pointer-events-none absolute left-0 bottom-full mb-1 w-64 rounded bg-gray-900 border border-gray-600 px-3 py-2 text-xs text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity z-10">
                      Excess return of the portfolio over SPY. Positive alpha means the portfolio outperformed a passive S&amp;P 500 investment over the same period.
                    </span>
                  </span>,
                  <span
                    key="alpha"
                    className={spy.alpha_pct >= 0 ? 'text-green-400' : 'text-red-400'}
                  >
                    {formatPct(spy.alpha_pct)}
                  </span>,
                ],
                ['Portfolio Annualized', formatPct(spy.portfolio_annualized)],
                ['SPY Annualized', formatPct(spy.spy_annualized)],
              ].map(([label, val], i) => (
                <tr key={i} className="border-b border-gray-700/50">
                  <td className="py-2.5 text-gray-400">{label}</td>
                  <td className="py-2.5 text-white text-right font-mono">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Monthly income bar chart */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Monthly Coupon Income</h2>
        {incomeData.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={incomeData} margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis
                dataKey="month"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                stroke="#4b5563"
              />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                stroke="#4b5563"
                tickFormatter={(v: number) => `$${v}`}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#1f2937',
                  border: '1px solid #374151',
                  borderRadius: '0.5rem',
                  color: '#f3f4f6',
                }}
                formatter={(value: number | undefined) => [`$${(value ?? 0).toFixed(2)}`, 'Income']}
              />
              <Bar dataKey="amount" fill="#10b981" radius={[4, 4, 0, 0]} name="Income" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500">No income data available.</p>
        )}
      </div>

      {/* Tax Analysis */}
      <div className="space-y-4">
        <h2 className="text-xl font-bold text-white">Tax Analysis</h2>

        {/* Tax rate inputs */}
        <div className="bg-gray-800 rounded-lg p-6">
          <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
            Tax Rate Assumptions
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Ordinary Income Rate</label>
              <div className="relative">
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  value={+(ordinaryRate * 100).toFixed(1)}
                  onChange={(e) => setOrdinaryRate(Math.min(1, Math.max(0, parseFloat(e.target.value) / 100 || 0)))}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-blue-500"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">%</span>
              </div>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">LTCG Rate</label>
              <div className="relative">
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  value={+(ltcgRate * 100).toFixed(1)}
                  onChange={(e) => setLtcgRate(Math.min(1, Math.max(0, parseFloat(e.target.value) / 100 || 0)))}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-blue-500"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">%</span>
              </div>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">State Tax Rate</label>
              <div className="relative">
                <input
                  type="number"
                  min={0}
                  max={100}
                  step={0.5}
                  value={+(stateRate * 100).toFixed(1)}
                  onChange={(e) => setStateRate(Math.min(1, Math.max(0, parseFloat(e.target.value) / 100 || 0)))}
                  className="w-full bg-gray-700 border border-gray-600 rounded px-3 py-2 text-white text-sm font-mono focus:outline-none focus:border-blue-500"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">%</span>
              </div>
            </div>
          </div>
        </div>

        {taxQuery.isLoading && (
          <div className="text-gray-400 text-sm">Loading tax analysis...</div>
        )}

        {taxQuery.error && (
          <div className="text-red-400 text-sm">
            Tax analysis error: {(taxQuery.error as Error).message}
          </div>
        )}

        {taxQuery.data && (
          <>
            {/* Side-by-side comparison cards */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Portfolio (Ordinary Income) */}
              <div className="bg-gray-800 rounded-lg p-6">
                <h3 className="text-lg font-semibold text-white mb-4">
                  Portfolio <span className="text-sm font-normal text-gray-400">(Ordinary Income)</span>
                </h3>
                <table className="w-full text-sm">
                  <tbody>
                    {[
                      ['Gross Income', formatCurrency(taxQuery.data.gross_coupon_income)],
                      ['Federal Tax', formatCurrency(-taxQuery.data.federal_tax_on_coupons)],
                      ['State Tax', formatCurrency(-taxQuery.data.state_tax_on_coupons)],
                      ['Net Income', formatCurrency(taxQuery.data.net_coupon_income)],
                      ['Effective Tax Rate', formatPct(taxQuery.data.effective_coupon_tax_rate * 100)],
                    ].map(([label, val]) => (
                      <tr key={label} className="border-b border-gray-700/50">
                        <td className="py-2.5 text-gray-400">{label}</td>
                        <td className="py-2.5 text-white text-right font-mono">{val}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* SPY (Capital Gains) */}
              <div className="bg-gray-800 rounded-lg p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-white">
                    SPY <span className="text-sm font-normal text-gray-400">
                      ({spyTaxTreatment === 'income' ? 'Ordinary Income' : 'Capital Gains'})
                    </span>
                  </h3>
                  <div className="flex items-center bg-gray-700 rounded-md p-0.5 text-xs">
                    <button
                      className={`px-2.5 py-1 rounded transition-colors ${
                        spyTaxTreatment === 'income'
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-400 hover:text-gray-200'
                      }`}
                      onClick={() => setSpyTaxTreatment('income')}
                    >
                      Income
                    </button>
                    <button
                      className={`px-2.5 py-1 rounded transition-colors ${
                        spyTaxTreatment === 'ltcg'
                          ? 'bg-blue-600 text-white'
                          : 'text-gray-400 hover:text-gray-200'
                      }`}
                      onClick={() => setSpyTaxTreatment('ltcg')}
                    >
                      Long Term
                    </button>
                  </div>
                </div>
                <table className="w-full text-sm">
                  <tbody>
                    {[
                      ['Gross Return', formatCurrency(taxQuery.data.spy_gross_return_dollars)],
                      ['Federal Tax', formatCurrency(-taxQuery.data.spy_federal_tax)],
                      ['State Tax', formatCurrency(-taxQuery.data.spy_state_tax)],
                      ['Net Return', formatCurrency(taxQuery.data.spy_net_return_dollars)],
                      ['Effective Tax Rate', formatPct(taxQuery.data.spy_effective_tax_rate * 100)],
                    ].map(([label, val]) => (
                      <tr key={label} className="border-b border-gray-700/50">
                        <td className="py-2.5 text-gray-400">{label}</td>
                        <td className="py-2.5 text-white text-right font-mono">{val}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* After-tax advantage summary */}
            <div className="bg-gray-800 rounded-lg p-6">
              <div className="flex items-center justify-between">
                <span className="text-gray-400 text-sm">After-Tax Advantage</span>
                <span
                  className={`text-lg font-bold font-mono ${
                    taxQuery.data.net_advantage >= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {taxQuery.data.net_advantage >= 0 ? '+' : ''}
                  {formatCurrency(taxQuery.data.net_advantage)}
                </span>
              </div>
              <div className="flex items-center justify-between mt-2">
                <span className="text-gray-400 text-sm">Tax Drag Difference</span>
                <span
                  className={`text-sm font-mono ${
                    taxQuery.data.tax_drag_pct <= 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {taxQuery.data.tax_drag_pct > 0 ? '+' : ''}
                  {formatPct(taxQuery.data.tax_drag_pct * 100)}
                </span>
              </div>
              <p className="text-gray-500 text-xs mt-3">
                {taxQuery.data.net_advantage >= 0
                  ? 'Portfolio coupons produce more after-tax income than a comparable SPY position.'
                  : 'A comparable SPY position would produce more after-tax income than portfolio coupons.'}
              </p>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
