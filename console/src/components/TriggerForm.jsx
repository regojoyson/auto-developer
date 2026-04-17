import { useState } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useToast } from './ToastContext';

export default function TriggerForm() {
  const [issueKey, setIssueKey] = useState('');
  const [summary, setSummary] = useState('');
  const [component, setComponent] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const showToast = useToast();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setResult(null);

    const payload = { issueKey: issueKey.trim() };
    if (summary.trim()) payload.summary = summary.trim();
    if (component.trim()) payload.component = component.trim();

    try {
      const data = await api.trigger(payload);
      if (data.accepted) {
        setResult({
          type: 'success',
          issueKey: data.issueKey,
          branch: data.branch,
        });
        showToast('Pipeline triggered successfully');
      } else if (data.error) {
        setResult({ type: 'error', message: data.error });
        showToast(data.error, 'error');
      }
    } catch (err) {
      setResult({ type: 'error', message: `Request failed: ${err.message}` });
      showToast('Failed to trigger pipeline', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <h2 className="text-2xl font-bold mb-6">Trigger Pipeline</h2>
      <div className="detail-card max-w-lg">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Issue Key <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              required
              placeholder="PROJ-42"
              value={issueKey}
              onChange={(e) => setIssueKey(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Summary</label>
            <input
              type="text"
              placeholder="Add login page"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Component</label>
            <input
              type="text"
              placeholder="frontend-app"
              value={component}
              onChange={(e) => setComponent(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          {result && result.type === 'success' && (
            <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
              Pipeline started for <strong>{result.issueKey}</strong> on branch{' '}
              <code className="text-xs">{result.branch}</code>.
              <Link to={`/pipeline/${result.issueKey}`} className="underline font-medium ml-1">
                View pipeline
              </Link>
            </div>
          )}

          {result && result.type === 'error' && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
              {result.message}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full px-4 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors disabled:opacity-50"
          >
            {submitting ? 'Triggering...' : 'Trigger Pipeline'}
          </button>
        </form>
      </div>
    </>
  );
}
