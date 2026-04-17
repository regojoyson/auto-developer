import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api';
import usePolling from '../hooks/usePolling';
import { useToast } from './ToastContext';

// Pipeline phase definitions in order
const PIPELINE_PHASES = [
  { key: 'analyzing', label: 'Analyze', desc: 'Reading ticket, writing TICKET.md' },
  { key: 'planning', label: 'Plan', desc: 'Exploring code, writing PLAN.md' },
  { key: 'developing', label: 'Implement', desc: 'Writing code, creating MR' },
  { key: 'awaiting-review', label: 'Review', desc: 'Waiting for human approval' },
];

const STATE_ORDER = ['analyzing', 'planning', 'developing', 'awaiting-review', 'merged'];

function StateBadge({ state }) {
  const s = (state || 'unknown').replace(/\s+/g, '-');
  return <span className={`badge badge-${s}`}>{s}</span>;
}

function formatDate(iso) {
  if (!iso) return '\u2014';
  return new Date(iso).toLocaleString();
}

function formatDuration(secs) {
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return remSecs ? `${mins}m ${remSecs}s` : `${mins}m`;
}

function getPhaseStatus(phase, currentState, phases) {
  const phaseRecord = phases.find(p => p.phase === phase.key);
  const currentIdx = STATE_ORDER.indexOf(currentState);
  const phaseIdx = STATE_ORDER.indexOf(phase.key);

  let status, statusColor, ringColor, label, duration = '';

  if (phaseRecord && phaseRecord.result === 'success') {
    status = 'completed'; statusColor = 'bg-green-500 text-white'; ringColor = 'ring-green-500'; label = 'Completed';
  } else if (phaseRecord && phaseRecord.result === 'failed') {
    status = 'failed'; statusColor = 'bg-red-500 text-white'; ringColor = 'ring-red-500'; label = 'Failed';
  } else if (phaseRecord && phaseRecord.result === 'blocked') {
    status = 'blocked'; statusColor = 'bg-yellow-500 text-white'; ringColor = 'ring-yellow-500'; label = 'Blocked';
  } else if (currentState === phase.key) {
    status = 'active'; statusColor = 'bg-blue-500 text-white'; ringColor = 'ring-blue-500'; label = 'Running';
  } else if (currentState === 'failed' && phaseIdx >= currentIdx) {
    status = 'skipped'; statusColor = 'bg-gray-200 text-gray-400'; ringColor = 'ring-gray-200'; label = 'Skipped';
  } else if (phaseIdx < currentIdx) {
    status = 'completed'; statusColor = 'bg-green-500 text-white'; ringColor = 'ring-green-500'; label = 'Completed';
  } else {
    status = 'pending'; statusColor = 'bg-gray-200 text-gray-400'; ringColor = 'ring-gray-200'; label = 'Pending';
  }

  if (phaseRecord && phaseRecord.startedAt) {
    const start = new Date(phaseRecord.startedAt);
    const end = phaseRecord.completedAt ? new Date(phaseRecord.completedAt) : new Date();
    duration = formatDuration(Math.round((end - start) / 1000));
  }

  return { status, statusColor, ringColor, label, duration };
}

function PipelineProgress({ pipeline }) {
  const currentState = pipeline.state || 'analyzing';
  const phases = pipeline.phases || [];
  const isMerged = currentState === 'merged';
  const isFailed = currentState === 'failed';

  // Calculate total elapsed time
  const totalElapsed = useMemo(() => {
    if (!pipeline.createdAt) return '';
    const start = new Date(pipeline.createdAt);
    const end = (isMerged || currentState === 'awaiting-review') && pipeline.updatedAt
      ? new Date(pipeline.updatedAt)
      : new Date();
    return formatDuration(Math.round((end - start) / 1000));
  }, [pipeline.createdAt, pipeline.updatedAt, currentState, isMerged]);

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm mb-6">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <h3 className="font-semibold text-gray-800">Pipeline Progress</h3>
          <StateBadge state={currentState} />
          {pipeline.reworkCount > 0 && (
            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full font-medium">
              Rework #{pipeline.reworkCount}
            </span>
          )}
        </div>
        {totalElapsed && (
          <div className="text-sm text-gray-500">
            Total: <span className="font-medium text-gray-700">{totalElapsed}</span>
          </div>
        )}
      </div>

      {/* Progress steps */}
      <div className="flex items-start justify-between relative">
        {PIPELINE_PHASES.map((phase, idx) => {
          const ps = getPhaseStatus(phase, currentState, phases);
          return (
            <div key={phase.key} className="flex items-start flex-1 relative">
              <div className="flex flex-col items-center flex-1 group">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold transition-all ${ps.statusColor} ring-2 ${ps.ringColor} ${ps.status === 'active' ? 'animate-pulse scale-110' : ''}`}>
                  {ps.status === 'completed' ? '\u2713' : ps.status === 'failed' ? '\u2717' : ps.status === 'blocked' ? '!' : idx + 1}
                </div>
                <div className="mt-2 text-center px-2">
                  <div className="text-sm font-medium text-gray-800">{phase.label}</div>
                  <div className={`text-xs mt-0.5 ${ps.status === 'active' ? 'text-blue-600 font-medium' : 'text-gray-500'}`}>
                    {ps.label}
                  </div>
                  {ps.duration && (
                    <div className="text-xs text-gray-400 mt-0.5">{ps.duration}</div>
                  )}
                </div>
                {/* Tooltip */}
                <div className="absolute top-full mt-14 left-1/2 -translate-x-1/2 bg-gray-800 text-white text-xs px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                  {phase.desc}
                </div>
              </div>
              {idx < PIPELINE_PHASES.length - 1 && (
                <div className={`flex-1 h-1 mt-[19px] rounded transition-colors ${ps.status === 'completed' ? 'bg-green-400' : ps.status === 'active' ? 'bg-blue-300' : 'bg-gray-200'}`} />
              )}
            </div>
          );
        })}
        {/* Final merged step */}
        <div className="flex flex-col items-center ml-2 flex-1">
          <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold transition-all ${isMerged ? 'bg-green-600 text-white ring-2 ring-green-600' : 'bg-gray-200 text-gray-400 ring-2 ring-gray-200'}`}>
            {isMerged ? '\u2713' : '5'}
          </div>
          <div className="mt-2 text-center px-2">
            <div className="text-sm font-medium text-gray-800">Merged</div>
            <div className={`text-xs mt-0.5 ${isMerged ? 'text-green-600 font-medium' : 'text-gray-500'}`}>
              {isMerged ? 'Done' : 'Pending'}
            </div>
          </div>
        </div>
      </div>

      {/* Error banner */}
      {isFailed && pipeline.error && (
        <div className="mt-6 p-4 bg-red-50 border border-red-200 rounded-lg">
          <div className="flex items-start gap-3">
            <svg className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
              <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd"/>
            </svg>
            <div>
              <p className="text-sm font-semibold text-red-800">Pipeline Failed</p>
              <p className="text-xs text-red-700 mt-1">
                <span className="font-medium">Phase:</span> {pipeline.error.phase} •{' '}
                <span className="font-medium">Agent:</span> {pipeline.error.agent}
              </p>
              <p className="text-xs text-red-700 mt-1 font-mono">{pipeline.error.message}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function InfoCard({ pipeline }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm mb-6">
      <h3 className="font-semibold text-gray-800 mb-4">Pipeline Details</h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Branch</div>
          <div className="text-sm font-mono text-gray-800 mt-1 break-all">{pipeline.branch}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Repo</div>
          <div className="text-sm font-mono text-gray-800 mt-1 break-all">{pipeline.repoPath || '\u2014'}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Created</div>
          <div className="text-sm text-gray-800 mt-1">{formatDate(pipeline.createdAt)}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Last Updated</div>
          <div className="text-sm text-gray-800 mt-1">{formatDate(pipeline.updatedAt)}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500 uppercase tracking-wide">Rework Count</div>
          <div className="text-sm text-gray-800 mt-1">{pipeline.reworkCount || 0}</div>
        </div>
        {pipeline.artifacts?.mrUrl && (
          <div>
            <div className="text-xs text-gray-500 uppercase tracking-wide">MR / PR</div>
            <a href={pipeline.artifacts.mrUrl} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-600 hover:underline mt-1 block break-all">
              {pipeline.artifacts.mrUrl}
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function LogsViewer({ issueKey, logOutput, logMeta, agent, setAgent, logRef, handleScroll, onCopy }) {
  const [searchTerm, setSearchTerm] = useState('');

  // Highlight search term in logs
  const displayOutput = useMemo(() => {
    if (!searchTerm) return logOutput;
    const regex = new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
    const matches = (logOutput.match(regex) || []).length;
    return { text: logOutput, matches };
  }, [logOutput, searchTerm]);

  const filteredLines = useMemo(() => {
    if (!searchTerm) return logOutput.split('\n');
    const term = searchTerm.toLowerCase();
    return logOutput.split('\n').filter(line => line.toLowerCase().includes(term));
  }, [logOutput, searchTerm]);

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <h3 className="font-semibold text-gray-800">Agent Logs</h3>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <input
              type="text"
              placeholder="Search logs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="border border-gray-300 rounded-md pl-8 pr-3 py-1.5 text-sm w-48 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <svg className="w-4 h-4 absolute left-2 top-2.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
            </svg>
          </div>
          <select
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="all">All Logs</option>
            <option value="orchestrator">Pipeline</option>
            <option value="feedback-parser">Feedback Parser</option>
          </select>
          <button
            onClick={onCopy}
            className="px-3 py-1.5 bg-gray-100 text-gray-700 rounded-md text-sm hover:bg-gray-200 flex items-center gap-1"
            title="Copy logs to clipboard"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/>
            </svg>
            Copy
          </button>
        </div>
      </div>

      <div ref={logRef} onScroll={handleScroll} className="log-viewer">
        {searchTerm ? filteredLines.join('\n') || '(no matches)' : logOutput}
      </div>

      <div className="flex items-center justify-between mt-3 text-xs text-gray-400">
        <span>
          {logMeta.lines} lines
          {searchTerm && ` • ${filteredLines.length} match${filteredLines.length !== 1 ? 'es' : ''}`}
        </span>
        <span>Filter: {logMeta.agent === 'all' ? 'All Logs' : logMeta.agent}</span>
      </div>
    </div>
  );
}

export default function PipelineDetail() {
  const { issueKey } = useParams();
  const [agent, setAgent] = useState('all');
  const [logOutput, setLogOutput] = useState('');
  const [logMeta, setLogMeta] = useState({ lines: 0, agent: 'all' });
  const [pipeline, setPipeline] = useState(null);
  const [error, setError] = useState(null);
  const [showDetails, setShowDetails] = useState(false);
  const logRef = useRef(null);
  const autoScrollRef = useRef(true);
  const showToast = useToast();

  const fetchData = useCallback(async () => {
    try {
      const [logsData, pipelineData] = await Promise.all([
        api.getLogs(issueKey, agent),
        api.getPipeline(issueKey),
      ]);
      if (pipelineData.error) {
        setError(pipelineData.error);
      } else {
        setPipeline(pipelineData);
        setError(null);
      }
      setLogOutput(logsData.output || '(no output yet)');
      setLogMeta({ lines: logsData.lines || 0, agent: logsData.agent });
    } catch (err) {
      setError(err.message);
    }
  }, [issueKey, agent]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  usePolling(fetchData);

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

  const handleCopyLogs = async () => {
    try {
      await navigator.clipboard.writeText(logOutput);
      showToast('Logs copied to clipboard');
    } catch (err) {
      showToast('Failed to copy logs', 'error');
    }
  };

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
        <Link to="/" className="text-blue-600 hover:text-blue-800 text-sm inline-flex items-center gap-1">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
          </svg>
          Back to Pipelines
        </Link>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-4">
          <p className="text-red-700 text-sm">{error}</p>
        </div>
      )}

      {!error && !pipeline && (
        <div className="flex items-center gap-2 text-gray-400">
          <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"/>
          </svg>
          Loading pipeline...
        </div>
      )}

      {pipeline && (
        <>
          {/* Header */}
          <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
            <div className="flex items-center gap-3 flex-wrap">
              <h2 className="text-2xl font-bold text-gray-900">{pipeline.issueKey}</h2>
              <StateBadge state={pipeline.state} />
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="px-3 py-1.5 bg-white border border-gray-300 text-gray-700 rounded-lg text-sm hover:bg-gray-50 flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d={showDetails ? "M5 15l7-7 7 7" : "M19 9l-7 7-7-7"}/>
                </svg>
                {showDetails ? 'Hide Details' : 'Show Details'}
              </button>
              <button
                onClick={handleCancel}
                className="px-3 py-1.5 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700 flex items-center gap-1"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
                Cancel
              </button>
            </div>
          </div>

          <PipelineProgress pipeline={pipeline} />

          {showDetails && <InfoCard pipeline={pipeline} />}

          <LogsViewer
            issueKey={issueKey}
            logOutput={logOutput}
            logMeta={logMeta}
            agent={agent}
            setAgent={setAgent}
            logRef={logRef}
            handleScroll={handleScroll}
            onCopy={handleCopyLogs}
          />
        </>
      )}
    </>
  );
}
