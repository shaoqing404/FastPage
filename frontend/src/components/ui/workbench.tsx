import React from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertCircle, Check, Copy, X } from 'lucide-react';

import { cn } from '../../lib/utils';

export const GlassPanel: React.FC<{
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}> = ({ title, subtitle, actions, children, className, bodyClassName }) => (
  <section className={cn('glass-panel', className)}>
    {(title || subtitle || actions) && (
      <div className="glass-panel-header">
        <div className="min-w-0">
          {title && <h3 className="panel-title">{title}</h3>}
          {subtitle && <p className="panel-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
    )}
    <div className={cn('glass-panel-body', bodyClassName)}>{children}</div>
  </section>
);

export const SectionToolbar: React.FC<{
  title: string;
  description?: string;
  actions?: React.ReactNode;
}> = ({ title, description, actions }) => (
  <div className="flex items-end justify-between gap-6">
    <div className="space-y-1">
      <h2 className="text-[28px] font-semibold tracking-[-0.03em] text-slate-900">{title}</h2>
      {description && <p className="text-sm text-slate-600">{description}</p>}
    </div>
    {actions && <div className="flex items-center gap-3">{actions}</div>}
  </div>
);

export const StatusBadge: React.FC<{
  tone?: 'default' | 'success' | 'warning' | 'danger' | 'accent';
  children: React.ReactNode;
}> = ({ tone = 'default', children }) => (
  <span className={cn('status-badge', `status-${tone}`)}>{children}</span>
);

export const EmptyState: React.FC<{
  title: string;
  description?: string;
  action?: React.ReactNode;
}> = ({ title, description, action }) => (
  <div className="empty-state">
    <p className="text-base font-medium text-slate-900">{title}</p>
    {description && <p className="max-w-md text-sm text-slate-500">{description}</p>}
    {action}
  </div>
);

export const KeyMetric: React.FC<{
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
}> = ({ label, value, hint }) => (
  <div className="metric-card">
    <p className="metric-label">{label}</p>
    <div className="space-y-1">
      <div className="metric-value">{value}</div>
      {hint && <p className="metric-hint">{hint}</p>}
    </div>
  </div>
);

export const Field: React.FC<{
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}> = ({ label, hint, required, children }) => (
  <label className="field-stack">
    <span className="field-label">
      {label}
      {required && <span className="text-blue-600">*</span>}
    </span>
    {children}
    {hint && <span className="field-hint">{hint}</span>}
  </label>
);

export const ExpertDrawer: React.FC<{
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
  side?: 'left' | 'right';
  widthClassName?: string;
}> = ({ open, title, description, onClose, children, side = 'right', widthClassName }) => (
  <AnimatePresence>
    {open && (
      <>
        <motion.button
          type="button"
          className="drawer-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        />
        <motion.aside
          className={cn('expert-drawer', side === 'left' ? 'expert-drawer-left' : 'expert-drawer-right', widthClassName)}
          initial={{ x: side === 'left' ? -32 : 32, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: side === 'left' ? -32 : 32, opacity: 0 }}
          transition={{ type: 'spring', stiffness: 280, damping: 28 }}
        >
          <div className="glass-panel-header">
            <div>
              <h3 className="panel-title">{title}</h3>
              {description && <p className="panel-subtitle">{description}</p>}
            </div>
            <button type="button" className="icon-button" onClick={onClose}>
              <X size={16} />
            </button>
          </div>
          <div className="glass-panel-body overflow-auto">{children}</div>
        </motion.aside>
      </>
    )}
  </AnimatePresence>
);

export const SurfaceModal: React.FC<{
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}> = ({ open, title, subtitle, onClose, actions, children, className, bodyClassName }) => (
  <AnimatePresence>
    {open && (
      <>
        <motion.button
          type="button"
          className="drawer-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        />
        <div className="modal-shell">
          <motion.div
            className={cn('surface-modal', className)}
            initial={{ y: 18, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 18, opacity: 0, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
          >
            <div className="glass-panel-header">
              <div>
                <h3 className="panel-title">{title}</h3>
                {subtitle && <p className="panel-subtitle">{subtitle}</p>}
              </div>
              <div className="flex items-center gap-2">
                {actions}
                <button type="button" className="icon-button" onClick={onClose}>
                  <X size={16} />
                </button>
              </div>
            </div>
            <div className={cn('glass-panel-body overflow-auto', bodyClassName)}>{children}</div>
          </motion.div>
        </div>
      </>
    )}
  </AnimatePresence>
);

export const CopyOnceModal: React.FC<{
  open: boolean;
  title: string;
  subtitle?: string;
  value: string;
  meta?: React.ReactNode;
  copied: boolean;
  copyError?: string;
  footerNote?: string;
  onCopy: () => void;
  onClose: () => void;
}> = ({ open, title, subtitle, value, meta, copied, copyError, footerNote, onCopy, onClose }) => (
  <AnimatePresence>
    {open && (
      <>
        <motion.button
          type="button"
          className="drawer-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        />
        <div className="modal-shell">
          <motion.div
            className="copy-once-modal"
            initial={{ y: 18, opacity: 0, scale: 0.98 }}
            animate={{ y: 0, opacity: 1, scale: 1 }}
            exit={{ y: 18, opacity: 0, scale: 0.98 }}
            transition={{ type: 'spring', stiffness: 320, damping: 28 }}
          >
            <div className="glass-panel-header">
              <div>
                <h3 className="panel-title">{title}</h3>
                <p className="panel-subtitle">{subtitle || 'Copy this secret before closing this window.'}</p>
              </div>
              <button type="button" className="icon-button" onClick={onClose}>
                <X size={16} />
              </button>
            </div>
            <div className="glass-panel-body space-y-4 overflow-auto">
              {meta && <div className="rounded-2xl bg-white/65 p-4 text-sm text-slate-600">{meta}</div>}
              <div className="rounded-2xl border border-white/80 bg-white/80 p-4">
                <textarea readOnly value={value} className="min-h-[120px] w-full resize-none bg-transparent text-[13px] leading-6 text-slate-900 outline-none" />
              </div>
              {copyError && <InlineAlert tone="warning" title="Clipboard copy failed">{copyError}</InlineAlert>}
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2 text-sm text-slate-500">
                  <AlertCircle size={16} />
                  <span>{copyError ? 'The key is still visible above. Manually select and copy it before closing.' : footerNote || 'Handle this secret carefully after copying.'}</span>
                </div>
                <button type="button" className="btn-primary" onClick={onCopy}>
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                  <span>{copied ? 'Copied' : 'Copy key'}</span>
                </button>
              </div>
            </div>
          </motion.div>
        </div>
      </>
    )}
  </AnimatePresence>
);

export const InlineAlert: React.FC<{
  tone?: 'danger' | 'warning' | 'success' | 'default';
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}> = ({ tone = 'danger', title, children, action }) => (
  <div className={cn('inline-alert', `inline-alert-${tone}`)}>
    <div className="space-y-1">
      {title && <p className="font-medium text-slate-900">{title}</p>}
      <div className="text-sm text-slate-700">{children}</div>
    </div>
    {action && <div className="shrink-0">{action}</div>}
  </div>
);

export const SegmentedControl: React.FC<{
  items: Array<{ value: string; label: string; count?: React.ReactNode }>;
  value: string;
  onChange: (value: string) => void;
}> = ({ items, value, onChange }) => (
  <div className="segmented">
    {items.map((item) => {
      const active = item.value === value;
      return (
        <button
          key={item.value}
          type="button"
          className={cn('segmented-item', active && 'segmented-item-active')}
          onClick={() => onChange(item.value)}
        >
          <span>{item.label}</span>
          {item.count !== undefined && <span className="text-xs text-slate-400">{item.count}</span>}
        </button>
      );
    })}
  </div>
);
