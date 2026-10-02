import { useState, useRef, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useUser } from '../contexts/UserContext';
import { useAccounts } from '../contexts/AccountContext';
import { setCurrentUserId } from '../api';

const ACCOUNT_TYPES = [
  { value: 'personal', label: 'Personal' },
  { value: 'roth_ira', label: 'Roth IRA' },
  { value: 'traditional_ira', label: 'Traditional IRA' },
  { value: '401k', label: '401(k)' },
];

export default function Navbar() {
  const { userId, userName, users, setUser, createUser } = useUser();
  const { createAccount: createAccountFn } = useAccounts();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [addingUser, setAddingUser] = useState(false);
  const [addingAccount, setAddingAccount] = useState(false);
  const [newUserName, setNewUserName] = useState('');
  const [newAccountName, setNewAccountName] = useState('');
  const [newAccountType, setNewAccountType] = useState('personal');
  const dropdownRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  // Sync api module's userId whenever context changes
  useEffect(() => {
    setCurrentUserId(userId);
  }, [userId]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
        setAddingUser(false);
        setAddingAccount(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  function handleSelectUser(id: number) {
    setUser(id);
    setCurrentUserId(id);
    setDropdownOpen(false);
    queryClient.invalidateQueries();
  }

  async function handleAddUser() {
    const trimmed = newUserName.trim();
    if (!trimmed) return;
    try {
      const user = await createUser(trimmed);
      setNewUserName('');
      setAddingUser(false);
      handleSelectUser(user.id);
    } catch (err) {
      console.error('Failed to create user:', err);
    }
  }

  async function handleAddAccount() {
    const trimmed = newAccountName.trim();
    if (!trimmed) return;
    try {
      await createAccountFn(trimmed, newAccountType);
      setNewAccountName('');
      setNewAccountType('personal');
      setAddingAccount(false);
      queryClient.invalidateQueries();
    } catch (err) {
      console.error('Failed to create account:', err);
    }
  }

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded-md text-sm font-medium transition-colors ${
      isActive
        ? 'bg-blue-600 text-white'
        : 'text-gray-300 hover:bg-gray-700 hover:text-white'
    }`;

  return (
    <nav className="bg-gray-800 border-b border-gray-700">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <div className="flex items-center gap-2">
            <span className="text-blue-400 font-bold text-lg">SI</span>
            <span className="text-white font-semibold text-lg hidden sm:inline">
              Structured Instruments
            </span>
          </div>
          <div className="flex items-center gap-2">
            <NavLink to="/" className={linkClass} end>
              Dashboard
            </NavLink>
            <NavLink to="/calendar" className={linkClass}>
              Calendar
            </NavLink>
            <NavLink to="/performance" className={linkClass}>
              Performance
            </NavLink>
            <NavLink to="/add" className={linkClass}>
              Add
            </NavLink>

            {/* User dropdown */}
            <div className="relative ml-3" ref={dropdownRef}>
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium text-gray-300 hover:bg-gray-700 hover:text-white transition-colors border border-gray-600"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                <span>{userName ?? 'User'}</span>
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {dropdownOpen && (
                <div className="absolute right-0 mt-1 w-48 rounded-md bg-gray-800 border border-gray-600 shadow-lg z-30">
                  <div className="py-1">
                    {users.map((u) => (
                      <button
                        key={u.id}
                        onClick={() => handleSelectUser(u.id)}
                        className={`w-full text-left px-4 py-2 text-sm transition-colors ${
                          u.id === userId
                            ? 'bg-blue-600/20 text-blue-300'
                            : 'text-gray-300 hover:bg-gray-700'
                        }`}
                      >
                        {u.name}
                        {u.id === userId && (
                          <span className="ml-2 text-xs text-blue-400">&#10003;</span>
                        )}
                      </button>
                    ))}
                    <div className="border-t border-gray-600 mt-1 pt-1">
                      {addingUser ? (
                        <div className="px-3 py-2">
                          <input
                            autoFocus
                            type="text"
                            value={newUserName}
                            onChange={(e) => setNewUserName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleAddUser();
                              if (e.key === 'Escape') { setAddingUser(false); setNewUserName(''); }
                            }}
                            placeholder="User name"
                            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                          />
                          <div className="flex gap-1 mt-1.5">
                            <button
                              onClick={handleAddUser}
                              className="flex-1 text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
                            >
                              Add
                            </button>
                            <button
                              onClick={() => { setAddingUser(false); setNewUserName(''); }}
                              className="flex-1 text-xs px-2 py-1 bg-gray-600 text-gray-300 rounded hover:bg-gray-500"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={() => setAddingUser(true)}
                          className="w-full text-left px-4 py-2 text-sm text-gray-400 hover:bg-gray-700 hover:text-white"
                        >
                          + Add User
                        </button>
                      )}
                    </div>
                    <div className="border-t border-gray-600 pt-1">
                      {addingAccount ? (
                        <div className="px-3 py-2">
                          <input
                            autoFocus
                            type="text"
                            value={newAccountName}
                            onChange={(e) => setNewAccountName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') handleAddAccount();
                              if (e.key === 'Escape') { setAddingAccount(false); setNewAccountName(''); }
                            }}
                            placeholder="Account name"
                            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white placeholder-gray-400 focus:outline-none focus:border-blue-500"
                          />
                          <select
                            value={newAccountType}
                            onChange={(e) => setNewAccountType(e.target.value)}
                            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white mt-1.5 focus:outline-none focus:border-blue-500"
                          >
                            {ACCOUNT_TYPES.map((t) => (
                              <option key={t.value} value={t.value}>{t.label}</option>
                            ))}
                          </select>
                          <div className="flex gap-1 mt-1.5">
                            <button
                              onClick={handleAddAccount}
                              className="flex-1 text-xs px-2 py-1 bg-blue-600 text-white rounded hover:bg-blue-700"
                            >
                              Add
                            </button>
                            <button
                              onClick={() => { setAddingAccount(false); setNewAccountName(''); }}
                              className="flex-1 text-xs px-2 py-1 bg-gray-600 text-gray-300 rounded hover:bg-gray-500"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={() => setAddingAccount(true)}
                          className="w-full text-left px-4 py-2 text-sm text-gray-400 hover:bg-gray-700 hover:text-white"
                        >
                          + Add Account
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </nav>
  );
}
