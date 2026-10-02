import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { UserProvider } from './contexts/UserContext';
import { AccountProvider } from './contexts/AccountContext';
import Navbar from './components/Navbar';
import Dashboard from './pages/Dashboard';
import InstrumentDetail from './pages/InstrumentDetail';
import CouponCalendar from './pages/CouponCalendar';
import Performance from './pages/Performance';
import AddInstruments from './pages/AddInstruments';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: 1,
    },
  },
});

export { queryClient };

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UserProvider>
        <AccountProvider>
          <BrowserRouter>
            <div className="min-h-screen bg-gray-900 text-gray-100">
              <Navbar />
              <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
                <Routes>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/instrument/:cusip" element={<InstrumentDetail />} />
                  <Route path="/calendar" element={<CouponCalendar />} />
                  <Route path="/performance" element={<Performance />} />
                  <Route path="/add" element={<AddInstruments />} />
                </Routes>
              </main>
            </div>
          </BrowserRouter>
        </AccountProvider>
      </UserProvider>
    </QueryClientProvider>
  );
}

export default App;
