/* Shared by the dashboard charts. Status colours are validated against the dark
   surface; green/amber are close for protan vision, so marks also differ by shape. */
export const STATUS = {
  OK: { color: '#00e55b', label: 'OK' },
  WARN: { color: '#fbbf24', label: 'Warn' },
  ANOMALY: { color: '#f87171', label: 'Anomaly' },
  PENDING: { color: '#5b6470', label: 'Judging' },
};

export const fmtS = (ms) => (Number.isFinite(ms) ? `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s` : '—');

export function quantile(values, q) {
  if (!values.length) return NaN;
  const s = [...values].sort((a, b) => a - b);
  const i = (s.length - 1) * q;
  const lo = Math.floor(i);
  return s[lo] + (s[Math.ceil(i)] - s[lo]) * (i - lo);
}
