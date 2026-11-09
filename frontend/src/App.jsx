import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { BrowserRouter, Routes, Route, NavLink, Navigate, useLocation } from 'react-router-dom';
import { ShieldCheck, Database, LayoutGrid, Sparkles, AlertCircle, Layers, Settings, Orbit } from 'lucide-react';
import clsx from 'clsx';

import ReviewPage from './features/review/ReviewPage';
import MemoryBrowser from './features/memory/MemoryBrowser';
import MaintenancePage from './features/maintenance/MaintenancePage';
import GraphPage from './features/graph/GraphPage';
import SettingsDrawer from './features/settings/SettingsDrawer';
import TokenAuth from './components/TokenAuth';
import { ToastContainer } from './components/Toast';
import { AUTH_ERROR_EVENT, getNamespaces } from './lib/api';
import { detectLocale } from './i18n/index';
const NAMESPACE_SWITCH_ROOT_REDIRECT_KEY = 'nocturne:namespace-switch-root-redirect';

const consumeTokenFromUrl = () => {
  const params = new URLSearchParams(window.location.search);
  const token = params.get('token');
  if (!token) return false;

  localStorage.setItem('api_token', token);
  params.delete('token');
  const query = params.toString();
  const nextUrl = `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`;
  window.history.replaceState({}, '', nextUrl);
  return true;
};

// ---------------------------------------------------------------------------
// NamespaceSelector — lets the user switch between agent namespaces.
//
// The selector is always visible so that users can manually enter a namespace
// even before any memories have been written (e.g. after a fresh deployment).
// Known namespaces fetched from the DB are offered as dropdown options, but
// the user can also type a custom value into the input box.
//
// Selected namespace is stored in localStorage; the axios interceptor in
// api.js attaches it as X-Namespace on every request.
// ---------------------------------------------------------------------------
function NamespaceSelector() {
  const [knownNamespaces, setKnownNamespaces] = useState([]);
  const [selected, setSelected] = useState(
    () => localStorage.getItem('selected_namespace') ?? ''
  );
  const [inputValue, setInputValue] = useState(
    () => localStorage.getItem('selected_namespace') ?? ''
  );
  const [showInput, setShowInput] = useState(false);

  useEffect(() => {
    getNamespaces()
      .then(nsList => setKnownNamespaces(nsList.filter(ns => ns !== '')))
      .catch(() => setKnownNamespaces([]));
  }, []);

  const applyNamespace = (ns) => {
    const trimmed = ns.trim();
    const changed = trimmed !== selected;
    setSelected(trimmed);
    setInputValue(trimmed);
    if (trimmed) {
      localStorage.setItem('selected_namespace', trimmed);
    } else {
      localStorage.removeItem('selected_namespace');
    }
    if (changed) {
      sessionStorage.setItem(
        NAMESPACE_SWITCH_ROOT_REDIRECT_KEY,
        JSON.stringify({ from: selected, to: trimmed, at: Date.now() })
      );
    }
    window.location.reload();
  };

  const handleSelectChange = (e) => {
    const val = e.target.value;
    if (val === '__custom__') {
      setShowInput(true);
      return;
    }
    applyNamespace(val);
  };

  const handleInputKeyDown = (e) => {
    if (e.key === 'Enter') applyNamespace(inputValue);
    if (e.key === 'Escape') setShowInput(false);
  };

  const activeLabel = selected || '(default)';

  return (
    <div className="flex items-center gap-2 text-sm">
      <Layers size={14} className="text-slate-400 flex-shrink-0" />
      {showInput ? (
        <input
          autoFocus
          type="text"
          value={inputValue}
          onChange={e => setInputValue(e.target.value)}
          onKeyDown={handleInputKeyDown}
          onBlur={() => setShowInput(false)}
          placeholder="namespace (Enter to apply)"
          className="bg-slate-800 border border-indigo-500 text-slate-200 rounded px-2 py-1 text-xs w-40 focus:outline-none"
        />
      ) : (
        <select
          value={selected}
          onChange={handleSelectChange}
          className="bg-slate-800 border border-slate-700 text-slate-200 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500"
          title={`Current namespace: ${activeLabel}`}
        >
          <option value="">(default)</option>
          {knownNamespaces.map(ns => (
            <option key={ns} value={ns}>{ns}</option>
          ))}
          {selected && !knownNamespaces.includes(selected) && (
            <option key={selected} value={selected}>{selected}</option>
          )}
          <option value="__custom__">+ enter custom…</option>
        </select>
      )}
    </div>
  );
}

function Layout() {
  const { t } = useTranslation();
  const location = useLocation();
  const isReviewPage = location.pathname.startsWith('/review');
  const isMaintenancePage = location.pathname.startsWith('/maintenance');

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      {/* Top Navigation Bar */}
      <div className="h-12 border-b border-slate-800 bg-slate-900 flex items-center px-4 gap-6 flex-shrink-0 z-10">
        <div className="font-bold text-slate-100 flex items-center gap-2 mr-4">
          <LayoutGrid className="w-5 h-5 text-indigo-500" />
          <span data-testid="app-brand">{t('app.nav.brand')}</span>
        </div>

        <nav className="flex items-center gap-1 h-full">
          <NavLink
            to="/review"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-indigo-500 text-indigo-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <ShieldCheck size={16} />
            {t('app.nav.review')}
          </NavLink>

          <NavLink
            to="/memory"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-emerald-500 text-emerald-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <Database size={16} />
            {t('app.nav.memory')}
          </NavLink>

          <NavLink
            to="/maintenance"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-amber-500 text-amber-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <Sparkles size={16} />
            {t('app.nav.maintenance')}
          </NavLink>

          <NavLink
            to="/graph"
            className={({ isActive }) => clsx(
              "h-full flex items-center gap-2 px-4 text-sm font-medium border-b-2 transition-colors",
              isActive ? "border-violet-500 text-violet-400 bg-slate-800/50" : "border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-800/30"
            )}
          >
            <Orbit size={16} />
            Graph 3D
          </NavLink>
        </nav>

        <div className="ml-auto flex items-center gap-4">
          {!isReviewPage && !isMaintenancePage && <NamespaceSelector />}
          <button
            onClick={() => window.dispatchEvent(new CustomEvent('open-settings'))}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
          >
            <Settings size={16} />
            {t('app.nav.settings')}
          </button>
        </div>
      </div>

      {/* Main Area */}
      <div className="flex-1 min-h-0 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/review" replace />} />

          <Route path="/review" element={<ReviewPage />} />

          <Route path="/memory" element={<MemoryBrowser />} />

          <Route path="/maintenance" element={<MaintenancePage />} />

          <Route path="/graph" element={<GraphPage />} />
        </Routes>
      </div>

      <SettingsDrawer />
      <ToastContainer />
    </div>
  );
}

function App() {
  const { t } = useTranslation();
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return consumeTokenFromUrl() || !!localStorage.getItem('api_token');
  });
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);
  const [backendError, setBackendError] = useState(false);

  const handleAuthError = useCallback(() => {
    setIsAuthenticated(false);
  }, []);

  const handleAuthenticated = useCallback(() => {
    setIsAuthenticated(true);
    setBackendError(false);
  }, []);

  // 组件挂载时，尝试发送一个无 token 的请求探测后端是否连通及鉴权状态
  useEffect(() => {
    let mounted = true;

    const checkAuthStatus = async () => {
      try {
        const { getDomains } = await import('./lib/api');
        await getDomains();
        if (mounted) {
          setIsAuthenticated(true);
          setBackendError(false);
          setIsCheckingAuth(false);
        }
      } catch (error) {
        if (mounted) {
          if (!error.response) {
            // 没有响应，说明是网络错误（后端未启动）
            setBackendError(true);
          } else if (error.response.status === 401) {
            setIsAuthenticated(false);
            setBackendError(false);
          } else {
            setBackendError(false);
          }
          setIsCheckingAuth(false);
        }
      }
    };

    checkAuthStatus();

    return () => {
      mounted = false;
    };
  }, []);

  // 监听 401 事件，切换回认证界面
  useEffect(() => {
    window.addEventListener(AUTH_ERROR_EVENT, handleAuthError);
    return () => {
      window.removeEventListener(AUTH_ERROR_EVENT, handleAuthError);
    };
  }, [handleAuthError]);

  useEffect(() => {
    if (!isCheckingAuth && isAuthenticated) {
      detectLocale();
    }
  }, [isCheckingAuth, isAuthenticated]);

  if (isCheckingAuth) {
    return (
      <div data-testid="app-loading" className="flex flex-col items-center justify-center h-screen bg-slate-950 text-slate-400">
        <div className="w-8 h-8 rounded-full border-2 border-indigo-500/30 border-t-indigo-500 animate-spin mb-4"></div>
        <div className="text-sm">{t('app.loading.connecting')}</div>
      </div>
    );
  }

  if (backendError) {
    return (
      <div data-testid="error-connection-refused" className="flex flex-col items-center justify-center h-screen bg-slate-950 text-slate-400">
        <div className="w-12 h-12 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center mb-4">
          <AlertCircle className="w-6 h-6 text-red-500" />
        </div>
        <div className="text-lg font-bold text-slate-100 mb-1">{t('app.error.connection_refused')}</div>
        <div className="text-sm text-slate-500 max-w-md text-center mt-2 space-y-2">
          <p>{t('app.error.troubleshooting')}</p>
          <ul className="list-disc text-left pl-6 space-y-1">
            <li>{t('app.error.check_backend')}</li>
            <li><strong>{t('app.error.check_port_title')}</strong>{t('app.error.check_port_detail')}</li>
            <li>{t('app.error.check_docker')}</li>
          </ul>
        </div>
        <button
          data-testid="retry-btn"
          onClick={() => window.location.reload()}
          className="mt-6 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-sm transition-colors"
        >
          {t('app.error.retry')}
        </button>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <TokenAuth onAuthenticated={handleAuthenticated} />;
  }

  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}

export default App;
