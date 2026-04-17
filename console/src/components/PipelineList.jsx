import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import usePolling from '../hooks/usePolling';
import { useToast } from './ToastContext';

function StateBadge({ state }) {
  const s = (state || 'unknown').replace(/\s+/g, '-');
  return <span className={`badge badge-${s}`}>{s}</span>;
}

function formatDate(iso) {
  if (!iso) return '\u2014';
  return new Date(iso).toLocaleString();
}

export default function PipelineList() {
  const [pipelines, setPipelines] = useState(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState(null);
  const showToast = useToast();

  const fetchData = useCallback(async () => {
    try {
      const data = await api.listPipelines();
      setPipelines(data.pipelines || []);
      setCount(data.count || 0);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  usePolling(fetchData);

  const handleStop = async (issueKey) => {
    if (!window.confirm(`Stop the running agent for ${issueKey}? State and logs are kept.`)) return;
    try {
      const data = await api.stop(issueKey);
      if (data.stopped) {
        showToast(`Pipeline ${issueKey} stopping…`);
        fetchData();
      } else {
        showToast(data.reason || 'No running agent to stop', 'error');
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    }
  };

  const handleCancel = async (issueKey) => {
    if (!window.confirm(`Cancel pipeline for ${issueKey}? This will delete state and logs.`)) return;
    try {
      const data = await api.cancel(issueKey);
      if (data.cancelled) {
        showToast(`Pipeline ${issueKey} cancelled`);
        fetchData();
      } else {
        showToast(data.error || 'Failed to cancel', 'error');
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    }
  };

  const isRunning = (state) => !['failed', 'merged', 'awaiting-review'].includes(state);

  if (error) {
    return <p className="text-red-500">Failed to load pipelines: {error}</p>;
  }

  if (pipelines === null) {
    return <p className="text-gray-400">Loading...</p>;
  }

  if (pipelines.length === 0) {
    return (
      <div className="text-center py-16 text-gray-400">
        <svg className="w-12 h-12 mx-auto mb-4 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
        </svg>
        <p className="text-lg font-medium">No pipelines found</p>
        <p className="mt-1">Trigger one to get started.</p>
        <Link to="/trigger" className="inline-block mt-4 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700">
          Trigger Pipeline
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Pipelines</h2>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
        <table className="pipeline-table">
          <thead>
            <tr>
              <th>Issue Key</th>
              <th>State</th>
              <th>Branch</th>
              <th>Created</th>
              <th>Updated</th>
              <th>Reworks</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pipelines.map((p) => (
              <tr key={p.issueKey}>
                <td className="font-medium">{p.issueKey}</td>
                <td><StateBadge state={p.state} /></td>
                <td className="text-xs font-mono text-gray-500">{p.branch}</td>
                <td className="text-sm text-gray-500">{formatDate(p.createdAt)}</td>
                <td className="text-sm text-gray-500">{formatDate(p.updatedAt)}</td>
                <td className="text-center">{p.reworkCount || 0}</td>
                <td>
                  <div className="flex gap-3">
                    <Link to={`/pipeline/${p.issueKey}`} className="text-blue-600 hover:text-blue-800 text-sm font-medium">
                      Open
                    </Link>
                    {isRunning(p.state) && (
                      <button onClick={() => handleStop(p.issueKey)} className="text-amber-600 hover:text-amber-700 text-sm font-medium">
                        Stop
                      </button>
                    )}
                    <button onClick={() => handleCancel(p.issueKey)} className="text-red-600 hover:text-red-800 text-sm font-medium">
                      Cancel
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-400 mt-2">{count} pipeline(s)</p>
    </>
  );
}
