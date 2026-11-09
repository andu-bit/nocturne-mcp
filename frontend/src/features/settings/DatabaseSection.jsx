import React, { useState, useEffect } from 'react';
import {
  Plus, CheckCircle, XCircle, RefreshCw, TestTube, FolderOpen
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import { testDatabase, createDatabase, openDbFolder } from '../../lib/api';
import { toast } from '../../components/Toast';

function parseSqlitePathFromUrl(url) {
  if (!url || !url.includes('sqlite')) return '';
  const m = url.match(/\/\/\/(.+)$/);
  return m ? m[1] : '';
}

export default function DatabaseSection({ settings, dbStatus, onRefreshStatus, onSave }) {
  const { t } = useTranslation();
  const currentUrl = settings?.database_url || '';
  const isSqliteCurrent = currentUrl.includes('sqlite');

  const [mode, setMode] = useState(isSqliteCurrent ? 'sqlite' : 'postgresql');
  const [sqlitePath, setSqlitePath] = useState('');
  const [pgUrl, setPgUrl] = useState('');
  const [newDbPath, setNewDbPath] = useState('');
  const [creating, setCreating] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!currentUrl) return;
    if (currentUrl.includes('sqlite')) {
      setMode('sqlite');
      setSqlitePath(parseSqlitePathFromUrl(currentUrl));
    } else {
      setMode('postgresql');
      setPgUrl(currentUrl);
    }
  }, [currentUrl]);

  const buildUrl = () => {
    if (mode === 'sqlite') {
      const p = sqlitePath.trim().replace(/\\/g, '/');
      return p ? `sqlite+aiosqlite:///${p}` : '';
    }
    return pgUrl.trim();
  };

  const inputValue = mode === 'sqlite' ? sqlitePath : pgUrl;
  const hasInput = inputValue.trim().length > 0;

  const handleTestOnly = async () => {
    const url = buildUrl();
    if (!url) return;
    setBusy(true);
    setTestResult(null);
    try {
      const result = await testDatabase(url);
      setTestResult(result);
    } catch (e) {
      setTestResult({ success: false, message: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleTestAndSave = async () => {
    const url = buildUrl();
    if (!url) return;
    setBusy(true);
    setTestResult(null);
    try {
      const result = await testDatabase(url);
      if (result.success) {
        await onSave({ database_url: url });
        setDirty(false);
        setTestResult({ success: true, message: t('settings.database.connected_saved') });
        onRefreshStatus();
      } else {
        setTestResult(result);
      }
    } catch (e) {
      setTestResult({ success: false, message: e.response?.data?.detail || e.message });
    } finally {
      setBusy(false);
    }
  };

  const handleCreate = async () => {
    const path = newDbPath.trim();
    if (!path) return;
    setCreating(true);
    setTestResult(null);
    try {
      const result = await createDatabase(path);
      setMode('sqlite');
      setSqlitePath(parseSqlitePathFromUrl(result.database_url));
      setDirty(true);
      setNewDbPath('');
      setTestResult({ success: true, message: t('settings.database.created_switch') });
    } catch (e) {
      setTestResult({ success: false, message: e.response?.data?.detail || e.message });
    } finally {
      setCreating(false);
    }
  };

  const handleOpenFolder = async () => {
    try {
      await openDbFolder();
    } catch (e) {
      toast(e.response?.data?.detail || e.message, "error");
    }
  };

  return (
    <div className="space-y-5 pt-4">
      {/* Status card */}
      {dbStatus && (
        <div className="bg-slate-900 border border-slate-700/50 shadow-sm rounded-lg p-3 text-sm space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">{t('settings.database.type_label')}</span>
            <span className="text-slate-200 font-medium">{dbStatus.type === 'sqlite' ? t('settings.database.sqlite') : t('settings.database.postgresql')}</span>
          </div>
          {dbStatus.type === 'sqlite' && dbStatus.path && (
            <>
              <div className="flex items-center justify-between gap-4">
                <span className="text-slate-400 flex-shrink-0">{t('settings.database.path_label')}</span>
                <span className="text-slate-300 font-mono text-xs truncate max-w-[380px]" title={dbStatus.path}>{dbStatus.path}</span>
              </div>
              {dbStatus.size_display && (
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">{t('settings.database.size_label')}</span>
                  <span className="text-slate-200">{dbStatus.size_display}</span>
                </div>
              )}
            </>
          )}
          {dbStatus.type === 'postgresql' && dbStatus.url_masked && (
            <div className="flex items-center justify-between">
              <span className="text-slate-400">{t('settings.database.url_label')}</span>
              <span className="text-slate-300 font-mono text-xs">{dbStatus.url_masked}</span>
            </div>
          )}
          <div className="flex items-center justify-end gap-3 pt-1">
            {dbStatus.type === 'sqlite' && dbStatus.path && (
              <button onClick={handleOpenFolder} className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 transition-colors">
                <FolderOpen size={11} /> {t('settings.database.open_folder')}
              </button>
            )}
            <button onClick={onRefreshStatus} className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1">
              <RefreshCw size={11} /> {t('settings.database.refresh')}
            </button>
          </div>
        </div>
      )}

      {/* Mode toggle */}
      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">{t('settings.database.type_selector_label')}</label>
        <div className="flex rounded-lg overflow-hidden border border-slate-700 w-fit">
          {[
            { id: 'sqlite', label: t('settings.database.sqlite') },
            { id: 'postgresql', label: t('settings.database.postgresql') },
          ].map(opt => (
            <button
              key={opt.id}
              onClick={() => { setMode(opt.id); setDirty(true); setTestResult(null); }}
              className={clsx(
                "px-4 py-1.5 text-sm font-medium transition-colors",
                mode === opt.id
                  ? "bg-indigo-600 text-white"
                  : "bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800"
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Connection input */}
      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">
          {mode === 'sqlite' ? t('settings.database.file_path_label') : t('settings.database.connection_url_label')}
        </label>
        {mode === 'sqlite' ? (
          <input
            type="text"
            value={sqlitePath}
            onChange={e => { setSqlitePath(e.target.value); setDirty(true); setTestResult(null); }}
            placeholder={t('settings.database.sqlite_placeholder')}
            className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
          />
        ) : (
          <input
            type="text"
            value={pgUrl}
            onChange={e => { setPgUrl(e.target.value); setDirty(true); setTestResult(null); }}
            placeholder={t('settings.database.pg_placeholder')}
            className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
          />
        )}

        {hasInput && (
          <button
            onClick={dirty ? handleTestAndSave : handleTestOnly}
            disabled={busy}
            className="mt-1 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 text-white rounded-lg text-sm flex items-center gap-1.5 transition-colors"
          >
            <TestTube size={14} />
            {busy ? t('settings.database.testing') : (dirty ? t('settings.database.test_save') : t('settings.database.test_connection'))}
          </button>
        )}

        {testResult && (
          <div className={`flex items-center gap-2 text-sm ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
            {testResult.success ? <CheckCircle size={14} /> : <XCircle size={14} />}
            {testResult.message}
          </div>
        )}
      </div>

      {/* Create new SQLite DB */}
      {mode === 'sqlite' && (
        <div className="space-y-2 pt-2 border-t border-slate-800/50">
          <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">{t('settings.database.create_new_label')}</label>
          <p className="text-xs text-slate-500">{t('settings.database.create_new_desc')}</p>
          <div className="flex gap-2">
            <input
              type="text"
              value={newDbPath}
              onChange={e => setNewDbPath(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              placeholder={t('settings.database.new_db_placeholder')}
              className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
            />
            <button
              onClick={handleCreate}
              disabled={creating || !newDbPath.trim()}
              className="px-3 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-200 rounded-lg text-sm flex items-center gap-1.5 transition-colors whitespace-nowrap"
            >
              <Plus size={14} />
              {creating ? t('settings.database.creating') : t('settings.database.create')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
