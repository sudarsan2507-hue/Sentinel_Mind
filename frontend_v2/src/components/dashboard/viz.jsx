import { useEffect, useMemo, useState } from 'react';

/* Real pixel width of a container, so charts draw at true size instead of
   scaling a fixed viewBox (which shrank axis text to unreadable). */
function useWidth() {
  // A callback ref, not useRef: the element changes when a chart swaps its
  // empty state for the real one, and a ref observed once would keep
  // measuring the detached placeholder.
  const [node, setNode] = useState(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!node) return undefined;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)));
    ro.observe(node);
    return () => ro.disconnect();
  }, [node]);
  return [setNode, w];
}
import { STATUS, fmtS, quantile } from './status';

/* Dashboard visualisations, plain SVG/HTML -- no chart library.

   Colour here is STATUS, never decoration: green OK, amber WARN, red ANOMALY.
   Green and amber are close for protan colour vision (validator: dE 5.3), so
   every status also has its own shape -- circle, triangle, diamond -- and a text
   label in tooltips and legends. Colour is never the only carrier. */

export function StatusMark({ status, size = 12, className = '' }) {
  const c = STATUS[status]?.color ?? STATUS.PENDING.color;
  const h = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={className} aria-hidden="true">
      {status === 'WARN' && <path d={`M${h} 1 L${size - 1} ${size - 1.5} L1 ${size - 1.5} Z`} fill={c} />}
      {status === 'ANOMALY' && <path d={`M${h} 0.5 L${size - 0.5} ${h} L${h} ${size - 0.5} L0.5 ${h} Z`} fill={c} />}
      {status === 'BLOCKED' && <rect x="1" y="1" width={size - 2} height={size - 2} rx="1.5" fill={c} />}
      {status === 'OK' && <circle cx={h} cy={h} r={h - 1} fill={c} />}
      {(status === 'PENDING' || !STATUS[status]) && <circle cx={h} cy={h} r={h - 1.5} fill="none" stroke={c} strokeWidth="1.5" />}
    </svg>
  );
}

export function StatusLegend({ statuses = ['OK', 'WARN', 'ANOMALY'] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-on-surface-variant">
      {statuses.map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <StatusMark status={s} size={11} />
          {STATUS[s].label}
        </span>
      ))}
    </div>
  );
}

/* Hover readout shared by the charts: one line of who/what, one of why. */
function Tip({ tip }) {
  if (!tip) return null;
  return (
    <div
      role="tooltip"
      className="pointer-events-none absolute z-20 w-[min(300px,80vw)] rounded-md border border-outline-variant/60 bg-[#0d0e0e] px-3 py-2 shadow-xl"
      style={{ left: tip.x, top: tip.y, transform: `translate(${tip.flip ? '-100%' : '0'}, -100%) translateY(-10px)` }}
    >
      <div className="flex items-center gap-2 text-[13px] text-on-background">
        <StatusMark status={tip.status} size={10} />
        <span className="font-semibold">{STATUS[tip.status]?.label}</span>
        <span className="text-on-surface-variant">step {tip.step}</span>
        {tip.extra && <span className="ml-auto tabular-nums text-on-surface-variant">{tip.extra}</span>}
      </div>
      <div className="mt-0.5 font-label-sm text-[12px] text-primary-container break-all">{tip.tool}</div>
      {tip.text && <p className="mt-1 text-[13px] leading-snug text-on-surface-variant line-clamp-3">{tip.text}</p>}
    </div>
  );
}

function tipAt(e, host, data) {
  const r = host.getBoundingClientRect();
  const x = e.clientX - r.left;
  return { ...data, x, y: e.clientY - r.top, flip: x > r.width * 0.6 };
}

/* ─── KPI tiles ─────────────────────────────────────────────────────── */

export function MixBar({ counts }) {
  const total = counts.OK + counts.WARN + counts.ANOMALY;
  if (!total) return <div className="h-2 rounded-full bg-outline-variant/30" />;
  return (
    <div className="flex h-2 gap-[2px]" role="img" aria-label={`${counts.OK} OK, ${counts.WARN} warn, ${counts.ANOMALY} anomaly`}>
      {['OK', 'WARN', 'ANOMALY', 'BLOCKED'].filter((s) => counts[s]).map((s) => (
        <div
          key={s}
          className="h-full rounded-full transition-[flex-grow] duration-500 ease-out"
          style={{ flexGrow: counts[s], background: STATUS[s].color }}
        />
      ))}
    </div>
  );
}

export function Sparkline({ values, height = 28 }) {
  if (values.length < 2) return <div style={{ height }} />;
  const w = 120;
  const max = Math.max(...values) || 1;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * w, height - 2 - (v / max) * (height - 4)]);
  const d = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const [lx, ly] = pts[pts.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="w-full" style={{ height }} aria-hidden="true">
      <path d={`${d} L${w} ${height} L0 ${height} Z`} fill="#00e55b" opacity="0.08" />
      <path d={d} fill="none" stroke="#00e55b" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="2.5" fill="#00e55b" />
    </svg>
  );
}

export function Tile({ label, value, sub, children, tone }) {
  return (
    <div className="kpi-tile relative overflow-hidden rounded-xl border border-outline-variant/40 bg-surface-container-low p-4 md:p-5 flex flex-col gap-2">
      <span className="text-[13px] text-on-surface-variant">{label}</span>
      <span className={`font-headline-lg text-[30px] leading-none font-bold tabular-nums ${tone || 'text-on-background'}`}>{value}</span>
      {sub && <span className="text-[13px] text-on-surface-variant">{sub}</span>}
      {children && <div className="mt-auto pt-1">{children}</div>}
    </div>
  );
}

/* ─── Run timeline ─────────────────────────────────────────────────────
   Replaces the vertical node chain, which spent a screen of height to show
   twelve boxes and hid the one pattern that matters: which tool the agent
   keeps going back to. One lane per tool, one column per step; the thread
   follows the run in order. A loop is a row lighting up again and again. */

const MIN_COL = 30;
const ROW = 34;
const LABEL_WIDE = 176;
const LABEL_NARROW = 112;

export function RunTimeline({ steps, selected, onSelect }) {
  const [tip, setTip] = useState(null);
  const [box, avail] = useWidth();
  const lanes = useMemo(() => {
    const order = [];
    steps.forEach((s) => { if (!order.includes(s.tool)) order.push(s.tool); });
    return order;
  }, [steps]);

  if (!steps.length) {
    return <p ref={box} className="flex min-h-[320px] items-center justify-center px-5 text-center text-[15px] text-on-surface-variant">Steps appear here as the agent runs, one column each.</p>;
  }

  // Phones get a narrower name column so the steps, not the labels, get the room.
  const LABEL = avail && avail < 520 ? LABEL_NARROW : LABEL_WIDE;
  const maxChars = LABEL === LABEL_NARROW ? 13 : 22;
  const COL = Math.max(MIN_COL, Math.min(56, Math.floor(((avail || 0) - LABEL - 16) / steps.length)));
  const width = LABEL + steps.length * COL + 16;
  const height = lanes.length * ROW + 26;
  const pos = (s, i) => [LABEL + i * COL + COL / 2, 26 + lanes.indexOf(s.tool) * ROW + ROW / 2];
  const thread = steps.map((s, i) => pos(s, i));
  const path = thread.map(([x, y], i) => {
    if (!i) return `M${x} ${y}`;
    const [px, py] = thread[i - 1];
    const mx = (px + x) / 2;
    return `C${mx} ${py} ${mx} ${y} ${x} ${y}`;
  }).join(' ');

  return (
    <div ref={box} className="relative" onMouseLeave={() => setTip(null)}>
      <div className="overflow-x-auto overscroll-x-contain">
        <svg width={width} height={height} className="block" role="img" aria-label={`Run timeline, ${steps.length} steps across ${lanes.length} tools`}>
          {/* lanes */}
          {lanes.map((tool, r) => (
            <g key={tool}>
              <rect x={LABEL - 8} y={26 + r * ROW + 3} width={width - LABEL} height={ROW - 6} rx="6" fill={r % 2 ? 'transparent' : '#ffffff05'} />
              <text x={LABEL - 16} y={26 + r * ROW + ROW / 2 + 4} textAnchor="end" className="fill-on-surface-variant" style={{ font: '500 12px "JetBrains Mono", monospace' }}>
                {tool.length > maxChars ? `${tool.slice(0, maxChars - 1)}…` : tool}
                <title>{tool}</title>
              </text>
            </g>
          ))}
          {/* step numbers */}
          {steps.map((s, i) => ((i + 1) % 5 === 0 || i === 0) && (
            <text key={`n${s.id}`} x={LABEL + i * COL + COL / 2} y="14" textAnchor="middle" className="fill-on-surface-variant" style={{ font: '12px Inter, sans-serif' }}>{i + 1}</text>
          ))}
          {/* the thread */}
          <path d={path} fill="none" stroke="#3b4b3a" strokeWidth="2" strokeLinecap="round" />
          {/* steps */}
          {steps.map((s, i) => {
            const [x, y] = thread[i];
            const sel = selected === s.id;
            return (
              <g
                key={s.id}
                className="timeline-step cursor-pointer"
                style={{ transformOrigin: `${x}px ${y}px` }}
                onClick={() => onSelect(sel ? null : s.id)}
                onMouseMove={(e) => setTip(tipAt(e, e.currentTarget.closest('.relative'), { status: s.status, step: i + 1, tool: s.tool, text: s.text, extra: s.latency ? fmtS(s.latency) : '' }))}
              >
                <rect x={x - COL / 2} y={y - ROW / 2} width={COL} height={ROW} fill="transparent" />
                {sel && <circle cx={x} cy={y} r="13" fill="none" stroke="#e3e2e2" strokeWidth="1.5" />}
                {s.status === 'PENDING' ? (
                  <circle cx={x} cy={y} r="6" fill="#1b1c1c" stroke={STATUS.PENDING.color} strokeWidth="2" className="animate-pulse" />
                ) : (
                  <g transform={`translate(${x - 8} ${y - 8})`}>
                    <rect x="-2" y="-2" width="20" height="20" rx="10" fill="#1b1c1c" />
                    <StatusMarkSvg status={s.status} />
                  </g>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <Tip tip={tip} />
    </div>
  );
}

/* StatusMark as an in-SVG group (16px), with the 2px surface ring the marks sit on. */
function StatusMarkSvg({ status }) {
  const c = STATUS[status].color;
  if (status === 'WARN') return <path d="M8 1.5 L15 14 L1 14 Z" fill={c} />;
  if (status === 'ANOMALY') return <path d="M8 0.5 L15.5 8 L8 15.5 L0.5 8 Z" fill={c} />;
  if (status === 'BLOCKED') return <rect x="1.5" y="1.5" width="13" height="13" rx="2" fill={c} />;
  return <circle cx="8" cy="8" r="6.5" fill={c} />;
}

/* ─── Verdict latency per step ─────────────────────────────────────────
   One measure, one axis: seconds from trace to verdict. Bar colour is the
   verdict, so a slow stretch of anomalies reads at a glance. */

export function LatencyChart({ steps, selected, onSelect }) {
  const [tip, setTip] = useState(null);
  const [box, avail] = useWidth();
  const judged = steps.map((s, i) => ({ ...s, n: i + 1 })).filter((s) => Number.isFinite(s.latency) && s.status !== 'BLOCKED');
  if (!judged.length) return <p ref={box} className="flex h-[200px] items-center justify-center text-[15px] text-on-surface-variant">No verdicts yet.</p>;

  const W = Math.max(280, avail || 560); const H = 200; const L = 44; const B = 24; const T = 22;
  const max = Math.max(...judged.map((s) => s.latency)) * 1.15 || 1;
  // A round step that gives at most five gridlines, whatever the range --
  // slow rate-limited verdicts (20 s+) used to stack a dozen labels.
  const step = [250, 500, 1000, 2000, 5000, 10000, 20000, 30000, 60000].find((v) => max / v <= 5) || 120000;
  const ticks = [];
  for (let v = 0; v <= max; v += step) ticks.push(v);
  const bw = Math.min(40, (W - L) / judged.length);
  const y = (v) => T + (H - T - B) * (1 - v / max);
  const med = quantile(judged.map((s) => s.latency), 0.5);

  return (
    <div ref={box} className="relative" onMouseLeave={() => setTip(null)}>
      <svg width={W} height={H} className="block" role="img" aria-label={`Verdict latency per step, median ${fmtS(med)}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W} y1={y(v)} y2={y(v)} stroke="#ffffff10" />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" className="fill-on-surface-variant" style={{ font: '12px Inter, sans-serif' }}>{(v / 1000).toFixed(step < 1000 ? 2 : 0)}s</text>
          </g>
        ))}
        {judged.map((s, i) => {
          const x = L + i * bw + 1;
          const top = y(s.latency);
          const h = Math.max(2, H - B - top);
          const w = Math.max(2, bw - 2);
          const r = Math.min(4, w / 2, h);
          const sel = selected === s.id;
          return (
            <g
              key={s.id}
              className="cursor-pointer"
              onClick={() => onSelect(sel ? null : s.id)}
              onMouseMove={(e) => setTip(tipAt(e, e.currentTarget.closest('.relative'), { status: s.status, step: s.n, tool: s.tool, text: s.text, extra: fmtS(s.latency) }))}
            >
              <rect x={x - 1} y={T} width={bw} height={H - T - B} fill="transparent" />
              <path
                className="bar-grow"
                style={{ transformOrigin: `0 ${H - B}px` }}
                d={`M${x} ${H - B} V${top + r} Q${x} ${top} ${x + r} ${top} H${x + w - r} Q${x + w} ${top} ${x + w} ${top + r} V${H - B} Z`}
                fill={STATUS[s.status].color}
                opacity={selected && !sel ? 0.35 : 1}
              />
              {(s.n % 5 === 0 || s.n === 1) && (
                <text x={x + w / 2} y={H - 6} textAnchor="middle" className="fill-on-surface-variant" style={{ font: '12px Inter, sans-serif' }}>{s.n}</text>
              )}
            </g>
          );
        })}
        <line x1={L} x2={L + judged.length * bw} y1={y(med)} y2={y(med)} stroke="#e3e2e2" strokeDasharray="4 4" opacity="0.7" />
        <text x={L} y={12} className="fill-on-background" style={{ font: '600 12px Inter, sans-serif' }}>- - median {fmtS(med)}</text>
      </svg>
      <Tip tip={tip} />
    </div>
  );
}

/* ─── Verdicts by tool ─────────────────────────────────────────────────
   Which tools the trouble comes from. Stacked in a fixed order (OK, warn,
   anomaly) with 2px gaps; sorted so the most anomalous tool is on top. */

export function ToolBreakdown({ steps, onPickTool }) {
  const rows = useMemo(() => {
    const m = new Map();
    steps.forEach((s) => {
      if (s.status === 'PENDING') return;
      const r = m.get(s.tool) || { tool: s.tool, OK: 0, WARN: 0, ANOMALY: 0, BLOCKED: 0 };
      r[s.status] += 1;
      m.set(s.tool, r);
    });
    return [...m.values()].sort((a, b) => (b.ANOMALY + b.BLOCKED) - (a.ANOMALY + a.BLOCKED) || b.WARN - a.WARN || (b.OK - a.OK));
  }, [steps]);
  if (!rows.length) return <p className="flex min-h-[200px] items-center justify-center text-[15px] text-on-surface-variant">No verdicts yet.</p>;
  const max = Math.max(...rows.map((r) => r.OK + r.WARN + r.ANOMALY + r.BLOCKED));

  return (
    <ul className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-2.5">
      {rows.map((r) => {
        const total = r.OK + r.WARN + r.ANOMALY + r.BLOCKED;
        return (
          <li key={r.tool}>
            <button type="button" onClick={() => onPickTool(r.tool)} className="group w-full text-left min-h-11">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-label-sm text-[12px] text-on-background break-all group-hover:text-primary-container transition-colors">{r.tool}</span>
                <span className="text-[12px] tabular-nums text-on-surface-variant shrink-0">
                  {total} · {r.BLOCKED ? `${r.BLOCKED} blocked` : r.ANOMALY ? `${r.ANOMALY} anomaly` : r.WARN ? `${r.WARN} warn` : 'all OK'}
                </span>
              </div>
              <div className="mt-1.5 flex h-2.5 gap-[2px]" style={{ width: `${(total / max) * 100}%` }}>
                {['OK', 'WARN', 'ANOMALY', 'BLOCKED'].filter((s) => r[s]).map((s) => (
                  <div key={s} className="h-full rounded-sm bar-grow-x" style={{ flexGrow: r[s], background: STATUS[s].color }} />
                ))}
              </div>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

/* ─── Confidence meter for feed cards ─── */
export function Confidence({ value }) {
  if (!Number.isFinite(value)) return null;
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] tabular-nums text-on-surface-variant" title="How sure the judge is">
      <span className="relative h-1.5 w-12 rounded-full bg-outline-variant/40 overflow-hidden">
        <span className="absolute inset-y-0 left-0 rounded-full bg-on-surface-variant" style={{ width: `${Math.round(value * 100)}%` }} />
      </span>
      {Math.round(value * 100)}%
    </span>
  );
}

