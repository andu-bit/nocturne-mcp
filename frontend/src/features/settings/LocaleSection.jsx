import React, { useState, useEffect } from 'react';
import { Save } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from '../../components/Toast';

export default function LocaleSection({ settings, onSave }) {
  const { t } = useTranslation();
  const [locale, setLocale] = useState('auto');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings?.locale !== undefined) {
      setLocale(settings.locale === null ? 'auto' : settings.locale);
    }
  }, [settings?.locale]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({ locale: locale === 'auto' ? null : locale });
      setDirty(false);
    } catch (e) {
      toast(t('settings.locale.save_failed') + ': ' + (e.response?.data?.detail || e.message), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4 pt-4">
      <div className="space-y-2">
        <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider">{t('settings.locale.label')}</label>
        <select
          value={locale}
          onChange={e => { setLocale(e.target.value); setDirty(true); }}
          className="bg-slate-950 border border-slate-700 text-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
        >
          <option value="auto">{t('settings.locale.auto_option')}</option>
          <option value="en">{t('settings.locale.en_option')}</option>
          <option value="zh">{t('settings.locale.zh_option')}</option>
        </select>
      </div>

      {dirty && (
        <div className="flex items-center justify-end pt-1">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium flex items-center gap-2 transition-colors"
          >
            <Save size={14} />
            {saving ? t('settings.locale.saving') : t('settings.locale.save')}
          </button>
        </div>
      )}
    </div>
  );
}
