import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api';
import usePolling from '../hooks/usePolling';

export default function Logs() {
  const { issueKey } = useParams();
  const [agent, setAgent] = useState('all');
  const [logOutput, setLogOutput] = useState('');
  const [logMeta, setLogMeta] = useState({ lines: 0, agent: 'all' });
  const logRef = useRef(null);
  const autoScrollRef = useRef(true);

  const fetchLogs = useCallback(async () => {
    try {
      const data = await api.getLogs(issueKey, agent);
      setLogOutput(data.output || '(no output yet)');
      setLogMeta({ lines: data.lines || 0, agent: data.agent });
    } catch (err) {
      setLogOutput(`Error loading logs: ${err.message}`);
    }
  }, [issueKey, agent]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  usePolling(fetchLogs);

  useEffect(() => {
    if (autoScrollRef.current && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logOutput]);

  const handleScroll = () => {
    if (!logRef.current) return;
    const { scrollHeight, scrollTop, clientHeight } = logRef.current;
    autoScrollRef.current = scrollHeight - scrollTop - clientHeight < 50;
  };

  return (
    <>
      <div className="mb-4">
        <Link to={`/pipeline/${issueKey}`} className="text-blue-600 hover:text-blue-800 text-sm">
          &larr; Back to Pipeline
        </Link>
      </div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">Logs: {issueKey}</h2>
        <div className="flex items-center gap-3">
          <label className="text-sm text-gray-600">Filter:</label>
          <select
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="all">All Phases</option>
            <optgroup label="Pipeline Phases">
              <option value="orchestrator">Phase 1 — Analyze</option>
              <option value="orchestrator:plan">Phase 2 — Plan</option>
              <option value="orchestrator:implement">Phase 3 — Implement</option>
            </optgroup>
            <optgroup label="Rework">
              <option value="feedback-parser">Feedback Parser</option>
              <option value="orchestrator:rework">Rework — Apply Fixes</option>
            </optgroup>
          </select>
        </div>
      </div>
      <div ref={logRef} onScroll={handleScroll} className="log-viewer">
        {logOutput}
      </div>
      <p className="text-xs text-gray-400 mt-2">
        {logMeta.lines} lines | Filter: {logMeta.agent === 'all' ? 'All Phases' : logMeta.agent}
      </p>
    </>
  );
}
