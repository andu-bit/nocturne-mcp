import React, { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { LayoutGrid, KeyRound, Loader2, AlertCircle } from 'lucide-react';
import { getDomains } from '../lib/api';

const TokenAuth = ({ onAuthenticated }) => {
  const { t } = useTranslation();
  const [token, setToken] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) return;

    setLoading(true);
    setError('');

    // 先保存 token 到 localStorage，让 axios 拦截器能读取到
    localStorage.setItem('api_token', trimmed);

    try {
      await getDomains();
      onAuthenticated();
    } catch (err) {
      localStorage.removeItem('api_token');
      if (err.response && err.response.status === 401) {
        setError(t('auth.invalid_token'));
      } else {
        setError(t('auth.network_error'));
      }
    } finally {
      setLoading(false);
    }
  }, [token, onAuthenticated]);

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-950">
      <div className="w-full max-w-sm mx-4">
        {/* 卡片容器 */}
        <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl shadow-black/50">
          {/* Logo 区域 */}
          <div className="flex flex-col items-center mb-8">
            <div className="w-12 h-12 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center mb-4">
              <LayoutGrid className="w-6 h-6 text-indigo-500" />
            </div>
            <h1 className="text-lg font-bold text-slate-100">{t('auth.title')}</h1>
            <p className="text-xs text-slate-500 mt-1">{t('auth.subtitle')}</p>
          </div>

          {/* 表单 */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="api-token"
                className="block text-xs font-medium text-slate-400 mb-2"
              >
                {t('auth.token_label')}
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <KeyRound className="w-4 h-4 text-slate-600" />
                </div>
                <input
                  id="api-token"
                  data-testid="auth-token-input"
                  type="password"
                  value={token}
                  onChange={(e) => {
                    setToken(e.target.value);
                    if (error) setError('');
                  }}
                  placeholder={t('auth.token_placeholder')}
                  disabled={loading}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 transition-colors disabled:opacity-50"
                />
              </div>
            </div>

            {/* 错误提示 */}
            {error && (
              <div data-testid="auth-error-msg" className="flex items-center gap-2 text-xs text-red-400 bg-red-950/30 border border-red-900/50 rounded-lg px-3 py-2">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              data-testid="auth-submit-btn"
              disabled={loading || !token.trim()}
              className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('auth.verifying')}
                </>
              ) : (
                t('auth.connect')
              )}
            </button>
          </form>
        </div>

        {/* 底部文字 */}
        <p className="text-center text-[10px] text-slate-700 mt-4 tracking-wider uppercase">
          {t('auth.footer')}
        </p>
      </div>
    </div>
  );
};

export default TokenAuth;
