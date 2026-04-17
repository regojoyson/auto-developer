import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api';
import usePolling from '../hooks/usePolling';

// Pipeline phase definitions in order
const PIPELINE_PHASES = [
  { key: 'analyzing', label: 'Analyze', icon: '1' },
  { key: 'planning', label: 'Plan', icon: '2' },
  { key: 'developing', label: 'Implement', icon: '3' },
  { key: 'awaiting-review', label: 'Review', icon: '4' },
];

const STATE_ORDER = ['analyzing', 'planning', 'developing', 'awaiting-review', 'merged'];

function PhaseStatus({ phase, currentState, phases, pipelineError }) {
  // Determine phase status from the phases history array
  const phaseRecord = phases.find(p => p.phase === phase.key);
  const currentIdx = STATE_ORDER.indexOf(currentState);
  const phaseIdx = STATE_ORDER.indexOf(phase.key);

  let status = 'pending';
  let statusColor = 'bg-gray-200 text-gray-400';
  let ringColor = 'ring-gray-200';
  let lineColor = 'bg-gray-200';
  let label = 'Pending';

  if (phaseRecord && phaseRecord.result === 'success') {
    status = 'completed';
    statusColor = 'bg-green-500 text-white';
    ringColor = 'ring-green-500';
    lineColor = 'bg-green-500';
    label = 'Completed';
  } else if (phaseRecord && phaseRecord.result === 'failed') {
    status = 'failed';
    statusColor = 'bg-red-500 text-white';
    ringColor = 'ring-red-500';
    lineColor = 'bg-red-500';
    label = 'Failed';
  } else if (phaseRecord && phaseRecord.result === 'blocked') {
    status = 'blocked';
    statusColor = 'bg-yellow-500 text-white';
    ringColor = 'ring-yellow-500';
    lineColor = 'bg-yellow-500';
    label = 'Blocked';
  } else if (currentState === phase.key) {
    status = 'active';
    statusColor = 'bg-blue-500 text-white';
    ringColor = 'ring-blue-500';
    lineColor = 'bg-blue-500';
    label = 'Running...';
  } else if (currentState === 'failed' && phaseIdx >= currentIdx) {
    status = 'skipped';
    statusColor = 'bg-gray-200 text-gray-400';
    label = 'Skipped';
  } else if (phaseIdx < currentIdx) {
    // Phase is before current state but no record — assume completed
    status = 'completed';
    statusColor = 'bg-green-500 text-white';
    ringColor = 'ring-green-500';
    lineColor = 'bg-green-500';
    label = 'Completed';
  }

  // Duration
  let duration = '';
  if (phaseRecord && phaseRecord.startedAt) {
    const start = new Date(phaseRecord.startedAt);
    const end = phaseRecord.completedAt ? new Date(phaseRecord.completedAt) : new Date();
    const secs = Math.round((end - start) / 1000);
    if (secs < 60) duration = `${secs}s`;
    else duration = `${Math.floor(secs / 60)}m ${secs % 60}s`;
  }

  return { status, statusColor, ringColor, lineColor, label, duration };
}

function PipelineProgress({ pipeline }) {
  if (!pipeline || pipeline.error === 'Pipeline not found') return null;

  const currentState = pipeline.state || 'analyzing';
  const phases = pipeline.phases || [];
  const isMerged = currentState === 'merged';
  const isFailed = currentState === 'failed';

  return (
    <div className="mb-6">
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <h3 className="font-semibold text-gray-700">Pipeline Progress</h3>
            <span className={`badge badge-${currentState.replace(/\s+/g, '-')}`}>{currentState}</span>
          </div>
          {pipeline.reworkCount > 0 && (
            <span className="text-xs text-orange-600 font-medium">
              Rework #{pipeline.reworkCount}
            </span>
          )}
        </div>

        {/* Phase steps */}
        <div className="flex items-center justify-between">
          {PIPELINE_PHASES.map((phase, idx) => {
            const ps = PhaseStatus({ phase, currentState, phases, pipelineError: pipeline.error });
            return (
              <div key={phase.key} className="flex items-center flex-1">
                {/* Step circle + label */}
                <div className="flex flex-col items-center">
                  <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold ${ps.statusColor} ring-2 ${ps.ringColor} ${ps.status === 'active' ? 'animate-pulse' : ''}`}>
                    {ps.status === 'completed' ? '\u2713' : ps.status === 'failed' ? '\u2717' : ps.status === 'blocked' ? '!' : phase.icon}
                  </div>
                  <span className="text-xs font-medium mt-1.5 text-gray-600">{phase.label}</span>
                  <span className="text-[10px] text-gray-400">{ps.label}</span>
                  {ps.duration && (
                    <span className="text-[10px] text-gray-400">{ps.duration}</span>
                  )}
                </div>
                {/* Connector line */}
                {idx < PIPELINE_PHASES.length - 1 && (
                  <div className={`flex-1 h-0.5 mx-2 mt-[-24px] ${ps.status === 'completed' ? 'bg-green-400' : ps.status === 'active' ? 'bg-blue-300' : 'bg-gray-200'}`} />
                )}
              </div>
            );
          })}
          {/* Merged / Final state */}
          <div className="flex flex-col items-center ml-2">
            <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold ${isMerged ? 'bg-green-600 text-white ring-2 ring-green-600' : 'bg-gray-200 text-gray-400 ring-2 ring-gray-200'}`}>
              {isMerged ? '\u2713' : '5'}
            </div>
            <span className="text-xs font-medium mt-1.5 text-gray-600">Merged</span>
            <span className="text-[10px] text-gray-400">{isMerged ? 'Done' : 'Pending'}</span>
          </div>
        </div>

        {/* Error message */}
        {isFailed && pipeline.error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-sm font-medium text-red-800">Pipeline Failed</p>
            <p className="text-xs text-red-600 mt-1">
              Phase: {pipeline.error.phase} | Agent: {pipeline.error.agent}
            </p>
            <p className="text-xs text-red-600 mt-0.5">{pipeline.error.message}</p>
          </div>
        )}

        {/* Branch and timing info */}
        <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-xs text-gray-400">
          <span>Branch: <span className="font-mono">{pipeline.branch}</span></span>
          <span>Started: {pipeline.createdAt ? new Date(pipeline.createdAt).toLocaleString() : '\u2014'}</span>
        </div>
      </div>
    </div>
  );
}

export default function Logs() {
  const { issueKey } = useParams();
  const [agent, setAgent] = useState('all');
  const [logOutput, setLogOutput] = useState('');
  const [logMeta, setLogMeta] = useState({ lines: 0, agent: 'all' });
  const [pipeline, setPipeline] = useState(null);
  const logRef = useRef(null);
  const autoScrollRef = useRef(true);

  const fetchData = useCallback(async () => {
    try {
      const [logsData, pipelineData] = await Promise.all([
        api.getLogs(issueKey, agent),
        api.getPipeline(issueKey),
      ]);
      setLogOutput(logsData.output || '(no output yet)');
      setLogMeta({ lines: logsData.lines || 0, agent: logsData.agent });
      setPipeline(pipelineData);
    } catch (err) {
      setLogOutput(`Error loading logs: ${err.message}`);
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

  return (
    <>
      <div className="mb-4">
        <Link to={`/pipeline/${issueKey}`} className="text-blue-600 hover:text-blue-800 text-sm">
          &larr; Back to Pipeline
        </Link>
      </div>

      <h2 className="text-2xl font-bold mb-4">{issueKey}</h2>

      {/* Pipeline progress tracker */}
      <PipelineProgress pipeline={pipeline} />

      {/* Log viewer */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-semibold text-gray-700">Agent Logs</h3>
        <div className="flex items-center gap-3">
          <label className="text-sm text-gray-600">Filter:</label>
          <select
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            className="border border-gray-300 rounded-md px-3 py-1.5 text-sm bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="all">All Logs</option>
            <option value="orchestrator">Pipeline (Analyze + Plan + Implement)</option>
            <option value="feedback-parser">Feedback Parser</option>
          </select>
        </div>
      </div>
      <div ref={logRef} onScroll={handleScroll} className="log-viewer">
        {logOutput}
      </div>
      <p className="text-xs text-gray-400 mt-2">
        {logMeta.lines} lines | Filter: {logMeta.agent === 'all' ? 'All Logs' : logMeta.agent}
      </p>
    </>
  );
}
