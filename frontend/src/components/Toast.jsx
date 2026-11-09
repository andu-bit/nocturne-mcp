import React, { useState, useEffect, useCallback, useRef } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';

// ---------------------------------------------------------------------------
// Toast — non-blocking notification system
//
// Usage (any component, no imports needed):
//   toast("Changes saved", "success")
//   toast("Network error — retry later", "error")
//   toast("Background sync complete", "info")
//
// Pattern: CustomEvent dispatch + dedicated container component.
// Same approach as AUTH_ERROR_EVENT (api.js:23) and open-settings (App.jsx:177).
// ---------------------------------------------------------------------------

const TOAST_EVENT = 'toast-show';

export function toast(message, type = 'info') {
  window.dispatchEvent(new CustomEvent(TOAST_EVENT, {
    detail: { message, type, id: `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}` },
  }));
}

// ---------------------------------------------------------------------------
// ToastContainer — renders at top-right, listens to TOAST_EVENT.
// Mount ONCE in App.jsx Layout (persistent across route changes).
// ---------------------------------------------------------------------------

const ICON_MAP = {
  error: { Icon: AlertCircle, className: 'text-red-400' },
  success: { Icon: CheckCircle, className: 'text-emerald-400' },
  info: { Icon: Info, className: 'text-slate-400' },
};

const TOAST_STYLE = {
  error: 'bg-red-950/90 border-red-800 text-red-200',
  success: 'bg-emerald-950/90 border-emerald-800 text-emerald-200',
  info: 'bg-slate-900/90 border-slate-700 text-slate-200',
};

function ToastItem({ toast: t, onDismiss }) {
  const { Icon, className: iconClass } = ICON_MAP[t.type] ?? ICON_MAP.info;
  const styleClass = TOAST_STYLE[t.type] ?? TOAST_STYLE.info;

  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg border animate-in slide-in-from-right duration-300 ${styleClass}`}
      role="alert"
    >
      <Icon size={18} className={`${iconClass} flex-shrink-0 mt-0.5`} />
      <span className="text-sm flex-1">{t.message}</span>
      <button
        onClick={() => onDismiss(t.id)}
        className="text-slate-500 hover:text-slate-300 flex-shrink-0 p-0.5 -mr-1"
        aria-label="Dismiss"
      >
        <X size={14} />
      </button>
    </div>
  );
}

export function ToastContainer() {
  const [toasts, setToasts] = useState([]);
  const timersRef = useRef({});

  const dismiss = useCallback((id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    if (timersRef.current[id]) {
      clearTimeout(timersRef.current[id]);
      delete timersRef.current[id];
    }
  }, []);

  useEffect(() => {
    const handler = (e) => {
      const { message, type, id } = e.detail;
      const toast = { message, type, id };

      setToasts(prev => [...prev, toast]);

      if (type !== 'error') {
        timersRef.current[id] = setTimeout(() => {
          dismiss(id);
        }, 5000);
      }
    };

    window.addEventListener(TOAST_EVENT, handler);
    return () => {
      window.removeEventListener(TOAST_EVENT, handler);
      // Clean up pending timers on unmount
      Object.values(timersRef.current).forEach(clearTimeout);
    };
  }, [dismiss]);

  if (toasts.length === 0) return null;

  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map(t => (
        <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
      ))}
    </div>
  );
}
