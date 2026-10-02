import { useState, useMemo } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import {
  format,
  parseISO,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addDays,
  addMonths,
  subMonths,
  isSameMonth,
  isSameDay,
} from 'date-fns';
import { Link } from 'react-router-dom';
import { fetchCouponCalendar, fetchInstruments, type CouponCalendarEntry } from '../api';
import { useUser } from '../contexts/UserContext';
import { useAccounts } from '../contexts/AccountContext';
import AccountFilter from '../components/AccountFilter';

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(value);
}

interface CouponInstrumentItem { cusip: string; issuer: string; amount: number }

function CouponCountPopover({ count, items }: { count: number; items: CouponInstrumentItem[] }) {
  if (count === 0) return <span className="text-base font-normal text-gray-500">({count})</span>;
  return (
    <span className="group/pop relative cursor-help inline-block">
      <span className="text-base font-normal text-gray-500 underline decoration-dotted decoration-gray-600">({count})</span>
      <span className="pointer-events-none group-hover/pop:pointer-events-auto absolute left-0 top-full pt-2 w-56 opacity-0 group-hover/pop:opacity-100 transition-opacity duration-300 z-20">
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

export default function CouponCalendar() {
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const { userId } = useUser();
  const { selectedAccountIds } = useAccounts();
  const accountIds = Array.from(selectedAccountIds).sort().join(',');

  const calendarQuery = useQuery({
    queryKey: ['coupons', 'calendar', userId, accountIds],
    queryFn: fetchCouponCalendar,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const instrumentsQuery = useQuery({
    queryKey: ['instruments', userId, accountIds],
    queryFn: fetchInstruments,
    enabled: userId != null && selectedAccountIds.size > 0,
    placeholderData: keepPreviousData,
  });

  const noAccounts = selectedAccountIds.size === 0;
  const entries = noAccounts ? [] : (calendarQuery.data ?? []);
  const instruments = noAccounts ? undefined : instrumentsQuery.data;

  // Index entries by date string
  const entriesByDate = useMemo(() => {
    const map: Record<string, CouponCalendarEntry[]> = {};
    entries.forEach((e) => {
      if (!map[e.date]) map[e.date] = [];
      map[e.date].push(e);
    });
    return map;
  }, [entries]);

  // Build calendar grid
  const monthStart = startOfMonth(currentMonth);
  const monthEnd = endOfMonth(currentMonth);
  const calStart = startOfWeek(monthStart);
  const calEnd = endOfWeek(monthEnd);

  const days: Date[] = [];
  let day = calStart;
  while (day <= calEnd) {
    days.push(day);
    day = addDays(day, 1);
  }

  const weeks: Date[][] = [];
  for (let i = 0; i < days.length; i += 7) {
    weeks.push(days.slice(i, i + 7));
  }

  // Get dominant status for a date
  function getDateStatus(dateStr: string): string | null {
    const dayEntries = entriesByDate[dateStr];
    if (!dayEntries || dayEntries.length === 0) return null;
    if (dayEntries.some((e) => e.status === 'paid')) return 'paid';
    if (dayEntries.some((e) => e.status === 'missed')) return 'missed';
    return 'upcoming';
  }

  // Summary stats for the currently displayed month
  const monthStats = useMemo(() => {
    const instByCusip: Record<string, { principal: number; monthlyRate: number }> = {};
    instruments?.forEach((inst) => {
      instByCusip[inst.cusip] = {
        principal: inst.principal ?? 0,
        monthlyRate: inst.coupon_rate_annual / 12,
      };
    });

    let paidCount = 0;
    let paidAmount = 0;
    const paidInstruments: CouponInstrumentItem[] = [];
    let missedCount = 0;
    let missedAmount = 0;
    const missedInstruments: CouponInstrumentItem[] = [];
    for (const entry of entries) {
      const entryDate = parseISO(entry.date);
      if (!isSameMonth(entryDate, currentMonth)) continue;
      if (entry.status === 'paid') {
        paidCount += 1;
        paidAmount += entry.coupon_amount ?? 0;
        paidInstruments.push({ cusip: entry.cusip, issuer: entry.issuer, amount: entry.coupon_amount ?? 0 });
      } else if (entry.status === 'missed') {
        missedCount += 1;
        const inst = instByCusip[entry.cusip];
        const missedAmt = inst ? inst.principal * inst.monthlyRate : 0;
        missedAmount += missedAmt;
        missedInstruments.push({ cusip: entry.cusip, issuer: entry.issuer, amount: missedAmt });
      }
    }
    return { paidCount, paidAmount, paidInstruments, missedCount, missedAmount, missedInstruments };
  }, [entries, instruments, currentMonth]);

  const selectedEntries = selectedDate ? entriesByDate[selectedDate] ?? [] : [];

  if (calendarQuery.isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400 text-lg">Loading calendar...</div>
      </div>
    );
  }

  if (calendarQuery.error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400 text-lg">
          Error: {(calendarQuery.error as Error).message}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">Coupon Calendar</h1>
        <AccountFilter />
      </div>

      {/* Month navigation */}
      <div className="flex items-center justify-between bg-gray-800 rounded-lg p-4">
        <button
          onClick={() => setCurrentMonth(subMonths(currentMonth, 1))}
          className="text-gray-400 hover:text-white px-3 py-1.5 rounded hover:bg-gray-700 transition-colors"
        >
          Previous
        </button>
        <h2 className="text-xl font-semibold text-white">
          {format(currentMonth, 'MMMM yyyy')}
        </h2>
        <button
          onClick={() => setCurrentMonth(addMonths(currentMonth, 1))}
          className="text-gray-400 hover:text-white px-3 py-1.5 rounded hover:bg-gray-700 transition-colors"
        >
          Next
        </button>
      </div>

      {/* Monthly summary stats */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm">Coupons Received</p>
          <p className="text-2xl font-bold text-green-400 mt-1">
            {formatCurrency(monthStats.paidAmount)}{' '}
            <CouponCountPopover count={monthStats.paidCount} items={monthStats.paidInstruments} />
          </p>
        </div>
        <div className="bg-gray-800 rounded-lg p-4">
          <p className="text-gray-400 text-sm">Coupons Missed</p>
          <p className={`text-2xl font-bold mt-1 ${monthStats.missedCount > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {formatCurrency(monthStats.missedAmount)}{' '}
            <CouponCountPopover count={monthStats.missedCount} items={monthStats.missedInstruments} />
          </p>
        </div>
      </div>

      {/* Calendar grid */}
      <div className="bg-gray-800 rounded-lg overflow-hidden">
        {/* Day headers */}
        <div className="grid grid-cols-7 border-b border-gray-700">
          {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
            <div key={d} className="text-center py-3 text-gray-400 text-sm font-medium">
              {d}
            </div>
          ))}
        </div>

        {/* Weeks */}
        {weeks.map((week, wi) => (
          <div key={wi} className="grid grid-cols-7 border-b border-gray-700/50 last:border-b-0">
            {week.map((d) => {
              const dateStr = format(d, 'yyyy-MM-dd');
              const inMonth = isSameMonth(d, currentMonth);
              const status = getDateStatus(dateStr);
              const isSelected = selectedDate === dateStr;
              const isToday = isSameDay(d, new Date());
              const hasEntries = status !== null;

              let bgClass = '';
              if (isSelected) {
                bgClass = 'bg-blue-900/50 ring-1 ring-blue-500';
              }

              return (
                <button
                  key={dateStr}
                  onClick={() => hasEntries && setSelectedDate(isSelected ? null : dateStr)}
                  className={`min-h-16 p-2 text-left transition-colors ${
                    inMonth ? 'text-white' : 'text-gray-600'
                  } ${bgClass} ${hasEntries ? 'cursor-pointer hover:bg-gray-700' : 'cursor-default'}`}
                >
                  <span
                    className={`text-sm ${
                      isToday ? 'bg-blue-600 text-white rounded-full w-6 h-6 flex items-center justify-center' : ''
                    }`}
                  >
                    {format(d, 'd')}
                  </span>
                  {hasEntries && (
                    <div className="mt-1 flex gap-1">
                      {(entriesByDate[dateStr] ?? []).map((entry, ei) => {
                        const dc = entry.status === 'paid' ? 'bg-green-500'
                          : entry.status === 'missed' ? 'bg-red-500'
                          : 'bg-gray-500';
                        return <div key={ei} className={`w-2 h-2 rounded-full ${dc}`} />;
                      })}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="flex items-center gap-6 text-sm text-gray-400">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-green-500" />
          <span>Paid</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-red-500" />
          <span>Missed</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-gray-500" />
          <span>Upcoming</span>
        </div>
      </div>

      {/* Selected date detail */}
      {selectedDate && selectedEntries.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-white mb-4">
            {format(parseISO(selectedDate), 'MMMM d, yyyy')}
          </h3>
          <div className="space-y-3">
            {selectedEntries.map((e, i) => (
              <div
                key={`${e.cusip}-${i}`}
                className="flex items-center justify-between bg-gray-700/50 rounded-lg p-4"
              >
                <div>
                  <p className="text-white font-medium">{e.issuer}</p>
                  <p className="text-gray-400 text-sm font-mono">{e.cusip}</p>
                  <p className="text-gray-500 text-xs mt-1">Period #{e.sequence_number}</p>
                </div>
                <div className="text-right">
                  <span
                    className={`text-sm font-medium px-2 py-0.5 rounded ${
                      e.status === 'paid'
                        ? 'bg-green-900 text-green-300'
                        : e.status === 'missed'
                          ? 'bg-red-900 text-red-300'
                          : 'bg-gray-600 text-gray-300'
                    }`}
                  >
                    {e.status}
                  </span>
                  {e.coupon_amount != null && (
                    <p className="text-white font-semibold mt-1">
                      {formatCurrency(e.coupon_amount)}
                    </p>
                  )}
                  {e.worst_performer_ticker && (
                    <p className="text-gray-400 text-xs mt-0.5">
                      Worst: {e.worst_performer_ticker}{' '}
                      {e.worst_performer_pct != null
                        ? `(${(e.worst_performer_pct * 100).toFixed(1)}%)`
                        : ''}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
