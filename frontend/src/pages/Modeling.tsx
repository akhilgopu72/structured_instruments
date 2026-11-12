import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { format, formatDistanceToNow, parseISO } from 'date-fns';
import {
  fetchCandidateMonths,
  fetchCandidates,
  fetchGmailStatus,
  fetchLatestScreenRun,
  setCandidateDismissed,
  startGmailSync,
  startScreenRun,
  type CandidateOffering,
  type ScreenParams,
  type ScreenResultRow,
  type TickerSignal,
} from '../api';
import { useUser } from '../contexts/UserContext';
import { useAccounts } from '../contexts/AccountContext';
import AccountFilter from '../components/AccountFilter';
import SummaryCard from '../components/SummaryCard';

const DEFAULT_PARAMS: ScreenParams = {
  stake: 10000,
  coupon_tax: 0.408,
  state_tax: 0,
  loss_tax: 0.238,
  erp: 0.05,
  reversal: 0,
  reversal_signal: '3m',
};

function pct(v: number | null | undefined, digits = 0): string {
  if (v == null) return '—';
  return `${(v * 100).toFixed(digits)}%`;
}

function signedPct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(1)}%`;
}

function dollars(v: number | null | undefined): string {
  if (v == null) return '—';
  const s = Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 0 });
  return `${v < 0 ? '-' : ''}$${s}`;
}

const REPLAY_FLAG_TIP =
  'History was much harsher than the simulation: replaying these terms over real 2-year windows returned at '
  + 'least 3 pts/yr less after tax, or lost principal at least 10 pts more often, than the Monte Carlo. '
  + 'Usually a stock in the basket has crashed before in a way smooth simulated paths understate. Trust the '
  + 'Hist columns over MC for this note.';

const COLUMN_TIPS = {
  cusip: 'Note identifier. ! = real history was much harsher than the simulation. ⚠ = parsed terms need checking. Hover either marker for details.',
  basket: "The underlying stocks. Coupons, autocall and losses all follow whichever stock is doing worst. Yellow = already held in the selected accounts' notes.",
  coupon: 'Annual contingent coupon, paid monthly only when every stock closes at or above the coupon barrier (usually 60% of its starting price) on the observation date.',
  db: 'Downside barrier. If the worst stock ends below this share of its starting price at maturity, you take its full loss (paid in shares).',
  fv: 'Estimated fair value per $1,000, pricing the note with option-implied volatilities. $1,000 minus this is roughly the issuer\'s built-in margin, so higher is a better-priced deal. Approximate; best used to compare notes.',
  mcLoss: 'Monte Carlo: probability the note ends below its downside barrier and loses principal.',
  lossGivenBreach: 'Monte Carlo: average loss per $1,000 in the scenarios where the barrier breaks. Breaks tend to be deep in volatile baskets.',
  mc: "Monte Carlo: expected after-tax profit per year of capital at risk, using the tax inputs above. Green = beats after-tax T-bills; red = doesn't.",
  histLoss: 'Historical replay: share of real 2-year windows (one per trading-day start date) in which these exact terms would have lost principal.',
  hist: 'Historical replay: average after-tax return per year if you had bought these terms on each historical start date. Green = beats after-tax T-bills. Best read as a crash test, not a forecast.',
  histWorst: 'Historical replay: the single worst window\'s after-tax profit or loss per $1,000.',
  histStarts: 'Years of start dates the replay covers. A short or bull-market-only span makes history look better than it should. "Too short" = less than about 2.5 years of shared price history.',
  corr: "Correlation between this note's simulated P&L and the existing book's (selected accounts). Lower = better diversifier.",
  breachInTail: 'Chance this note breaks its barrier in the scenarios where the existing book is in its worst 10%. Lower = less likely to fail at the same time as what you already own.',
  tail: "Extra dollars lost in the book's worst 5% of outcomes after adding the stake. Lower = adds less tail risk.",
  maxName: "Largest single-stock exposure after buying, as a share of principal. Worst-of notes put each note's full principal at risk to every stock in it, so shares can add up past 100%.",
};

type SortKey =
  | 'mc' | 'hist' | 'coupon' | 'fv' | 'mcLoss' | 'histLoss' | 'corr' | 'tail';

const SORTERS: Record<SortKey, (r: ScreenResultRow) => number> = {
  mc: (r) => r.aftertax_return_per_year,
  hist: (r) => r.replay?.aftertax_return_per_year ?? -Infinity,
  coupon: (r) => r.coupon_rate_annual,
  fv: (r) => r.fair_value,
  mcLoss: (r) => -r.prob_principal_loss,
  histLoss: (r) => -(r.replay?.prob_principal_loss ?? Infinity),
  corr: (r) => -(r.corr_with_book ?? 0),
  tail: (r) => -(r.tail_add ?? 0),
};

export default function Modeling() {
  const queryClient = useQueryClient();
  const { userId } = useUser();
  const { accounts, selectedAccountIds } = useAccounts();
  const [pickedMonth, setMonth] = useState<string | null>(null);
  const [params, setParams] = useState<ScreenParams>(DEFAULT_PARAMS);
  const [sortKey, setSortKey] = useState<SortKey>('mc');
  const [showSignals, setShowSignals] = useState(false);

  const monthsQuery = useQuery({
    queryKey: ['candidates', 'months', userId],
    queryFn: fetchCandidateMonths,
    enabled: userId != null,
  });

  // Default to the most recent month with offerings.
  const month = pickedMonth ?? monthsQuery.data?.[0]?.month ?? null;

  const candidatesQuery = useQuery({
    queryKey: ['candidates', 'list', userId, month],
    queryFn: () => fetchCandidates(month!),
    enabled: userId != null && month != null,
  });

  const runQuery = useQuery({
    queryKey: ['candidates', 'run', userId, month],
    queryFn: () => fetchLatestScreenRun(month!),
    enabled: userId != null && month != null,
    refetchInterval: (q) => (q.state.data?.status === 'running' ? 3000 : false),
  });

  const gmailQuery = useQuery({
    queryKey: ['candidates', 'gmail', userId],
    queryFn: fetchGmailStatus,
    enabled: userId != null,
    refetchInterval: (q) => (q.state.data?.syncing ? 4000 : 60000),
  });

  // When a sync finishes, pull in whatever it added.
  const wasSyncing = useRef(false);
  useEffect(() => {
    const syncing = gmailQuery.data?.syncing ?? false;
    if (wasSyncing.current && !syncing) {
      queryClient.invalidateQueries({ queryKey: ['candidates', 'months'] });
      queryClient.invalidateQueries({ queryKey: ['candidates', 'list'] });
    }
    wasSyncing.current = syncing;
  }, [gmailQuery.data?.syncing, queryClient]);

  const runMutation = useMutation({
    mutationFn: () => startScreenRun(month!, params),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['candidates', 'run'] }),
  });

  const syncMutation = useMutation({
    mutationFn: startGmailSync,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['candidates', 'gmail'] }),
  });

  const dismissMutation = useMutation({
    mutationFn: ({ cusip, dismissed }: { cusip: string; dismissed: boolean }) =>
      setCandidateDismissed(cusip, dismissed),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['candidates'] }),
  });

  const run = runQuery.data ?? null;
  const result = run?.status === 'done' ? run.result : null;
  const running = run?.status === 'running' || runMutation.isPending;

  const candidates = useMemo(() => candidatesQuery.data ?? [], [candidatesQuery.data]);
  const candidateByCusip = useMemo(
    () => new Map(candidates.map((c) => [c.cusip, c])),
    [candidates],
  );

  const rows = useMemo(() => {
    if (!result) return [];
    const live = result.results.filter((r) => candidateByCusip.has(r.cusip));
    return [...live].sort((a, b) => SORTERS[sortKey](b) - SORTERS[sortKey](a));
  }, [result, candidateByCusip, sortKey]);

  const unmodeled = useMemo(() => {
    const modeled = new Set(result?.results.map((r) => r.cusip) ?? []);
    return candidates.filter((c) => !modeled.has(c.cusip));
  }, [result, candidates]);

  const selectedIds = Array.from(selectedAccountIds).sort((a, b) => a - b);
  const selectionChanged =
    run != null && run.account_ids.join(',') !== selectedIds.join(',');
  const accountNames = (ids: number[]) =>
    ids.map((id) => accounts.find((a) => a.id === id)?.name ?? `#${id}`).join(', ') || 'no accounts';
  const allTaxFree =
    selectedIds.length > 0 &&
    selectedIds.every((id) => ['roth_ira', 'traditional_ira', '401k'].includes(
      accounts.find((a) => a.id === id)?.account_type ?? '',
    ));

  const hurdle = result?.aftertax_hurdle ?? 0;
  const returnClass = (v: number | null | undefined) =>
    v == null ? 'text-gray-500' : v > hurdle ? 'text-green-400' : 'text-red-400';

  if (monthsQuery.isLoading) {
    return <div className="text-gray-400">Loading…</div>;
  }

  if (monthsQuery.error) {
    return (
      <div className="rounded-md px-4 py-3 text-sm bg-red-900/50 text-red-300 border border-red-700">
        Couldn't load candidates: {(monthsQuery.error as Error).message}. If this is a 404, the API server is
        running older code — restart <code>si serve</code>.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-white">Modeling</h1>
          {monthsQuery.data && monthsQuery.data.length > 0 && (
            <select
              value={month ?? ''}
              onChange={(e) => setMonth(e.target.value)}
              className="bg-gray-800 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500"
            >
              {monthsQuery.data.map((m) => (
                <option key={m.month} value={m.month}>
                  {format(parseISO(`${m.month}-01`), 'MMMM yyyy')} ({m.count})
                </option>
              ))}
            </select>
          )}
        </div>
        <AccountFilter />
      </div>

      <GmailBar
        status={gmailQuery.data}
        onSync={() => syncMutation.mutate()}
        syncError={syncMutation.error as Error | null}
      />

      {monthsQuery.data?.length === 0 && (
        <div className="bg-gray-800 rounded-lg p-8 text-center text-gray-400">
          No offerings yet. Connect Gmail, or upload a preliminary pricing supplement on the{' '}
          <Link to="/add" className="text-blue-400 hover:underline">Add</Link> page.
        </div>
      )}

      {month && (
        <>
          {/* Model inputs */}
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex flex-wrap items-end gap-4 text-sm">
              <NumberField label="Stake ($)" value={params.stake} step={1000}
                onChange={(v) => setParams({ ...params, stake: v })} />
              <NumberField label="Coupon tax" value={params.coupon_tax} step={0.01} percent
                onChange={(v) => setParams({ ...params, coupon_tax: v })} />
              <NumberField label="State tax" value={params.state_tax} step={0.01} percent
                onChange={(v) => setParams({ ...params, state_tax: v })} />
              <NumberField label="Loss tax value" value={params.loss_tax} step={0.01} percent
                onChange={(v) => setParams({ ...params, loss_tax: v })} />
              <NumberField label="Rebound tilt" value={params.reversal} step={0.25}
                onChange={(v) => setParams({ ...params, reversal: v })} />
              <label className="flex flex-col gap-1">
                <span className="text-xs text-gray-400">Rebound signal</span>
                <select
                  value={params.reversal_signal}
                  onChange={(e) => setParams({ ...params, reversal_signal: e.target.value as '3m' | '52w' })}
                  className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white"
                >
                  <option value="3m">3-month return</option>
                  <option value="52w">Off 52-week high</option>
                </select>
              </label>
              <button
                onClick={() => setParams({ ...params, coupon_tax: 0, state_tax: 0, loss_tax: 0 })}
                className="px-3 py-1.5 rounded-md text-xs text-gray-300 border border-gray-600 hover:bg-gray-700"
                title="Coupons and losses inside an IRA/Roth aren't taxed"
              >
                Tax-free account
              </button>
              <button
                onClick={() => setParams(DEFAULT_PARAMS)}
                className="px-3 py-1.5 rounded-md text-xs text-gray-400 hover:text-white"
              >
                Reset
              </button>
              <div className="flex-1" />
              <button
                onClick={() => runMutation.mutate()}
                disabled={running || candidates.length === 0}
                className="px-4 py-2 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {running ? 'Running… (~1–2 min)' : 'Run model'}
              </button>
            </div>
            <div className="text-xs text-gray-500">
              Scores candidates against the selected accounts' active notes: {accountNames(selectedIds)}.
              {allTaxFree && params.coupon_tax > 0 && (
                <span className="text-yellow-400"> All selected accounts are tax-advantaged — consider “Tax-free account”.</span>
              )}
              {run && (
                <span>
                  {' '}Last run {formatDistanceToNow(parseISO(run.created_at))} ago against {accountNames(run.account_ids)}
                  {selectionChanged && <span className="text-yellow-400"> (selection changed — rerun)</span>}.
                </span>
              )}
            </div>
            {run?.status === 'error' && (
              <div className="rounded-md px-3 py-2 text-sm bg-red-900/50 text-red-300 border border-red-700">
                Model run failed: {run.error}
              </div>
            )}
            {runMutation.error && (
              <div className="rounded-md px-3 py-2 text-sm bg-red-900/50 text-red-300 border border-red-700">
                {(runMutation.error as Error).message}
              </div>
            )}
          </div>

          {/* Existing book */}
          {result?.book && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <SummaryCard label="Book principal" value={dollars(result.book.principal)} />
                <SummaryCard
                  label="Book expected after-tax P&L"
                  value={dollars(result.book.expected_aftertax_pnl)}
                  accent={result.book.expected_aftertax_pnl >= 0 ? 'green' : 'red'}
                />
                <SummaryCard label="Book 5% CVaR" value={dollars(result.book.cvar_5_aftertax)} accent="red" />
                <SummaryCard label="P(any note breaches)" value={pct(result.book.prob_any_breach)} accent="yellow" />
              </div>
              <div className="bg-gray-800 rounded-lg p-4 text-sm space-y-2">
                <div className="text-gray-400">
                  Name exposure:{' '}
                  {result.book.concentration.slice(0, 8).map(([t, s]) => (
                    <span key={t} className="inline-block mr-3 font-mono text-gray-200">
                      {t} <span className={s >= 0.4 ? 'text-yellow-400' : 'text-gray-400'}>{pct(s)}</span>
                    </span>
                  ))}
                </div>
                {result.book.notes.map((n) => (
                  <div key={n.cusip} className="text-xs text-gray-400 font-mono">
                    <Link to={`/instrument/${n.cusip}`} className="text-blue-400 hover:underline">{n.cusip}</Link>{' '}
                    {dollars(n.principal)}:{' '}
                    {n.levels.map((l) => (
                      <span
                        key={l.ticker}
                        className={`mr-2 ${l.pct < n.downside_barrier_pct ? 'text-red-400' : l.pct < n.coupon_barrier_pct ? 'text-yellow-400' : 'text-gray-300'}`}
                      >
                        {l.ticker} {pct(l.pct)}
                      </span>
                    ))}
                    <span className="text-gray-500">(CB {pct(n.coupon_barrier_pct)}, DB {pct(n.downside_barrier_pct)})</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Results */}
          <div className="bg-gray-800 rounded-lg overflow-x-auto">
            <table className="w-full text-sm whitespace-nowrap">
              <thead>
                <tr className="text-gray-400 text-xs border-b border-gray-700">
                  <Th label="CUSIP" align="left" tip={COLUMN_TIPS.cusip} />
                  <Th label="Basket" align="left" tip={COLUMN_TIPS.basket} />
                  <Th label="Cpn" tip={COLUMN_TIPS.coupon} sort={{ k: 'coupon', cur: sortKey, set: setSortKey }} />
                  <Th label="DB" tip={COLUMN_TIPS.db} />
                  <Th label="FV" tip={COLUMN_TIPS.fv} sort={{ k: 'fv', cur: sortKey, set: setSortKey }} />
                  <Th label="MC P(loss)" tip={COLUMN_TIPS.mcLoss} sort={{ k: 'mcLoss', cur: sortKey, set: setSortKey }} />
                  <Th label="Loss|br" tip={COLUMN_TIPS.lossGivenBreach} />
                  <Th label="MC AT/yr" tip={COLUMN_TIPS.mc} sort={{ k: 'mc', cur: sortKey, set: setSortKey }} />
                  <Th label="Hist P(loss)" tip={COLUMN_TIPS.histLoss} sort={{ k: 'histLoss', cur: sortKey, set: setSortKey }} />
                  <Th label="Hist AT/yr" tip={COLUMN_TIPS.hist} sort={{ k: 'hist', cur: sortKey, set: setSortKey }} />
                  <Th label="Hist worst" tip={COLUMN_TIPS.histWorst} />
                  <Th label="Hist starts" tip={COLUMN_TIPS.histStarts} />
                  <Th label="ρ book" tip={COLUMN_TIPS.corr} sort={{ k: 'corr', cur: sortKey, set: setSortKey }} />
                  <Th label="P(br|tail)" tip={COLUMN_TIPS.breachInTail} />
                  <Th label="Tail add" tip={COLUMN_TIPS.tail} sort={{ k: 'tail', cur: sortKey, set: setSortKey }} />
                  <Th label="Max name" tip={COLUMN_TIPS.maxName} />
                  <th className="px-3 py-3" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const c = candidateByCusip.get(r.cusip)!;
                  return (
                    <tr key={r.cusip} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                      <td className="px-3 py-2.5 font-mono text-gray-200">
                        <CandidateLabel c={c} />
                        {r.replay_flag && (
                          <Tip align="left" text={REPLAY_FLAG_TIP}>
                            <span className="ml-1 text-red-400 font-bold">!</span>
                          </Tip>
                        )}
                      </td>
                      <td className="px-3 py-2.5 font-mono text-blue-300">
                        {r.tickers.map((t) => (
                          <span key={t} className={`mr-1.5 ${r.overlap_tickers.includes(t) ? 'text-yellow-300' : ''}`}
                            title={r.overlap_tickers.includes(t) ? 'Already held in the book' : undefined}>
                            {t}
                          </span>
                        ))}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-white">{pct(r.coupon_rate_annual, 1)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{pct(r.downside_barrier_pct)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{dollars(r.fair_value)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{pct(r.prob_principal_loss)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-400">{dollars(-r.expected_loss_given_breach)}</td>
                      <td className={`px-3 py-2.5 text-right font-mono font-semibold ${returnClass(r.aftertax_return_per_year)}`}>
                        {signedPct(r.aftertax_return_per_year)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{pct(r.replay?.prob_principal_loss)}</td>
                      <td className={`px-3 py-2.5 text-right font-mono ${returnClass(r.replay?.aftertax_return_per_year)}`}>
                        {signedPct(r.replay?.aftertax_return_per_year)}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-400">{dollars(r.replay?.worst_aftertax_pnl)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-500">
                        {r.replay ? `${r.replay.first_start.slice(0, 4)}–${r.replay.last_start.slice(0, 4)}` : 'too short'}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{r.corr_with_book?.toFixed(2) ?? '—'}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{pct(r.prob_breach_in_book_tail)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-300">{dollars(r.tail_add)}</td>
                      <td className="px-3 py-2.5 text-right font-mono text-gray-400">
                        {r.max_concentration ? `${r.max_concentration[0]} ${pct(r.max_concentration[1])}` : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          onClick={() => dismissMutation.mutate({ cusip: r.cusip, dismissed: true })}
                          className="text-xs text-gray-500 hover:text-red-400"
                          title="Hide this offering"
                        >
                          Dismiss
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {unmodeled.map((c) => (
                  <tr key={c.cusip} className="border-b border-gray-700/50 bg-purple-900/10">
                    <td className="px-3 py-2.5 font-mono text-gray-200"><CandidateLabel c={c} /></td>
                    <td className="px-3 py-2.5 font-mono text-blue-300">{c.tickers.join(' ')}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-white">{pct(c.coupon_rate_annual, 1)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-gray-300">{pct(c.downside_barrier_pct)}</td>
                    <td colSpan={12} className="px-3 py-2.5 text-xs text-purple-300">
                      New since the last run{c.received_at ? ` (received ${format(parseISO(c.received_at), 'MMM d')})` : ''} — run the model to score it.
                    </td>
                    <td className="px-3 py-2.5 text-right">
                      <button
                        onClick={() => dismissMutation.mutate({ cusip: c.cusip, dismissed: true })}
                        className="text-xs text-gray-500 hover:text-red-400"
                      >
                        Dismiss
                      </button>
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && unmodeled.length === 0 && (
                  <tr>
                    <td colSpan={17} className="px-3 py-8 text-center text-gray-500">
                      {running ? 'Running the model…' : 'No candidates for this month.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {result && (
            <p className="text-xs text-gray-500 leading-relaxed">
              Returns are green above the after-tax T-bill hurdle ({pct(hurdle, 2)}/yr at r={pct(result.risk_free, 2)}).
              MC = Monte Carlo on option-implied vols with a CAPM drift. Hist = the note's terms replayed over every real
              2-year window of its basket — overlapping windows covering a few regimes, strongest as a crash test; short
              or bull-market-only histories flatter it. <span className="text-red-400 font-bold">!</span> = history much
              harsher than MC. Amounts per $1,000 except Tail add, which uses a {dollars(result.params.stake)} stake.
              Highlighted tickers are already held. Model output, not investment advice.
            </p>
          )}

          {result && result.signals.length > 0 && (
            <div className="bg-gray-800 rounded-lg">
              <button
                onClick={() => setShowSignals(!showSignals)}
                className="w-full text-left px-4 py-3 text-sm font-medium text-gray-300 hover:text-white"
              >
                {showSignals ? '▾' : '▸'} Ticker diagnostics — 52-week range, MACD, support (context only)
              </button>
              {showSignals && <SignalsTable signals={result.signals} />}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CandidateLabel({ c }: { c: CandidateOffering }) {
  const tip = [c.issuer, c.email_subject, c.source_filename].filter(Boolean).join('\n');
  return (
    <span title={tip}>
      {c.cusip}
      {c.review_notes && (
        <Tip align="left" text={`Parsed terms disagree with the attachment filename or look implausible — check the PDF: ${c.review_notes}`}>
          <span className="ml-1 text-yellow-400">⚠</span>
        </Tip>
      )}
    </span>
  );
}

function Tip({
  text, align = 'right', children,
}: { text: string; align?: 'left' | 'right'; children: React.ReactNode }) {
  return (
    <span className="relative inline-flex group cursor-help">
      {children}
      <span
        role="tooltip"
        className={`pointer-events-none absolute top-full mt-2 z-30 w-72 whitespace-normal rounded-md border border-gray-600 bg-gray-950 px-3 py-2 text-left font-sans text-xs font-normal leading-relaxed text-gray-200 shadow-lg opacity-0 transition-opacity group-hover:opacity-100 ${
          align === 'left' ? 'left-0' : 'right-0'
        }`}
      >
        {text}
      </span>
    </span>
  );
}

function Th({
  label, tip, align = 'right', dense = false, sort,
}: {
  label: string;
  tip: string;
  align?: 'left' | 'right';
  dense?: boolean;
  sort?: { k: SortKey; cur: SortKey; set: (k: SortKey) => void };
}) {
  const active = sort != null && sort.cur === sort.k;
  const text = <span className="border-b border-dotted border-gray-500">{label}</span>;
  return (
    <th className={`px-3 ${dense ? 'py-2' : 'py-3'} font-medium ${align === 'left' ? 'text-left' : 'text-right'}`}>
      <Tip text={sort ? `${tip} Click to sort.` : tip} align={align}>
        {sort ? (
          <button onClick={() => sort.set(sort.k)} className={`hover:text-white ${active ? 'text-white' : ''}`}>
            {text}{active ? ' ▾' : ''}
          </button>
        ) : text}
      </Tip>
    </th>
  );
}

function NumberField({
  label, value, step, percent = false, onChange,
}: { label: string; value: number; step: number; percent?: boolean; onChange: (v: number) => void }) {
  const display = percent ? +(value * 100).toFixed(2) : value;
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-gray-400">{label}{percent ? ' (%)' : ''}</span>
      <input
        type="number"
        value={display}
        step={percent ? step * 100 : step}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(percent ? n / 100 : n);
        }}
        className="w-24 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-white focus:outline-none focus:border-blue-500"
      />
    </label>
  );
}

function GmailBar({
  status, onSync, syncError,
}: { status: Awaited<ReturnType<typeof fetchGmailStatus>> | undefined; onSync: () => void; syncError: Error | null }) {
  if (!status) return null;
  if (!status.connected) {
    return (
      <div className="rounded-lg px-4 py-3 text-sm bg-gray-800 border border-gray-700 text-gray-400">
        Gmail not connected. Run <code className="text-gray-200">si gmail auth</code> once to pull new offerings
        from the broker emails automatically.
      </div>
    );
  }
  return (
    <div className="rounded-lg px-4 py-3 text-sm bg-gray-800 border border-gray-700 flex items-center gap-3 flex-wrap">
      <span className="w-2 h-2 rounded-full bg-green-500" />
      <span className="text-gray-300">Gmail connected</span>
      <span className="text-gray-500">
        {status.syncing
          ? 'Syncing…'
          : status.last_success_at
            ? `Last sync ${formatDistanceToNow(parseISO(status.last_success_at))} ago, ${status.last_added} new`
            : 'Not synced yet'}
      </span>
      {status.last_error && (
        <span className="text-red-400 truncate max-w-md" title={status.last_error}>Last error: {status.last_error}</span>
      )}
      {syncError && <span className="text-red-400">{syncError.message}</span>}
      <div className="flex-1" />
      <button
        onClick={onSync}
        disabled={status.syncing}
        className="px-3 py-1.5 rounded-md text-xs font-medium text-gray-200 border border-gray-600 hover:bg-gray-700 disabled:opacity-50"
      >
        Sync now
      </button>
    </div>
  );
}

function SignalsTable({ signals }: { signals: TickerSignal[] }) {
  const money = (v: number) => `$${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const level = (v: number | null, last: number) =>
    v == null ? '—' : `${money(v)} (${signedPct(v / last - 1).replace('.0%', '%')})`;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm whitespace-nowrap">
        <thead>
          <tr className="text-gray-400 text-xs border-y border-gray-700">
            <Th dense label="Ticker" align="left" tip="Underlying stock." />
            <Th dense label="Last" tip="Latest daily close." />
            <Th dense label="52w range" tip="Lowest and highest daily close over the past year." />
            <Th dense label="Pos" tip="Where the last close sits in its 52-week range: 0% = at the low, 100% = at the high." />
            <Th dense label="Off high" tip="How far the last close is below the 52-week high. Red when more than 40% below." />
            <Th dense label="MACD" tip="MACD (12/26/9) on daily closes. Bull = MACD line above its signal line, bear = below, with days since the last crossover. A short-term (weeks) momentum gauge; says little about a 2-year note." />
            <Th dense label="200d" tip="Whether the last close is above or below its 200-day moving average, a common long-term trend gauge." />
            <Th dense label="Volume support" tip="Proxy for support: the price band at least 3% below the last close where the most shares traded over the past year. Not order-book data." />
            <Th dense label="Put-OI wall" tip="Proxy for support: the put strike below the current price with the most open interest, in the nearest monthly expiry 3+ weeks out." />
            <Th dense label="Barrier if struck today" tip="Where the downside barrier would sit if the note priced at today's close (lowest barrier among this month's candidates holding the stock). Compare with the support levels: support far above the barrier doesn't protect it." />
          </tr>
        </thead>
        <tbody>
          {signals.map((s) => (
            <tr key={s.ticker} className="border-b border-gray-700/50">
              <td className="px-3 py-2 font-mono text-blue-300">{s.ticker}</td>
              <td className="px-3 py-2 text-right font-mono text-gray-200">{money(s.last)}</td>
              <td className="px-3 py-2 text-right font-mono text-gray-400">{money(s.low_52w)}–{money(s.high_52w)}</td>
              <td className="px-3 py-2 text-right font-mono text-gray-300">{pct(s.range_position)}</td>
              <td className={`px-3 py-2 text-right font-mono ${s.off_high < -0.4 ? 'text-red-400' : 'text-gray-300'}`}>
                {signedPct(s.off_high).replace('.0%', '%')}
              </td>
              <td className="px-3 py-2 text-right font-mono">
                {s.macd_bullish == null ? '—' : (
                  <span className={s.macd_bullish ? 'text-green-400' : 'text-red-400'}>
                    {s.macd_bullish ? 'bull' : 'bear'} {s.days_since_cross}d
                  </span>
                )}
              </td>
              <td className="px-3 py-2 text-right font-mono">
                {s.above_200dma == null ? '—' : (
                  <span className={s.above_200dma ? 'text-green-400' : 'text-red-400'}>{s.above_200dma ? 'above' : 'below'}</span>
                )}
              </td>
              <td className="px-3 py-2 text-right font-mono text-gray-300">{level(s.volume_support, s.last)}</td>
              <td className="px-3 py-2 text-right font-mono text-gray-300">{level(s.put_oi_support, s.last)}</td>
              <td className="px-3 py-2 text-right font-mono text-gray-400">
                {money(s.barrier_pct * s.last)} ({signedPct(s.barrier_pct - 1).replace('.0%', '%')})
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
