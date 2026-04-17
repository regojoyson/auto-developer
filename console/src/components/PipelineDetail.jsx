import { useState, useEffect, useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
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

export default function PipelineDetail() {
  const { issueKey } = useParams();
  const [pipeline, setPipeline] = useState(null);
  const [error, setError] = useState(null);
  const showToast = useToast();

  const fetchData = useCallback(async () => {
    try {
      const data = await api.getPipeline(issueKey);
      if (data.error) {
        setError(data.error);
      } else {
        setPipeline(data);
        setError(null);
      }
    } catch (err) {
      setError(err.message);
    }
  }, [issueKey]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  usePolling(fetchData);

  const handleCancel = async () => {
    if (!window.confirm(`Cancel pipeline for ${issueKey}? This will delete state and logs.`)) return;
    try {
      const data = await api.cancel(issueKey);
      if (data.cancelled) {
        showToast(`Pipeline ${issueKey} cancelled`);
        window.location.hash = '#/';
      } else {
        showToast(data.error || 'Failed to cancel', 'error');
      }
    } catch (err) {
      showToast(`Error: ${err.message}`, 'error');
    }
  };

  return (
    <>
      <div className="mb-4">
        <Link to="/" className="text-blue-600 hover:text-blue-800 text-sm">&larr; Back to Pipelines</Link>
      </div>

      {error && <p className="text-red-500">{error}</p>}

      {!error && !pipeline && <p className="text-gray-400">Loading...</p>}

      {pipeline && (
        <>
          <div className="flex items-center gap-4 mb-6">
            <h2 className="text-2xl font-bold">{pipeline.issueKey}</h2>
            <StateBadge state={pipeline.state} />
          </div>
          <div className="detail-card mb-6">
            <div className="detail-field">
              <span className="detail-label">Branch</span>
              <span className="detail-value font-mono text-sm">{pipeline.branch}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Repo Path</span>
              <span className="detail-value font-mono text-sm">{pipeline.repoPath || '\u2014'}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Created</span>
              <span className="detail-value">{formatDate(pipeline.createdAt)}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Updated</span>
              <span className="detail-value">{formatDate(pipeline.updatedAt)}</span>
            </div>
            <div className="detail-field">
              <span className="detail-label">Rework Count</span>
              <span className="detail-value">{pipeline.reworkCount || 0}</span>
            </div>
          </div>
          <div className="flex gap-3">
            <Link to={`/logs/${pipeline.issueKey}`} className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm hover:bg-indigo-700">
              View Logs
            </Link>
            <button onClick={handleCancel} className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700">
              Cancel Pipeline
            </button>
          </div>
        </>
      )}
    </>
  );
}
