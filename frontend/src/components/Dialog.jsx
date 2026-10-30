import { useEffect, useRef } from "react";

/** Minimal accessible modal: Escape closes, backdrop click closes, focus moves inside. */
export default function Dialog({ title, onClose, children, busy = false }) {
  const ref = useRef(null);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  useEffect(() => {
    ref.current?.querySelector("input, button")?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-24"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="w-full max-w-md rounded border border-base-700 bg-base-900 p-5 shadow-xl"
      >
        <h2 className="mb-3 text-sm font-semibold text-ink-100">{title}</h2>
        {children}
      </div>
    </div>
  );
}
