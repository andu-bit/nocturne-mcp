import React from 'react';
import { diffLines } from 'diff';
import { useTranslation } from 'react-i18next';

const DiffViewer = ({ oldText, newText }) => {
  const { t } = useTranslation();
  const safeOld = oldText || '';
  const safeNew = newText || '';
  const diff = diffLines(safeOld, safeNew);
  const hasChanges = safeOld !== safeNew;

  return (
    <div className="w-full font-sans text-sm leading-7">
      {!hasChanges && (
        <div data-testid="diff-no-changes" className="text-slate-500 italic p-4 text-center border border-dashed border-slate-800 rounded-lg">
          {t('diff.no_changes')}
        </div>
      )}

      <div className="space-y-1">
        {diff.map((part, index) => {
          if (part.removed) {
            return (
              <div key={index} className="group relative bg-red-950/20 hover:bg-red-950/30 transition-colors border-l-2 border-red-900/50 pl-4 pr-2 py-1 select-text">
                <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-red-800 opacity-50 group-hover:opacity-100 transition-opacity"></div>
                <span data-testid="diff-removed" className="text-red-300/50 line-through decoration-red-800/50 font-mono text-xs block mb-1 opacity-50 select-none">{t('diff.removed')}</span>
                <span className="text-red-200/60 font-serif whitespace-pre-wrap">{part.value}</span>
              </div>
            );
          }
          
          if (part.added) {
            return (
               <div key={index} className="group relative bg-emerald-950/20 hover:bg-emerald-950/30 transition-colors border-l-2 border-emerald-500/50 pl-4 pr-2 py-2 my-1 rounded-r select-text">
                 <div className="absolute left-0 top-0 bottom-0 w-[2px] bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.3)]"></div>
                 <span data-testid="diff-added" className="text-emerald-500/50 font-mono text-xs block mb-1 opacity-70 select-none">{t('diff.added')}</span>
                 <span className="text-emerald-100 font-medium font-serif whitespace-pre-wrap">{part.value}</span>
               </div>
            );
          }

          return (
            <div key={index} className="pl-4 pr-2 py-1 text-slate-400 whitespace-pre-wrap hover:text-slate-300 transition-colors border-l-2 border-transparent">
              {part.value}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DiffViewer;
