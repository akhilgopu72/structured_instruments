import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react';
import { fetchUsers, createUser as apiCreateUser, type UserInfo } from '../api';

interface UserContextType {
  userId: number | null;
  userName: string | null;
  users: UserInfo[];
  setUser: (id: number) => void;
  refreshUsers: () => Promise<void>;
  createUser: (name: string) => Promise<UserInfo>;
  loading: boolean;
}

const UserContext = createContext<UserContextType | null>(null);

const STORAGE_KEY = 'si-user-id';

export function UserProvider({ children }: { children: ReactNode }) {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [userId, setUserId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshUsers = useCallback(async () => {
    const list = await fetchUsers();
    setUsers(list);
    return list;
  }, []);

  // Initialize: fetch users, auto-create Default if none, restore from localStorage
  useEffect(() => {
    (async () => {
      try {
        let list = await fetchUsers();

        // If no users exist, create "Default"
        if (list.length === 0) {
          const defaultUser = await apiCreateUser('Default');
          list = [defaultUser];
        }

        setUsers(list);

        // Restore selected user from localStorage
        const stored = localStorage.getItem(STORAGE_KEY);
        const storedId = stored ? parseInt(stored, 10) : null;

        if (storedId && list.some((u) => u.id === storedId)) {
          setUserId(storedId);
        } else {
          // Default to first user
          setUserId(list[0].id);
          localStorage.setItem(STORAGE_KEY, String(list[0].id));
        }
      } catch (err) {
        console.error('Failed to initialize users:', err);
      } finally {
        setLoading(false);
      }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setUser = useCallback((id: number) => {
    setUserId(id);
    localStorage.setItem(STORAGE_KEY, String(id));
  }, []);

  const createUserFn = useCallback(async (name: string): Promise<UserInfo> => {
    const user = await apiCreateUser(name);
    setUsers((prev) => [...prev, user]);
    return user;
  }, []);

  const userName = users.find((u) => u.id === userId)?.name ?? null;

  return (
    <UserContext.Provider
      value={{
        userId,
        userName,
        users,
        setUser,
        refreshUsers,
        createUser: createUserFn,
        loading,
      }}
    >
      {children}
    </UserContext.Provider>
  );
}

export function useUser(): UserContextType {
  const ctx = useContext(UserContext);
  if (!ctx) throw new Error('useUser must be used within a UserProvider');
  return ctx;
}
