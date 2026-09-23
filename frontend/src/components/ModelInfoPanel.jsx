export default function ModelInfoPanel({ modelInfo }) {
  if (!modelInfo) return null;

  if (!modelInfo.available) {
    return (
      <div className="rounded border border-base-800 bg-base-900 p-4">
        <div className="mb-1 text-[11px] uppercase tracking-wide text-ink-500">Model Information</div>
        <div className="text-sm text-ink-300">No trained model found.</div>
        <div className="mt-1 font-mono text-[11px] text-ink-500">
          python -m backend.training.train --model xgboost
        </div>
      </div>
    );
  }

  const { metadata, metrics } = modelInfo;
  const metricEntries = [
    ["Accuracy", metrics.accuracy],
    ["Precision", metrics.precision],
    ["Recall", metrics.recall],
    ["F1", metrics.f1],
    ["ROC-AUC", metrics.roc_auc],
    ["PR-AUC", metrics.pr_auc],
  ];

  return (
    <div className="rounded border border-base-800 bg-base-900 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-[11px] uppercase tracking-wide text-ink-500">Model Information</div>
        <span className="rounded bg-up/10 px-1.5 py-0.5 text-[10px] font-medium text-up">Evaluated</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
        <span className="text-ink-500">Model</span>
        <span className="text-right font-mono text-ink-100">{metadata.model_name}</span>
        <span className="text-ink-500">Version</span>
        <span className="text-right font-mono text-ink-100">{metadata.version}</span>
        <span className="text-ink-500">Features</span>
        <span className="text-right font-mono text-ink-100">{metadata.feature_count}</span>
        <span className="text-ink-500">Train / Val / Test</span>
        <span className="text-right font-mono text-ink-100">
          {metadata.n_train} / {metadata.n_val} / {metadata.n_test}
        </span>
      </div>
      <div className="mt-3 border-t border-base-850 pt-3">
        <div className="mb-1.5 text-[11px] uppercase tracking-wide text-ink-500">Test-Set Metrics</div>
        <div className="grid grid-cols-3 gap-2">
          {metricEntries.map(([label, value]) => (
            <div key={label} className="rounded bg-base-850 px-2 py-1.5">
              <div className="text-[10px] text-ink-500">{label}</div>
              <div className="font-mono text-sm tabular text-ink-100">
                {value === null || Number.isNaN(value) ? "N/A" : value.toFixed(3)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
