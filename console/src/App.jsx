import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import PipelineList from './components/PipelineList';
import PipelineDetail from './components/PipelineDetail';
import TriggerForm from './components/TriggerForm';
import { ToastProvider } from './components/ToastContext';

export default function App() {
  return (
    <HashRouter>
      <ToastProvider>
        <div className="bg-gray-50 text-gray-900 min-h-screen flex">
          <Sidebar />
          <main className="ml-56 flex-1 min-h-screen">
            <div className="p-6">
              <Routes>
                <Route path="/" element={<PipelineList />} />
                <Route path="/trigger" element={<TriggerForm />} />
                <Route path="/pipeline/:issueKey" element={<PipelineDetail />} />
                {/* Back-compat redirect for old /logs/:issueKey URLs */}
                <Route path="/logs/:issueKey" element={<Navigate to="/pipeline/:issueKey" replace />} />
              </Routes>
            </div>
          </main>
        </div>
      </ToastProvider>
    </HashRouter>
  );
}
