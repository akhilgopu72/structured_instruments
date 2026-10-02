import { useState, useRef, useEffect } from 'react';
import { useAccounts } from '../contexts/AccountContext';

const TYPE_COLORS: Record<string, string> = {
  personal: 'bg-blue-900 text-blue-300',
  roth_ira: 'bg-green-900 text-green-300',
  traditional_ira: 'bg-yellow-900 text-yellow-300',
  '401k': 'bg-purple-900 text-purple-300',
};

const TYPE_LABELS: Record<string, string> = {
  personal: 'Personal',
  roth_ira: 'Roth IRA',
  traditional_ira: 'Trad IRA',
  '401k': '401(k)',
};

export default function AccountFilter() {
  const { accounts, selectedAccountIds, toggleAccount, selectAll, deselectAll } = useAccounts();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  if (accounts.length === 0) return null;

  const allSelected = selectedAccountIds.size === accounts.length;
  const noneSelected = selectedAccountIds.size === 0;

  let label: string;
  if (allSelected) {
    label = 'All Accounts';
  } else if (noneSelected) {
    label = 'No Accounts';
  } else if (selectedAccountIds.size === 1) {
    const selected = accounts.find((a) => selectedAccountIds.has(a.id));
    label = selected?.name ?? '1 Account';
  } else {
    label = `${selectedAccountIds.size} Accounts`;
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium text-gray-300 hover:bg-gray-700 hover:text-white transition-colors border border-gray-600 bg-gray-800"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        <span>{label}</span>
        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-64 rounded-md bg-gray-800 border border-gray-600 shadow-lg z-30">
          <div className="p-2 border-b border-gray-700 flex gap-2">
            <button
              onClick={selectAll}
              className="flex-1 text-xs px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
            >
              All
            </button>
            <button
              onClick={deselectAll}
              className="flex-1 text-xs px-2 py-1 rounded bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
            >
              None
            </button>
          </div>
          <div className="py-1 max-h-60 overflow-y-auto">
            {accounts.map((account) => {
              const isSelected = selectedAccountIds.has(account.id);
              return (
                <button
                  key={account.id}
                  onClick={() => toggleAccount(account.id)}
                  className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-gray-700 transition-colors"
                >
                  <span
                    className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 ${
                      isSelected
                        ? 'bg-blue-600 border-blue-600'
                        : 'border-gray-500'
                    }`}
                  >
                    {isSelected && (
                      <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </span>
                  <span className="text-gray-200 flex-1">{account.name}</span>
                  <span className={`text-xs px-1.5 py-0.5 rounded ${TYPE_COLORS[account.account_type] ?? 'bg-gray-700 text-gray-300'}`}>
                    {TYPE_LABELS[account.account_type] ?? account.account_type}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
