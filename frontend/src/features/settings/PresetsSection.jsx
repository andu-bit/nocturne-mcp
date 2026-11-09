import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Plus, Trash2, GripVertical, Save, Copy, Check, Edit2, X, Layers
} from 'lucide-react';
import clsx from 'clsx';
import { useTranslation } from 'react-i18next';
import {
  listPresets, createPreset, updatePreset, deletePreset,
  activatePreset, duplicatePreset
} from '../../lib/api';
import { toast } from '../../components/Toast';
import ConfirmModal from '../../components/ConfirmModal';


function PresetEditor({ preset, onSaved, onCancel }) {
  const { t } = useTranslation();
  const [bootUris, setBootUris] = useState(preset.boot_uris || { '': [] });
  const [name, setName] = useState(preset.name || '');
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [newUri, setNewUri] = useState({});
  const [newNamespace, setNewNamespace] = useState('');
  const dragItem = useRef(null);
  const dragOver = useRef(null);

  const namespaces = Object.keys(bootUris).sort((a, b) => {
    if (a === '') return -1;
    if (b === '') return 1;
    return a.localeCompare(b);
  });

  const handleAddNamespace = () => {
    const ns = newNamespace.trim();
    if (!ns || namespaces.includes(ns)) return;
    setBootUris(prev => ({ ...prev, [ns]: [] }));
    setNewNamespace('');
    setDirty(true);
  };

  const handleRemoveNamespace = (ns) => {
    if (ns === '') return;
    setBootUris(prev => {
      const next = { ...prev };
      delete next[ns];
      return next;
    });
    setDirty(true);
  };

  const handleAddUri = (ns) => {
    const uri = (newUri[ns] || '').trim();
    if (!uri || (bootUris[ns] || []).includes(uri)) return;
    setBootUris(prev => ({ ...prev, [ns]: [...(prev[ns] || []), uri] }));
    setNewUri(prev => ({ ...prev, [ns]: '' }));
    setDirty(true);
  };

  const handleRemoveUri = (ns, idx) => {
    setBootUris(prev => ({
      ...prev,
      [ns]: prev[ns].filter((_, i) => i !== idx),
    }));
    setDirty(true);
  };

  const handleDragStart = (ns, idx) => { dragItem.current = { ns, idx }; };
  const handleDragEnter = (ns, idx) => { dragOver.current = { ns, idx }; };
  const handleDragEnd = (ns) => {
    if (!dragItem.current || !dragOver.current) return;
    if (dragItem.current.ns !== ns || dragOver.current.ns !== ns) {
      dragItem.current = null;
      dragOver.current = null;
      return;
    }
    if (dragItem.current.idx === dragOver.current.idx) {
      dragItem.current = null;
      dragOver.current = null;
      return;
    }
    const items = [...(bootUris[ns] || [])];
    const [removed] = items.splice(dragItem.current.idx, 1);
    items.splice(dragOver.current.idx, 0, removed);
    setBootUris(prev => ({ ...prev, [ns]: items }));
    setDirty(true);
    dragItem.current = null;
    dragOver.current = null;
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      if (preset.id) {
        await updatePreset(preset.id, { name, boot_uris: bootUris });
      } else {
        await createPreset({ name, boot_uris: bootUris });
      }
      setDirty(false);
      onSaved?.();
    } catch (e) {
      toast(t('settings.presets.save_failed') + ': ' + (e.response?.data?.detail || e.message), 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* 友好引导 Tips */}
      <p className="text-xs text-slate-400 bg-slate-950/40 border border-slate-800 rounded-lg p-2.5 leading-relaxed">
        {t('settings.presets.editor_tip')}
      </p>

      <div>
        <label className="text-xs text-slate-500 mb-1 block">{t('settings.presets.name_label')}</label>
        <input
          type="text"
          value={name}
          onChange={e => { setName(e.target.value); setDirty(true); }}
          placeholder={t('settings.presets.name_placeholder')}
          className="w-full bg-slate-950 border border-slate-700 text-slate-200 rounded-md px-2.5 py-1.5 text-sm placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      {namespaces.map(ns => (
        <div key={ns} className="bg-slate-900/60 border border-slate-800 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-xs text-slate-400 font-medium">
              {ns === '' ? t('settings.presets.default_namespace') : t('settings.presets.namespace_title', { namespace: ns })}
            </div>
            {ns !== '' && (
              <button
                onClick={() => handleRemoveNamespace(ns)}
                className="text-red-400 hover:text-red-300 transition-colors"
                title={t('settings.presets.remove_namespace')}
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
          <div className="space-y-1">
            {(bootUris[ns] || []).map((uri, idx) => (
              <div
                key={`${uri}-${idx}`}
                draggable
                onDragStart={() => handleDragStart(ns, idx)}
                onDragEnter={() => handleDragEnter(ns, idx)}
                onDragEnd={() => handleDragEnd(ns)}
                onDragOver={e => e.preventDefault()}
                className="flex items-center gap-2 bg-slate-950/60 border border-slate-800 hover:border-slate-700 rounded-md px-2.5 py-1.5 group cursor-grab active:cursor-grabbing transition-all"
              >
                <GripVertical size={12} className="text-slate-600 group-hover:text-slate-400 flex-shrink-0" />
                <span className="text-xs font-mono text-slate-300 flex-1 truncate">{uri}</span>
                <button
                  onClick={() => handleRemoveUri(ns, idx)}
                  className="opacity-0 group-hover:opacity-100 text-red-400 hover:text-red-300 transition-opacity"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
          <div className="flex gap-1.5">
            <input
              type="text"
              value={newUri[ns] || ''}
              onChange={e => setNewUri(prev => ({ ...prev, [ns]: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleAddUri(ns)}
              placeholder={t('settings.presets.uri_placeholder')}
              className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 rounded-md px-2.5 py-1.5 text-xs font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
            />
            <button
              onClick={() => handleAddUri(ns)}
              disabled={!(newUri[ns] || '').trim()}
              className="px-2.5 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-200 rounded-md text-xs flex items-center gap-1 transition-colors"
            >
              <Plus size={12} />
            </button>
          </div>
        </div>
      ))}
      
      <div className="flex gap-1.5">
        <input
          type="text"
          value={newNamespace}
          onChange={e => setNewNamespace(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAddNamespace()}
          placeholder={t('settings.presets.new_namespace_placeholder')}
          className="flex-1 bg-slate-950 border border-slate-700 text-slate-200 rounded-md px-2.5 py-1.5 text-xs font-mono placeholder:text-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 shadow-inner"
        />
        <button
          onClick={handleAddNamespace}
          disabled={!newNamespace.trim() || namespaces.includes(newNamespace.trim())}
          className="px-2.5 py-1.5 bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-200 rounded-md text-xs flex items-center gap-1 transition-colors"
        >
          <Plus size={12} /> {t('settings.presets.add_namespace')}
        </button>
      </div>

      <div className="flex justify-between pt-2">
        {onCancel && (
          <button onClick={onCancel} className="text-xs text-slate-400 hover:text-slate-200 transition-colors">
            {t('settings.presets.cancel')}
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={saving || !name.trim() || !dirty}
          className="ml-auto px-4 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-md text-xs font-medium flex items-center gap-1.5 transition-colors"
        >
          <Save size={12} />
          {saving ? t('settings.presets.saving') : t('settings.presets.save')}
        </button>
      </div>
    </div>
  );
}


function PresetCard({ preset, onActivate, onDelete, onDuplicate, onEdit }) {
  const { t } = useTranslation();
  const [confirmState, setConfirmState] = useState(null);

  const uriCount = Object.values(preset.boot_uris || {}).reduce(
    (sum, uris) => sum + uris.length, 0
  );

  const handleDelete = () => {
    setConfirmState({
      title: t('settings.presets.delete_title'),
      message: t('settings.presets.delete_message', { name: preset.name }),
      variant: 'danger',
      confirmLabel: t('settings.presets.delete'),
      onConfirm: () => { setConfirmState(null); onDelete(preset.id); },
      onCancel: () => setConfirmState(null),
    });
  };

  return (
    <div className={clsx(
      'bg-slate-900/60 border rounded-lg p-3 transition-all',
      preset.is_active
        ? 'border-indigo-500/50 ring-1 ring-indigo-500/20'
        : 'border-slate-800 hover:border-slate-700'
    )}>
      <div className="flex items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-200 truncate">
              {preset.name}
            </span>
            {preset.is_active && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 flex items-center gap-1">
                <Check size={8} /> {t('settings.presets.active')}
              </span>
            )}
          </div>
          <div className="text-xs text-slate-500 mt-0.5">
            {uriCount} URI{uriCount !== 1 ? 's' : ''}
          </div>
        </div>

        <div className="flex items-center gap-1">
          {!preset.is_active && (
            <button
              onClick={() => onActivate(preset.id)}
              className="px-2.5 py-1 bg-indigo-600/80 hover:bg-indigo-500 text-white rounded text-[11px] font-medium transition-colors"
            >
              {t('settings.presets.activate')}
            </button>
          )}
          <button
            onClick={() => onEdit(preset)}
            className="p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
            title={t('settings.presets.edit')}
          >
            <Edit2 size={13} />
          </button>
          <button
            onClick={() => onDuplicate(preset.id)}
            className="p-1.5 text-slate-500 hover:text-slate-300 transition-colors"
            title={t('settings.presets.duplicate')}
          >
            <Copy size={13} />
          </button>
          {!preset.is_active && (
            <button
              onClick={handleDelete}
              className="p-1.5 text-slate-500 hover:text-red-400 transition-colors"
              title={t('settings.presets.delete')}
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
      </div>
      {confirmState && <ConfirmModal {...confirmState} />}
    </div>
  );
}


export default function PresetsSection() {
  const { t, i18n } = useTranslation();
  const [presets, setPresets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null | preset object | { new: true }
  const [duplicateCounter, setDuplicateCounter] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPresets();
      setPresets(data);
    } catch (e) {
      console.error('Failed to load presets:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleActivate = async (id) => {
    try {
      await activatePreset(id);
      await load();
    } catch (e) {
      toast(t('settings.presets.activate_failed') + ': ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const handleDelete = async (id) => {
    try {
      await deletePreset(id);
      await load();
    } catch (e) {
      toast(t('settings.presets.delete_failed') + ': ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const handleDuplicate = async (id) => {
    const source = presets.find(p => p.id === id);
    const isZh = i18n.language?.startsWith('zh');
    const suffix = isZh ? '_副本' : '_copy';
    const fallbackBase = isZh ? '新方案' : 'copy';
    const baseName = source ? `${source.name}${suffix}` : fallbackBase;
    const newName = duplicateCounter > 0 ? `${baseName}_${duplicateCounter}` : baseName;
    setDuplicateCounter(c => c + 1);
    try {
      await duplicatePreset(id, newName);
      await load();
    } catch (e) {
      toast(t('settings.presets.duplicate_failed') + ': ' + (e.response?.data?.detail || e.message), 'error');
    }
  };

  const handleEdit = (preset) => {
    setEditing(preset);
  };

  const handleNew = () => {
    setEditing({ name: '', boot_uris: { '': [] }, id: null });
  };

  if (loading) {
    return <div className="pt-4 text-sm text-slate-500">{t('settings.presets.loading')}</div>;
  }

  if (editing) {
    return (
      <div className="space-y-3 pt-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-300">
            {editing.id ? t('settings.presets.edit_title') : t('settings.presets.create_title')}
          </h3>
          <button
            onClick={() => setEditing(null)}
            className="p-1 text-slate-400 hover:text-slate-200 transition-colors"
          >
            <X size={16} />
          </button>
        </div>
        <PresetEditor
          preset={editing}
          onSaved={() => { setEditing(null); load(); }}
          onCancel={() => setEditing(null)}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3 pt-4">
      <p className="text-xs text-slate-500">{t('settings.presets.description')}</p>

      <div className="space-y-2">
        {presets.map(preset => (
          <PresetCard
            key={preset.id}
            preset={preset}
            onActivate={handleActivate}
            onDelete={handleDelete}
            onDuplicate={handleDuplicate}
            onEdit={handleEdit}
          />
        ))}
      </div>

      <button
        onClick={handleNew}
        className="w-full py-2 border border-dashed border-slate-700 hover:border-slate-500 rounded-lg text-xs text-slate-500 hover:text-slate-300 flex items-center justify-center gap-1.5 transition-colors"
      >
        <Plus size={12} /> {t('settings.presets.add_new')}
      </button>
    </div>
  );
}
