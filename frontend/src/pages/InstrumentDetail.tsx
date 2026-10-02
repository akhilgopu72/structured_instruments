import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts';
import { fetchInstrumentDetail, fetchCouponCalendar, type CouponCalendarEntry, type CouponUnderlyingDetail } from '../api';
import { useUser } from '../contexts/UserContext';

const UNDERLYING_COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6', '#ec4899'];

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(value);
}

export default function InstrumentDetail() {
  const { cusip } = useParams<{ cusip: string }>();
  const { userId } = useUser();

  const detailQuery = useQuery({
    queryKey: ['instrument', cusip, userId],
    queryFn: () => fetchInstrumentDetail(cusip!),
    enabled: !!cusip && userId != null,
  });

  const calendarQuery = useQuery({
    queryKey: ['coupons', 'calendar', userId],
    queryFn: fetchCouponCalendar,
    enabled: userId != null,
  });

  if (detailQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400 text-lg">Loading instrument...</div>
      </div>
    );
  }

  if (detailQuery.error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400 text-lg">
          Error: {(detailQuery.error as Error).message}
        </div>
      </div>
    );
  }

  const inst = detailQuery.data!;

  // Filter coupon events for this instrument
  const couponHistory: CouponCalendarEntry[] = (calendarQuery.data ?? [])
    .filter((c) => c.cusip === cusip)
    .sort((a, b) => a.date.localeCompare(b.date));

  // Derive the unique underlying tickers for dynamic columns in coupon history.
  // Prefer the instrument's underlyings order; fall back to details from coupon events.
  const underlyingTickers: string[] = inst.underlyings.length > 0
    ? inst.underlyings.map((u) => u.ticker)
    : (() => {
        const seen = new Set<string>();
        for (const c of couponHistory) {
          if (c.details) {
            for (const d of c.details) {
              seen.add(d.ticker);
            }
          }
        }
        return Array.from(seen);
      })();

  // Build price chart data: each underlying's pct_of_initial as a single "current" data point
  // Since we don't have historical time-series per underlying from the detail endpoint,
  // we show a snapshot with barriers
  const chartData = inst.underlyings.map((u) => ({
    ticker: u.ticker,
    pct_of_initial: u.pct_of_initial != null ? +(u.pct_of_initial * 100).toFixed(2) : null,
  }));

  return (
    <div className="space-y-6">
      {/* Header with account filter */}
      <div className="text-sm text-gray-400">
        <Link to="/" className="text-blue-400 hover:underline">
          Dashboard
        </Link>
        <span className="mx-2">/</span>
        <span>{inst.cusip}</span>
      </div>

      {/* Header */}
      <div className="bg-gray-800 rounded-lg p-6">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-white">{inst.issuer}</h1>
            <p className="text-gray-400 font-mono text-lg mt-1">{inst.cusip}</p>
            {inst.product_type && (
              <p className="text-gray-500 text-sm mt-1">{inst.product_type}</p>
            )}
          </div>
          <span
            className={`self-start text-sm font-medium px-3 py-1.5 rounded ${
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

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
          <div>
            <p className="text-gray-500 text-sm">Pricing Date</p>
            <p className="text-white">{format(parseISO(inst.pricing_date), 'MMM d, yyyy')}</p>
          </div>
          <div>
            <p className="text-gray-500 text-sm">Maturity Date</p>
            <p className="text-white">{format(parseISO(inst.maturity_date), 'MMM d, yyyy')}</p>
          </div>
          <div>
            <p className="text-gray-500 text-sm">Annual Coupon</p>
            <p className="text-white">{(inst.coupon_rate_annual * 100).toFixed(2)}%</p>
          </div>
          <div>
            <p className="text-gray-500 text-sm">Monthly Coupon</p>
            <p className="text-white">{(inst.coupon_rate_monthly * 100).toFixed(4)}%</p>
          </div>
          <div>
            <p className="text-gray-500 text-sm">Coupon Barrier</p>
            <p className="text-yellow-400">{(inst.coupon_barrier_pct * 100).toFixed(0)}%</p>
          </div>
          <div>
            <p className="text-gray-500 text-sm">Downside Barrier</p>
            <p className="text-red-400">{(inst.downside_barrier_pct * 100).toFixed(0)}%</p>
          </div>
          <div>
            <p className="text-gray-500 text-sm">Autocall Barrier</p>
            <p className="text-blue-400">{(inst.autocall_barrier_pct * 100).toFixed(0)}%</p>
          </div>
          {inst.next_valuation_date && (
            <div>
              <p className="text-gray-500 text-sm">Next Valuation</p>
              <p className="text-white">
                {format(parseISO(inst.next_valuation_date), 'MMM d, yyyy')}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Price snapshot chart with barriers */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">
          Underlying Prices (% of Initial)
        </h2>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart
            data={chartData}
            margin={{ top: 10, right: 30, left: 10, bottom: 10 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis
              dataKey="ticker"
              tick={{ fill: '#9ca3af', fontSize: 12 }}
              stroke="#4b5563"
            />
            <YAxis
              tick={{ fill: '#9ca3af', fontSize: 12 }}
              stroke="#4b5563"
              domain={[0, 'auto']}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: '#1f2937',
                border: '1px solid #374151',
                borderRadius: '0.5rem',
                color: '#f3f4f6',
              }}
              formatter={(value: number | undefined) => [`${value ?? 0}%`, 'Price % of Initial']}
            />
            <ReferenceLine
              y={inst.coupon_barrier_pct * 100}
              stroke="#eab308"
              strokeDasharray="5 5"
              label={{
                value: `Coupon ${(inst.coupon_barrier_pct * 100).toFixed(0)}%`,
                fill: '#eab308',
                fontSize: 11,
                position: 'right',
              }}
            />
            <ReferenceLine
              y={inst.downside_barrier_pct * 100}
              stroke="#ef4444"
              strokeDasharray="5 5"
              label={{
                value: `Downside ${(inst.downside_barrier_pct * 100).toFixed(0)}%`,
                fill: '#ef4444',
                fontSize: 11,
                position: 'right',
              }}
            />
            <Line
              type="monotone"
              dataKey="pct_of_initial"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={{ fill: '#3b82f6', r: 6 }}
              name="% of Initial"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Underlyings detail */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Underlyings</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-700 text-gray-400">
                <th className="text-left px-4 py-3 font-medium">Ticker</th>
                <th className="text-left px-4 py-3 font-medium">Name</th>
                <th className="text-right px-4 py-3 font-medium">Initial</th>
                <th className="text-right px-4 py-3 font-medium">Current</th>
                <th className="text-right px-4 py-3 font-medium">% of Initial</th>
                <th className="text-right px-4 py-3 font-medium">Coupon Barrier</th>
                <th className="text-right px-4 py-3 font-medium">Downside Barrier</th>
                <th className="text-center px-4 py-3 font-medium">Coupon OK</th>
                <th className="text-center px-4 py-3 font-medium">Downside OK</th>
              </tr>
            </thead>
            <tbody>
              {inst.underlyings.map((u, i) => (
                <tr
                  key={u.ticker}
                  className={`border-b border-gray-700/50 ${i % 2 === 0 ? '' : 'bg-gray-800/50'}`}
                >
                  <td className="px-4 py-2.5 font-mono text-white" style={{ color: UNDERLYING_COLORS[i % UNDERLYING_COLORS.length] }}>{u.ticker}</td>
                  <td className="px-4 py-2.5 text-gray-300">{u.name ?? '-'}</td>
                  <td className="px-4 py-2.5 text-gray-300 text-right">
                    {formatCurrency(u.initial_price)}
                  </td>
                  <td className="px-4 py-2.5 text-white text-right">
                    {u.current_price != null ? formatCurrency(u.current_price) : '-'}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono">
                    {u.pct_of_initial != null ? (
                      <span
                        className={
                          u.pct_of_initial >= 1 ? 'text-green-400' : 'text-red-400'
                        }
                      >
                        {(u.pct_of_initial * 100).toFixed(1)}%
                      </span>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-yellow-400">
                    {formatCurrency(u.coupon_barrier_price)}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-red-400">
                    {formatCurrency(u.downside_barrier_price)}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {u.above_coupon_barrier != null ? (
                      u.above_coupon_barrier ? (
                        <span className="text-green-400">Yes</span>
                      ) : (
                        <span className="text-red-400">No</span>
                      )
                    ) : (
                      '-'
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    {u.above_downside_barrier != null ? (
                      u.above_downside_barrier ? (
                        <span className="text-green-400">Yes</span>
                      ) : (
                        <span className="text-red-400">No</span>
                      )
                    ) : (
                      '-'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Coupon history */}
      <div className="bg-gray-800 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-white mb-4">Coupon History</h2>
        {calendarQuery.isLoading ? (
          <p className="text-gray-400">Loading coupon data...</p>
        ) : couponHistory.length === 0 ? (
          <p className="text-gray-500">No coupon events recorded yet.</p>
        ) : (
          <>
          <p className="text-gray-500 text-xs mb-3">
            <span className="font-bold underline text-gray-400">Bold underlined</span> values indicate the worst performing underlying for that period.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700 text-gray-400">
                  <th className="text-left px-4 py-3 font-medium">#</th>
                  <th className="text-left px-4 py-3 font-medium">Date</th>
                  <th className="text-left px-4 py-3 font-medium">Status</th>
                  <th className="text-right px-4 py-3 font-medium">Amount</th>
                  {underlyingTickers.map((ticker) => (
                    <th key={ticker} className="text-right px-4 py-3 font-medium font-mono">
                      {ticker}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {couponHistory.map((c, i) => {
                  // Build a lookup from ticker -> detail for this coupon event
                  const detailMap = new Map<string, CouponUnderlyingDetail>();
                  if (c.details) {
                    for (const d of c.details) {
                      detailMap.set(d.ticker, d);
                    }
                  }

                  return (
                    <tr
                      key={`${c.date}-${c.sequence_number}`}
                      className={`border-b border-gray-700/50 ${i % 2 === 0 ? '' : 'bg-gray-800/50'}`}
                    >
                      <td className="px-4 py-2.5 text-gray-400">{c.sequence_number}</td>
                      <td className="px-4 py-2.5 text-white font-mono">
                        {format(parseISO(c.date), 'MMM d, yyyy')}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded ${
                            c.status === 'paid'
                              ? 'bg-green-900 text-green-300'
                              : c.status === 'missed'
                                ? 'bg-red-900 text-red-300'
                                : 'bg-gray-700 text-gray-300'
                          }`}
                        >
                          {c.status}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right text-white">
                        {c.coupon_amount != null ? formatCurrency(c.coupon_amount) : '-'}
                      </td>
                      {underlyingTickers.map((ticker) => {
                        const detail = detailMap.get(ticker);
                        if (!detail) {
                          return (
                            <td key={ticker} className="px-4 py-2.5 text-right text-gray-500">
                              -
                            </td>
                          );
                        }

                        const pctDisplay = (detail.pct_of_initial * 100).toFixed(1);
                        const isWorst = ticker === c.worst_performer_ticker;

                        // Color: green if above coupon barrier, yellow if between downside and coupon barrier, red if below downside barrier
                        const aboveCoupon = detail.close_price >= detail.coupon_barrier_price;
                        // Compute downside barrier price from instrument data
                        const underlyingInfo = inst.underlyings.find((u) => u.ticker === ticker);
                        const downsideBarrierPrice = underlyingInfo?.downside_barrier_price ?? 0;
                        const aboveDownside = detail.close_price >= downsideBarrierPrice;

                        let colorClass: string;
                        if (aboveCoupon) {
                          colorClass = 'text-green-400';
                        } else if (aboveDownside) {
                          colorClass = 'text-yellow-400';
                        } else {
                          colorClass = 'text-red-400';
                        }

                        return (
                          <td
                            key={ticker}
                            className={`px-4 py-2.5 text-right font-mono ${colorClass} ${isWorst ? 'font-bold underline' : ''}`}
                          >
                            {formatCurrency(detail.close_price)}{' '}
                            <span className="text-xs">({pctDisplay}%)</span>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          </>
        )}
      </div>
    </div>
  );
}
