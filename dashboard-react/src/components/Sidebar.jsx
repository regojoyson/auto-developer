import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

export default function Sidebar() {
  const location = useLocation();
  const [pollActive, setPollActive] = useState(true);
  const currentRoute = location.pathname.split('/')[1] || 'pipelines';

  return (
    <aside className="w-56 bg-gray-900 text-gray-100 min-h-screen flex flex-col fixed left-0 top-0 bottom-0 z-10">
      <div className="p-5 border-b border-gray-700">
        <h1 className="text-lg font-bold tracking-tight">Auto Developer</h1>
        <p className="text-xs text-gray-400 mt-1">Pipeline Dashboard</p>
      </div>
      <nav className="flex-1 p-3 space-y-1">
        <Link
          to="/"
          className={`nav-link flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-gray-800 transition-colors ${
            currentRoute === 'pipelines' || currentRoute === '' ? 'active' : ''
          }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
          Pipelines
        </Link>
        <Link
          to="/trigger"
          className={`nav-link flex items-center gap-2 px-3 py-2 rounded-md text-sm hover:bg-gray-800 transition-colors ${
            currentRoute === 'trigger' ? 'active' : ''
          }`}
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
          </svg>
          Trigger Pipeline
        </Link>
      </nav>
      <div className="p-3 border-t border-gray-700">
        <div
          className="flex items-center gap-2 px-3 py-2 text-xs text-gray-400 cursor-pointer hover:text-gray-200 transition-colors"
          title="Click to pause/resume auto-refresh"
          onClick={() => setPollActive(!pollActive)}
        >
          <span className={`live-dot ${!pollActive ? 'paused' : ''}`} />
          <span>{pollActive ? 'Live' : 'Paused'}</span>
        </div>
      </div>
    </aside>
  );
}
