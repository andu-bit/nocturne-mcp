import React from 'react';
import { ChevronRight, Folder, FileText, AlertTriangle, Link2, Zap } from 'lucide-react';
import clsx from 'clsx';
import PriorityBadge from './PriorityBadge';
import { useLocale } from '../../../i18n/useLocale';

const NodeGridCard = ({ node, currentDomain, isInBoot, onBootToggle, onClick }) => {
  const { t } = useLocale();
  const isCrossDomain = node.domain && node.domain !== currentDomain;

  const handleBootClick = (e) => {
    e.stopPropagation();
    onBootToggle?.();
  };

  return (
  <button 
    onClick={onClick}
    className={clsx(
      "group relative flex flex-col items-start p-5 bg-[#0A0A12] border rounded-xl transition-all duration-300 hover:shadow-[0_0_20px_rgba(99,102,241,0.1)] hover:-translate-y-1 text-left w-full h-full overflow-hidden",
      isInBoot
        ? "border-amber-800/40 hover:border-amber-600/50"
        : isCrossDomain
          ? "border-violet-800/40 hover:border-violet-500/40"
          : "border-slate-800/50 hover:border-indigo-500/30"
    )}
  >
    <div className="absolute inset-0 bg-gradient-to-br from-indigo-500/5 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
    
    <div className="flex items-center gap-3 mb-3 w-full">
      <div className="p-2 rounded-lg bg-slate-900 group-hover:bg-indigo-900/20 text-slate-500 group-hover:text-indigo-400 transition-colors flex-shrink-0">
         {node.approx_children_count > 0 ? <Folder size={18} /> : <FileText size={18} />}
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="text-sm font-semibold text-slate-300 group-hover:text-indigo-200 transition-colors break-words line-clamp-2">
          {node.name || (node.path ? node.path.split('/').pop() : '')}
        </h3>
        {isCrossDomain && (
          <span className="inline-flex items-center gap-1 mt-1 px-1.5 py-0.5 text-[10px] font-mono text-violet-400/80 bg-violet-950/40 border border-violet-800/30 rounded">
            <Link2 size={9} />
            {node.domain}://
          </span>
        )}
      </div>
      
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <PriorityBadge priority={node.priority} />
        {/* Boot toggle inline */}
        <div
          onClick={handleBootClick}
          title={isInBoot ? t('memory.boot.remove') : t('memory.boot.add')}
          className={clsx(
            "p-1 rounded-md transition-all z-10",
            isInBoot
              ? "text-amber-400 bg-amber-950/50 border border-amber-700/40 shadow-[0_0_8px_rgba(245,158,11,0.15)]"
              : "text-slate-700 hover:text-amber-400/70 hover:bg-slate-800/60 opacity-0 group-hover:opacity-100 border border-transparent"
          )}
        >
          <Zap size={13} className={isInBoot ? "fill-amber-400" : ""} />
        </div>
      </div>
    </div>
    
    {node.disclosure && (
      <div className="w-full mb-2">
        <p className="text-[11px] text-amber-500/70 leading-snug line-clamp-2 flex items-start gap-1">
          <AlertTriangle size={11} className="flex-shrink-0 mt-0.5" />
          <span className="italic">{node.disclosure}</span>
        </p>
      </div>
    )}
    
    <div className="w-full flex-1">
        {node.content_snippet ? (
            <p className="text-xs text-slate-500 leading-relaxed line-clamp-3">
                {node.content_snippet}
            </p>
        ) : (
            <p className="text-xs text-slate-700 italic">{t('memory.card.no_preview')}</p>
        )}
    </div>

    <ChevronRight size={14} className="absolute bottom-4 right-4 text-indigo-500/50 opacity-0 group-hover:opacity-100 transition-opacity" />
  </button>
  );
};

export default NodeGridCard;
