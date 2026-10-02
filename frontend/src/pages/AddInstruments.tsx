import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDropzone, type FileRejection } from 'react-dropzone';
import { useQueryClient } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
import {
  parsePdfs,
  commitInstruments,
  type ParsedFile,
  type CommitItem,
  type CommitResultItem,
} from '../api';
import { useAccounts } from '../contexts/AccountContext';

type Stage = 'select' | 'parsing' | 'review' | 'committing' | 'done';

interface ReviewRow {
  file: ParsedFile;
  principal: number;
  selected: boolean;
}

function formatCurrency(n: number): string {
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function pct(n: number): string {
  return `${(n * 100).toFixed(2)}%`;
}

export default function AddInstruments() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { accounts } = useAccounts();

  const [stage, setStage] = useState<Stage>('select');
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [parseError, setParseError] = useState<string | null>(null);
  const [reviewRows, setReviewRows] = useState<ReviewRow[]>([]);
  const [accountId, setAccountId] = useState<number | null>(accounts[0]?.id ?? null);
  const [commitResults, setCommitResults] = useState<CommitResultItem[]>([]);
  const [commitError, setCommitError] = useState<string | null>(null);

  useEffect(() => {
    if (accountId == null && accounts.length > 0) {
      setAccountId(accounts[0].id);
    }
  }, [accounts, accountId]);

  const onDrop = useCallback((accepted: File[], rejections: FileRejection[]) => {
    setParseError(null);
    if (rejections.length > 0) {
      setParseError(`Rejected ${rejections.length} file(s): only PDFs are accepted`);
    }
    if (accepted.length > 0) {
      setPendingFiles((prev) => [...prev, ...accepted]);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
    disabled: stage !== 'select',
  });

  function removePending(idx: number) {
    setPendingFiles((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleParse() {
    if (pendingFiles.length === 0) return;
    setStage('parsing');
    setParseError(null);
    try {
      const parsed = await parsePdfs(pendingFiles);
      const rows: ReviewRow[] = parsed.map((f) => ({
        file: f,
        principal: 10000,
        selected: f.parsed != null,
      }));
      setReviewRows(rows);
      setStage('review');
    } catch (err) {
      setParseError((err as Error).message);
      setStage('select');
    }
  }

  function updateRow(idx: number, patch: Partial<ReviewRow>) {
    setReviewRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  async function handleCommit() {
    if (accountId == null) {
      setCommitError('Please select an account');
      return;
    }
    const items: CommitItem[] = reviewRows
      .filter((r) => r.selected && r.file.parsed)
      .map((r) => ({
        parsed: r.file.parsed!,
        principal: r.principal,
        filename: r.file.filename,
      }));
    if (items.length === 0) {
      setCommitError('Select at least one instrument to add');
      return;
    }
    setCommitError(null);
    setStage('committing');
    try {
      const results = await commitInstruments(accountId, items);
      setCommitResults(results);
      setStage('done');
      // Invalidate dashboard queries so new instrument shows up
      await queryClient.invalidateQueries();
    } catch (err) {
      setCommitError((err as Error).message);
      setStage('review');
    }
  }

  function handleReset() {
    setStage('select');
    setPendingFiles([]);
    setReviewRows([]);
    setCommitResults([]);
    setCommitError(null);
    setParseError(null);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Add Instruments</h1>
          <p className="text-gray-400 text-sm mt-1">
            Upload one or more prospectus PDFs. Each will be parsed and shown for review before being added.
          </p>
        </div>
        <button
          onClick={() => navigate('/')}
          className="text-sm text-gray-400 hover:text-gray-200"
        >
          ← Back to Dashboard
        </button>
      </div>

      {/* Stage indicator */}
      <div className="flex items-center gap-3 text-sm">
        <StageStep label="1. Upload" active={stage === 'select' || stage === 'parsing'} done={stage !== 'select' && stage !== 'parsing'} />
        <span className="text-gray-600">›</span>
        <StageStep label="2. Review" active={stage === 'review' || stage === 'committing'} done={stage === 'done'} />
        <span className="text-gray-600">›</span>
        <StageStep label="3. Confirm" active={stage === 'done'} done={false} />
      </div>

      {/* Stage 1: Upload */}
      {stage === 'select' && (
        <div className="space-y-4">
          <div
            {...getRootProps()}
            className={`bg-gray-800 rounded-lg p-12 text-center border-2 border-dashed transition-colors cursor-pointer ${
              isDragActive ? 'border-blue-500 bg-blue-900/20' : 'border-gray-600 hover:border-gray-500'
            }`}
          >
            <input {...getInputProps()} />
            <svg className="w-12 h-12 mx-auto text-gray-500 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.9A5 5 0 0117 8.18 4.5 4.5 0 0117 17H7zm5-5v6m0 0l-2-2m2 2l2-2" />
            </svg>
            {isDragActive ? (
              <p className="text-blue-300">Drop the PDF{pendingFiles.length === 0 ? '' : 's'} here…</p>
            ) : (
              <>
                <p className="text-gray-300">Drag &amp; drop prospectus PDFs here, or click to browse</p>
                <p className="text-xs text-gray-500 mt-2">Accepts one or many .pdf files</p>
              </>
            )}
          </div>

          {parseError && (
            <div className="rounded-md px-4 py-3 text-sm bg-red-900/50 text-red-300 border border-red-700">
              {parseError}
            </div>
          )}

          {pendingFiles.length > 0 && (
            <div className="bg-gray-800 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">
                Selected files ({pendingFiles.length})
              </h3>
              <ul className="space-y-1.5">
                {pendingFiles.map((f, i) => (
                  <li key={i} className="flex items-center justify-between text-sm bg-gray-700/50 rounded px-3 py-2">
                    <span className="text-gray-200 font-mono truncate">{f.name}</span>
                    <div className="flex items-center gap-3">
                      <span className="text-gray-500 text-xs">{(f.size / 1024).toFixed(1)} KB</span>
                      <button
                        onClick={() => removePending(i)}
                        className="text-red-400 hover:text-red-300 text-xs"
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              <button
                onClick={handleParse}
                className="mt-4 inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
              >
                Parse {pendingFiles.length} file{pendingFiles.length === 1 ? '' : 's'} →
              </button>
            </div>
          )}
        </div>
      )}

      {/* Parsing spinner */}
      {stage === 'parsing' && (
        <div className="bg-gray-800 rounded-lg p-8 text-center">
          <div className="inline-block animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent mb-4" />
          <p className="text-gray-300">Parsing {pendingFiles.length} prospectus PDF{pendingFiles.length === 1 ? '' : 's'}…</p>
          <p className="text-gray-500 text-xs mt-1">This typically takes 5–15 seconds per file.</p>
        </div>
      )}

      {/* Stage 2: Review */}
      {(stage === 'review' || stage === 'committing') && (
        <div className="space-y-4">
          {/* Account selector */}
          <div className="bg-gray-800 rounded-lg p-4 flex items-center gap-4">
            <label className="text-sm text-gray-400">Target Account:</label>
            <select
              value={accountId ?? ''}
              onChange={(e) => setAccountId(Number(e.target.value))}
              className="bg-gray-700 border border-gray-600 rounded-md px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
              disabled={stage === 'committing'}
            >
              {accounts.length === 0 && <option value="">No accounts</option>}
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.account_type})
                </option>
              ))}
            </select>
          </div>

          {reviewRows.map((row, idx) => (
            <ReviewCard
              key={idx}
              row={row}
              disabled={stage === 'committing'}
              onChange={(patch) => updateRow(idx, patch)}
            />
          ))}

          {commitError && (
            <div className="rounded-md px-4 py-3 text-sm bg-red-900/50 text-red-300 border border-red-700">
              {commitError}
            </div>
          )}

          <div className="flex items-center gap-3">
            <button
              onClick={handleReset}
              disabled={stage === 'committing'}
              className="rounded-md px-4 py-2 text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600 disabled:opacity-50"
            >
              Start Over
            </button>
            <button
              onClick={handleCommit}
              disabled={stage === 'committing' || reviewRows.every((r) => !r.selected || !r.file.parsed)}
              className="inline-flex items-center gap-2 rounded-md bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {stage === 'committing' && (
                <span className="inline-block animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent" />
              )}
              {stage === 'committing'
                ? 'Adding…'
                : `Confirm & Add ${reviewRows.filter((r) => r.selected && r.file.parsed).length} instrument${reviewRows.filter((r) => r.selected && r.file.parsed).length === 1 ? '' : 's'}`}
            </button>
          </div>
        </div>
      )}

      {/* Stage 3: Done */}
      {stage === 'done' && (
        <div className="space-y-4">
          <div className="bg-gray-800 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-white mb-4">Results</h2>
            <ul className="space-y-2">
              {commitResults.map((r, i) => (
                <li key={i} className="flex items-start gap-3 text-sm">
                  <span
                    className={`mt-0.5 inline-flex items-center justify-center w-5 h-5 rounded-full text-xs ${
                      r.status === 'error'
                        ? 'bg-red-900 text-red-300'
                        : 'bg-green-900 text-green-300'
                    }`}
                  >
                    {r.status === 'error' ? '✕' : '✓'}
                  </span>
                  <div className="flex-1">
                    <div className="text-gray-200">
                      <span className="font-mono">{r.cusip}</span>
                      <span className="text-gray-500"> · {r.filename ?? 'unnamed'}</span>
                    </div>
                    <div className={`text-xs ${r.status === 'error' ? 'text-red-300' : 'text-gray-400'}`}>
                      {r.status === 'added'
                        ? `Added new instrument. Backfilled prices: ${Object.entries(r.prices_backfilled)
                            .map(([t, c]) => `${t}=${c}`)
                            .join(', ') || '—'}`
                        : r.status === 'position_added'
                          ? 'Added position to existing instrument'
                          : r.message}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleReset}
              className="rounded-md px-4 py-2 text-sm font-medium text-gray-300 bg-gray-700 hover:bg-gray-600"
            >
              Add More
            </button>
            <button
              onClick={() => navigate('/')}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
            >
              Go to Dashboard
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function StageStep({ label, active, done }: { label: string; active: boolean; done: boolean }) {
  return (
    <span
      className={`px-3 py-1 rounded-full text-xs font-medium ${
        active
          ? 'bg-blue-600 text-white'
          : done
            ? 'bg-green-900/50 text-green-300 border border-green-700'
            : 'bg-gray-800 text-gray-500 border border-gray-700'
      }`}
    >
      {label}
    </span>
  );
}

function ReviewCard({
  row,
  disabled,
  onChange,
}: {
  row: ReviewRow;
  disabled: boolean;
  onChange: (patch: Partial<ReviewRow>) => void;
}) {
  const { file, principal, selected } = row;

  if (file.error || !file.parsed) {
    return (
      <div className="bg-gray-800 rounded-lg p-5 border border-red-900/50">
        <div className="flex items-center justify-between mb-2">
          <span className="font-mono text-sm text-gray-300">{file.filename}</span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-red-900/50 text-red-300 border border-red-700">
            Parse failed
          </span>
        </div>
        <p className="text-sm text-red-300">{file.error ?? 'No data returned'}</p>
      </div>
    );
  }

  const p = file.parsed;
  const targetCoupon = (principal * p.coupon_rate_annual) / 12;
  const numNotes = Math.floor(principal / 1000);
  const reviewDates = p.valuation_dates.filter((v) => v.autocall_eligible);

  return (
    <div className={`bg-gray-800 rounded-lg p-5 border ${selected ? 'border-blue-900/50' : 'border-gray-700'}`}>
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-start gap-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={(e) => onChange({ selected: e.target.checked })}
            disabled={disabled}
            className="mt-1 w-4 h-4 accent-blue-600"
          />
          <div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-white">{p.issuer}</span>
              <span className="font-mono text-sm text-gray-400">{p.cusip}</span>
              {file.existing_cusip && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-yellow-900/50 text-yellow-300 border border-yellow-700">
                  Existing CUSIP — position will be added
                </span>
              )}
            </div>
            <p className="text-xs text-gray-500 font-mono">{file.filename}</p>
            {p.product_type && <p className="text-xs text-gray-400 mt-1">{p.product_type}</p>}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-400">Principal:</label>
          <span className="text-gray-500">$</span>
          <input
            type="number"
            value={principal}
            min={1000}
            step={1000}
            onChange={(e) => onChange({ principal: Number(e.target.value) })}
            disabled={disabled || !selected}
            className="w-28 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
          />
        </div>
      </div>

      {/* Bond terms grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm mb-4">
        <Stat label="Coupon Rate" value={pct(p.coupon_rate_annual)} highlight="green" />
        <Stat label="Target Coupon (monthly)" value={formatCurrency(targetCoupon)} />
        <Stat label="Coupon Barrier" value={pct(p.coupon_barrier_pct)} />
        <Stat label="Downside Barrier" value={pct(p.downside_barrier_pct)} highlight="red" />
        <Stat label="Pricing Date" value={format(parseISO(p.pricing_date), 'MMM d, yyyy')} />
        <Stat label="Maturity Date" value={format(parseISO(p.maturity_date), 'MMM d, yyyy')} />
        <Stat label="Number of Notes" value={String(numNotes)} />
        <Stat label="Total Coupons Possible" value={String(p.valuation_dates.length)} />
      </div>

      {/* Underlyings */}
      <div className="mb-4">
        <h4 className="text-xs uppercase tracking-wider text-gray-500 mb-2">Underlyings &amp; Initial Pricing</h4>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-400 text-xs border-b border-gray-700">
              <th className="text-left py-1.5">Ticker</th>
              <th className="text-left py-1.5">Name</th>
              <th className="text-right py-1.5">Initial</th>
              <th className="text-right py-1.5">Coupon Barrier</th>
              <th className="text-right py-1.5">Downside Barrier</th>
            </tr>
          </thead>
          <tbody>
            {p.underlyings.map((u) => (
              <tr key={u.ticker} className="border-b border-gray-700/30">
                <td className="py-1.5 font-mono text-blue-300">{u.ticker}</td>
                <td className="py-1.5 text-gray-300">{u.name ?? '—'}</td>
                <td className="py-1.5 text-right font-mono text-gray-200">${u.initial_price.toFixed(2)}</td>
                <td className="py-1.5 text-right font-mono text-yellow-300">
                  ${(u.initial_price * p.coupon_barrier_pct).toFixed(2)}
                </td>
                <td className="py-1.5 text-right font-mono text-red-300">
                  ${(u.initial_price * p.downside_barrier_pct).toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Review dates summary */}
      <div>
        <details className="text-sm">
          <summary className="cursor-pointer text-xs uppercase tracking-wider text-gray-500 hover:text-gray-300">
            Review Dates ({reviewDates.length} autocall-eligible / {p.valuation_dates.length} total)
          </summary>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-1.5 mt-3 max-h-48 overflow-auto pr-1">
            {p.valuation_dates.map((v) => (
              <span
                key={v.sequence_number}
                className={`text-xs font-mono px-2 py-1 rounded ${
                  v.autocall_eligible
                    ? 'bg-blue-900/30 text-blue-200 border border-blue-800'
                    : 'bg-gray-700/50 text-gray-400 border border-gray-700'
                }`}
                title={v.autocall_eligible ? 'Autocall eligible' : 'Coupon only'}
              >
                {format(parseISO(v.date), 'MMM d, yy')}
              </span>
            ))}
          </div>
        </details>
      </div>
    </div>
  );
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: 'green' | 'red' }) {
  const color = highlight === 'green' ? 'text-green-400' : highlight === 'red' ? 'text-red-400' : 'text-white';
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`font-mono ${color}`}>{value}</p>
    </div>
  );
}
