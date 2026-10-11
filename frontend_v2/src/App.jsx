import { lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import LandingPage from './pages/LandingPage';

// The landing page is the entry point and ships in the main bundle. The two app
// pages load on demand: a first visit should not download the dashboard, its
// socket client and the graph page just to read the hero.
const Dashboard = lazy(() => import('./pages/Dashboard'));
const KnowledgeGraph = lazy(() => import('./pages/KnowledgeGraph'));

function App() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#050505]" />}>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/graph" element={<KnowledgeGraph />} />
      </Routes>
    </Suspense>
  );
}

export default App;
