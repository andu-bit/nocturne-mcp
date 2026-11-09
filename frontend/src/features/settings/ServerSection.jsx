import React, { useState, useEffect } from 'react';
import { Save, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from '../../components/Toast';

export default function ServerSection({ settings, configPath, lockedFields = [], onSave }) {
  const { t } = useTranslation();
  const isLocked = (field) => lockedFields.includes(field);
  const [port, setPort] = useState('');
  const [autoOpen, setAutoOpen] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings?.web_port != null) setPort(String(settings.web_port));
    if (settings?.auto_open_browser != null) setAutoOpen(settings.auto_open_browser);
  }, [settings?.web_port, settings?.auto_open_browser]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = { auto_open_browser: autoOpen };
      if (!isLocked('web_port')) {
        const parsedPort = parseInt(port, 10);
        if (isNaN(parsedPort)) {
          toast(t('settings.server.invalid_port'), "error");
          setSaving(false);
          return;
        }
        payload.web_port = parsedPort;
      }
      await onSave(payload);
      setDirty(false);
    } catch (e) {
      toast(t('settings.server.save_failed') + ': ' + (e.response?.data?.detail || e.message), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 pt-4">
      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">{t('settings.server.port_label')}</label>
        <input
          type="number"
          value={port}
          onChange={e => { setPort(e.target.value); setDirty(true); }}
          disabled={isLocked('web_port')}
          className="bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm w-32 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner disabled:opacity-50 disabled:cursor-not-allowed"
        />
        {isLocked('web_port') && (
          <p className="text-xs text-slate-500 mt-1">{t('settings.server.docker_managed')}</p>
        )}
      </div>

      <div className="flex items-center gap-3">
        <label className="relative inline-flex items-center cursor-pointer">
          <input
            type="checkbox"
            checked={autoOpen}
            onChange={e => { setAutoOpen(e.target.checked); setDirty(true); }}
            className="sr-only peer"
          />
          <div className="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-slate-400 after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-indigo-600 peer-checked:after:bg-white"></div>
        </label>
        <span className="text-sm text-slate-300">{t('settings.server.auto_open')}</span>
      </div>

      {configPath && (
        <div className="text-xs text-slate-500 pt-2 border-t border-slate-800/50">
          {t('settings.server.config_file')} <code className="text-slate-400">{configPath}</code>
        </div>
      )}

      {dirty && (
        <div className="flex items-center justify-between pt-1">
          <p className="text-xs text-amber-400 flex items-center gap-1">
            <AlertTriangle size={12} /> {t('settings.server.restart_warning')}
          </p>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium flex items-center gap-2 transition-colors"
          >
            <Save size={14} />
            {saving ? t('settings.server.saving') : t('settings.server.save')}
          </button>
        </div>
      )}
    </div>
  );
}
