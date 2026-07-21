import React from 'react'
import { CheckCircle, AlertCircle, X } from 'lucide-react'

interface ReviewStatusBarProps {
  successMessage: string | null
  errorMessage: string | null
  onClear: () => void
}

export const ReviewStatusBar: React.FC<ReviewStatusBarProps> = ({
  successMessage,
  errorMessage,
  onClear,
}) => {
  if (!successMessage && !errorMessage) return null

  return (
    <div className="print:hidden fixed top-16 left-1/2 -translate-x-1/2 z-50 w-full max-w-xl px-4 animate-in fade-in slide-in-from-top-4 duration-200">
      {successMessage && (
        <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-900 text-white shadow-xl border border-slate-700 text-xs font-semibold">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMessage}</span>
          </div>
          <button
            type="button"
            onClick={onClear}
            className="text-slate-400 hover:text-white ml-3 p-1 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {errorMessage && (
        <div className="flex items-center justify-between p-3.5 rounded-xl bg-red-900 text-white shadow-xl border border-red-700 text-xs font-semibold">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-red-300 shrink-0" />
            <span>{errorMessage}</span>
          </div>
          <button
            type="button"
            onClick={onClear}
            className="text-red-300 hover:text-white ml-3 p-1 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}
