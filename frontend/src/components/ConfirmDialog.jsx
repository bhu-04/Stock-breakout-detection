import Dialog from "./Dialog";

export default function ConfirmDialog({ title, message, confirmLabel, onConfirm, onClose, busy = false }) {
  return (
    <Dialog title={title} onClose={onClose} busy={busy}>
      <p className="mb-4 text-xs leading-relaxed text-ink-300">{message}</p>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          disabled={busy}
          className="rounded border border-base-700 px-3 py-1.5 text-xs text-ink-300 hover:bg-base-800 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="rounded bg-accent-600 px-3 py-1.5 text-xs font-medium text-ink-100 hover:bg-accent-500 disabled:opacity-50"
        >
          {confirmLabel}
        </button>
      </div>
    </Dialog>
  );
}
