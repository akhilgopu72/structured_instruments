import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react';
import { fetchAccounts, createAccount as apiCreateAccount, setCurrentAccountIds, type AccountInfo } from '../api';
import { useUser } from './UserContext';

interface AccountContextType {
  accounts: AccountInfo[];
  selectedAccountIds: Set<number>;
  toggleAccount: (id: number) => void;
  selectAll: () => void;
  deselectAll: () => void;
  createAccount: (name: string, accountType: string) => Promise<AccountInfo>;
  refreshAccounts: () => Promise<void>;
  loading: boolean;
}

const AccountContext = createContext<AccountContextType | null>(null);

function storageKey(userId: number): string {
  return `si-accounts-${userId}`;
}

export function AccountProvider({ children }: { children: ReactNode }) {
  const { userId } = useUser();
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [selectedAccountIds, setSelectedAccountIds] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(true);

  const refreshAccounts = useCallback(async () => {
    if (userId == null) return;
    const list = await fetchAccounts();
    setAccounts(list);
    return list;
  }, [userId]);

  // Fetch accounts when userId changes
  useEffect(() => {
    if (userId == null) {
      setAccounts([]);
      setSelectedAccountIds(new Set());
      setCurrentAccountIds(null);
      setLoading(false);
      return;
    }

    (async () => {
      setLoading(true);
      try {
        const list = await fetchAccounts();
        setAccounts(list);

        // Restore selection from localStorage
        const stored = localStorage.getItem(storageKey(userId));
        let restoredIds: Set<number>;
        if (stored) {
          try {
            const parsed = JSON.parse(stored) as number[];
            // Only keep IDs that still exist
            const validIds = new Set(list.map((a) => a.id));
            restoredIds = new Set(parsed.filter((id) => validIds.has(id)));
            // If all restored IDs were invalid, select all
            if (restoredIds.size === 0) {
              restoredIds = new Set(list.map((a) => a.id));
            }
          } catch {
            restoredIds = new Set(list.map((a) => a.id));
          }
        } else {
          // Default: all accounts selected
          restoredIds = new Set(list.map((a) => a.id));
        }

        setSelectedAccountIds(restoredIds);
        setCurrentAccountIds(Array.from(restoredIds));
      } catch (err) {
        console.error('Failed to fetch accounts:', err);
      } finally {
        setLoading(false);
      }
    })();
  }, [userId]);

  // Persist selection to localStorage and sync api module
  useEffect(() => {
    if (userId == null) return;
    const ids = Array.from(selectedAccountIds);
    localStorage.setItem(storageKey(userId), JSON.stringify(ids));
    setCurrentAccountIds(ids);
  }, [selectedAccountIds, userId]);

  const toggleAccount = useCallback((id: number) => {
    setSelectedAccountIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedAccountIds(new Set(accounts.map((a) => a.id)));
  }, [accounts]);

  const deselectAll = useCallback(() => {
    setSelectedAccountIds(new Set());
  }, []);

  const createAccountFn = useCallback(async (name: string, accountType: string): Promise<AccountInfo> => {
    const account = await apiCreateAccount(name, accountType);
    setAccounts((prev) => [...prev, account]);
    // Auto-select new account
    setSelectedAccountIds((prev) => new Set([...prev, account.id]));
    return account;
  }, []);

  return (
    <AccountContext.Provider
      value={{
        accounts,
        selectedAccountIds,
        toggleAccount,
        selectAll,
        deselectAll,
        createAccount: createAccountFn,
        refreshAccounts,
        loading,
      }}
    >
      {children}
    </AccountContext.Provider>
  );
}

export function useAccounts(): AccountContextType {
  const ctx = useContext(AccountContext);
  if (!ctx) throw new Error('useAccounts must be used within an AccountProvider');
  return ctx;
}
