import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useSocket } from '../hooks/useSocket';

/* ─── Failure modes, in a sentence each ───
   The page used to explain every failure in four paragraphs; nobody reads
   that. `short` is the one line on screen; the rest sits behind a disclosure
   for anyone who wants the reasoning. True of LLM agents generally -- no
   statistics we have not measured. */
const FAILURE = {
  hallucinated_tool: {
    title: 'Invented tool',
    short: 'Asked for an action it has no tool for, it made one up.',
    why: 'A language model continues patterns. When a task implies an action — issue a refund, notify the customer — and no tool provides it, the most plausible continuation is a plausible-looking tool name.',
    fix: 'Tell the agent the capability is missing, by capability rather than by URL, so it says a human is needed instead of inventing another endpoint.',
  },
  infinite_loop: {
    title: 'Loop',
    short: 'Called the same tool again and again without getting anywhere.',
    why: 'An agent has no built-in sense of “I already tried this”. If a result does not resolve the uncertainty, the same action stays the most likely next step — and rewording the query hides it from exact-match checks.',
    fix: 'Call once or twice, then act on what came back or answer.',
  },
  goal_drift: {
    title: 'Goal drift',
    short: 'Stopped working on what it was asked to do.',
    why: 'In a long context the original instruction is one message among many; the latest tool output steers the next step more than the goal does.',
    fix: 'Judge every step against the declared goal. There is no deterministic remedy to inject yet.',
  },
  exception: {
    title: 'Error',
    short: 'A call failed — often because the tool it called does not exist.',
    why: 'Usually a downstream effect: an invented endpoint answers 403. Agents also tend to carry on after an error, because the next step is generated either way.',
    fix: 'Surface the error in the answer instead of retrying blindly; check which other failure the same tools show.',
  },
  unsafe_action: {
    title: 'Unsafe action',
    short: 'Used a real tool in a way the rules did not allow — stopped before it ran.',
    why: 'Pressure in the prompt ("never tell a customer no") outweighs a policy the agent read a few steps earlier. The model optimises for the instruction it was given, not for the rule it found.',
    fix: 'Check side-effect tools against the goal and the facts gathered before they run (guard mode), and send the reason back so the agent can change course.',
  },
  inefficient_reasoning: {
    title: 'Sloppy step',
    short: 'Worked, but slow, oddly shaped or only loosely on topic.',
    why: 'The catch-all for warnings with no hard signal behind them. Minor alone; repeated on one tool it often comes before a sharper failure.',
    fix: 'Watch the trend on the tools involved.',
  },
};

/* Lessons are written for the agent, in full sentences. On screen they get a headline. */
function lessonHeadline(text) {
  let m = text.match(/You have NO tool that can (.+?)\. Across (\d+)/);
  if (m) return { head: `Can't ${m[1]}`, n: `${m[2]} attempt${m[2] === '1' ? '' : 's'}`, kind: 'hallucinated_tool' };
  m = text.match(/Calling '(.+?)' over and over has been flagged as a loop (\d+)/);
  if (m) return { head: `Loops on ${m[1]}`, n: `${m[2]}×`, kind: 'infinite_loop' };
  m = text.match(/'(.+?)' was stopped (\d+) time/);
  if (m) return { head: `Stopped: ${m[1]}`, n: `${m[2]}×`, kind: 'unsafe_action' };
  m = text.match(/NOT in your tool registry and calling them has failed (\d+)/);
  if (m) return { head: 'Unregistered tools', n: `${m[1]}×`, kind: 'hallucinated_tool' };
  return { head: text.split('.')[0], n: '', kind: null };
}

const COLORS = {
  failure_mode: { fill: '#2a1416', stroke: '#f87171', label: 'Failure' },
  tool: { fill: '#10201a', stroke: '#34d27a', label: 'Tool' },
  invented: { fill: '#1d1830', stroke: '#a78bfa', label: 'Invented tool' },
  capability: { fill: '#2a2008', stroke: '#f5b041', label: 'Missing capability' },
};
const key = (n) => `${n.type}:${n.id}`;

/* Real pixel width of the container -- callback ref, so it follows remounts. */
function useWidth() {
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

/* ─── Layout ───
   Rings around the agent, read inside-out: how it failed, which tools did it,
   what they were reaching for. Deterministic -- the same memory draws the same
   picture every time, unlike a physics simulation. Tools sit next to the
   failure they show most; capabilities next to the tools that wanted them. */
function spread(items, rx, ry, cx, cy) {
  if (!items.length) return [];
  const sorted = [...items].sort((a, b) => a.a - b.a);
  const step = (2 * Math.PI) / sorted.length;
  let sx = 0; let sy = 0;
  sorted.forEach((it, i) => { sx += Math.sin(it.a - i * step); sy += Math.cos(it.a - i * step); });
  const offset = Math.atan2(sx, sy);
  return sorted.map((it, i) => {
    const a = offset + i * step;
    return { ...it, a, x: cx + rx * Math.cos(a), y: cy + ry * Math.sin(a) };
  });
}

const RING = { fail: 0.34, tool: 0.6, cap: 1 };
// Phones: no room for labels around the rim, so the rings use the full width
// and spread further apart; names appear for what you tap (and in the card).
const RING_NARROW = { fail: 0.44, tool: 0.74, cap: 1 };
const margin = (narrow) => (narrow ? 22 : 150);

function computeLayout(nodes, edges, W, H) {
  const cx = W / 2; const cy = H / 2;
  const narrow = W < 640;
  const R = narrow ? RING_NARROW : RING;
  const RX = W / 2 - margin(narrow);
  const RY = H / 2 - 40;
  const pos = new Map();
  const fails = nodes.filter((n) => n.type === 'failure_mode').sort((a, b) => b.count - a.count);
  fails.forEach((f, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, fails.length);
    pos.set(key(f), { a, x: cx + RX * R.fail * Math.cos(a), y: cy + RY * R.fail * Math.sin(a) });
  });
  const meanAngle = (pairs) => {
    let sx = 0; let sy = 0;
    pairs.forEach(([a, w]) => { sx += Math.cos(a) * w; sy += Math.sin(a) * w; });
    return Math.atan2(sy, sx);
  };
  const tools = nodes.filter((n) => n.type === 'tool').map((t) => ({
    n: t,
    a: meanAngle(edges.filter((e) => e.relation === 'exhibits' && e.src_id === t.id)
      .map((e) => [pos.get(`failure_mode:${e.dst_id}`)?.a ?? 0, e.count])),
  }));
  spread(tools, RX * R.tool, RY * R.tool, cx, cy).forEach((t) => pos.set(key(t.n), t));
  const caps = nodes.filter((n) => n.type === 'capability').map((c) => ({
    n: c,
    a: meanAngle(edges.filter((e) => e.relation === 'requires' && e.dst_id === c.id)
      .map((e) => [pos.get(`tool:${e.src_id}`)?.a ?? 0, e.count])),
  }));
  spread(caps, RX, RY, cx, cy).forEach((c) => pos.set(key(c.n), c));
  return { pos, cx, cy };
}

/* ─── The graph ─── */
function MemoryGraph({ nodes, edges, focus, onFocus }) {
  const [box, W0] = useWidth();
  const [hover, setHover] = useState(null);
  // Nodes can be dragged. Moved positions are tied to the canvas size they were
  // made at, so a resize falls back to the computed layout instead of leaving
  // nodes stranded off-canvas.
  const [moved, setMoved] = useState({ size: '', at: {} });
  const [drag, setDrag] = useState(null);
  const W = Math.max(320, W0 || 900);
  const H = W < 640 ? Math.round(W * 1.1) : Math.max(520, Math.min(680, Math.round(W * 0.56)));
  const narrow = W < 640;

  // Goals are context, not structure -- they appear in the card, not as nodes.
  const shown = useMemo(() => nodes.filter((n) => n.type !== 'goal'), [nodes]);
  const links = useMemo(() => edges.filter((e) => e.relation !== 'missing_in'), [edges]);
  const { pos, cx: cx0, cy: cy0 } = useMemo(() => computeLayout(shown, links, W, H), [shown, links, W, H]);
  const size = `${W}x${H}`;
  const at = moved.size === size ? moved.at : {};
  const hasMoves = Object.keys(at).length > 0;
  const cx = at.agent ? at.agent.x : cx0;
  const cy = at.agent ? at.agent.y : cy0;
  // Where a node is now: dragged position if any, else the layout. Labels keep
  // pointing away from the agent, wherever either has been moved to.
  const P = (k) => {
    const m = at[k];
    if (m) return { x: m.x, y: m.y, a: Math.atan2(m.y - cy, m.x - cx) };
    const b = pos.get(k);
    return b ? { ...b, a: at.agent ? Math.atan2(b.y - cy, b.x - cx) : b.a } : null;
  };

  const startDrag = (k, e) => {
    const p0 = k === 'agent' ? { x: cx, y: cy } : P(k);
    setDrag({ k, x0: e.clientX, y0: e.clientY, px: p0.x, py: p0.y, moved: false });
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };
  const moveDrag = (k, e) => {
    const d = drag;
    if (!d || d.k !== k) return;
    const dx = e.clientX - d.x0; const dy = e.clientY - d.y0;
    if (!d.moved && Math.hypot(dx, dy) < 4) return; // a click, not a drag
    if (!d.moved) setDrag({ ...d, moved: true });
    const x = Math.min(W - 10, Math.max(10, d.px + dx));
    const y = Math.min(H - 10, Math.max(10, d.py + dy));
    setMoved((m) => ({ size, at: { ...(m.size === size ? m.at : {}), [k]: { x, y } } }));
  };
  const endDrag = (k) => {
    const d = drag;
    setDrag(null);
    if (d && !d.moved && k !== 'agent') onFocus(k);
  };
  const dragProps = (k) => ({
    onPointerDown: (e) => startDrag(k, e),
    onPointerMove: (e) => moveDrag(k, e),
    onPointerUp: () => endDrag(k),
    onPointerCancel: () => setDrag(null),
    style: { touchAction: 'none' },
  });
  const invented = useMemo(() => new Set(links.filter((e) => e.relation === 'requires').map((e) => e.src_id)), [links]);

  // The lit neighbourhood: whatever is hovered, else whatever is selected.
  const active = hover || focus;
  const lit = useMemo(() => {
    if (!active) return null;
    const s = new Set([active]);
    const near = links.filter((e) => `${e.src_type}:${e.src_id}` === active || `${e.dst_type}:${e.dst_id}` === active);
    near.forEach((e) => { s.add(`${e.src_type}:${e.src_id}`); s.add(`${e.dst_type}:${e.dst_id}`); });
    // A failure lights its tools AND what those tools were reaching for: the whole chain.
    if (active.startsWith('failure_mode:')) {
      const tools = new Set(near.map((e) => e.src_id));
      links.filter((e) => e.relation === 'requires' && tools.has(e.src_id)).forEach((e) => s.add(`capability:${e.dst_id}`));
    }
    return s;
  }, [active, links]);
  const edgeLit = (e) => !lit || (lit.has(`${e.src_type}:${e.src_id}`) && lit.has(`${e.dst_type}:${e.dst_id}`));

  const radius = (n) => (n.type === 'failure_mode' ? (narrow ? 10 + Math.sqrt(n.count) * 2.2 : 13 + Math.sqrt(n.count) * 3.2) : n.type === 'tool' ? 6 + Math.min(n.count, 8) : 9 + Math.min(n.count, 8) * 0.8);

  return (
    <div ref={box} className="relative w-full">
      {hasMoves && (
        <button
          type="button"
          onClick={() => setMoved({ size: '', at: {} })}
          className="absolute right-4 top-2 z-10 inline-flex min-h-11 md:min-h-9 items-center rounded-md border border-outline-variant/60 bg-surface-container-low px-3 text-[13px] text-on-background hover:bg-surface-container-high"
        >
          Reset layout
        </button>
      )}
      <svg width={W} height={H} className="block" role="img" aria-label={`Failure memory: ${shown.filter((n) => n.type === 'failure_mode').length} kinds of failure across ${shown.filter((n) => n.type === 'tool').length} tools`}>
        <defs>
          <radialGradient id="kg-core" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#00ff66" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#00ff66" stopOpacity="0" />
          </radialGradient>
        </defs>
        {/* rings */}
        {Object.values(narrow ? RING_NARROW : RING).map((f) => (
          <ellipse key={f} cx={cx} cy={cy} rx={(W / 2 - margin(narrow)) * f} ry={(H / 2 - 40) * f} fill="none" stroke="#ffffff0d" strokeDasharray="2 6" />
        ))}
        {/* the agent at the centre, with spokes to each way it failed */}
        <circle cx={cx} cy={cy} r="46" fill="url(#kg-core)" pointerEvents="none" />
        {shown.filter((n) => n.type === 'failure_mode').map((f) => {
          const p = P(key(f));
          const on = !lit || lit.has(key(f));
          return <line key={`spoke-${f.id}`} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#f87171" strokeOpacity={on ? 0.35 : 0.06} strokeWidth="1" className="kg-edge" />;
        })}
        <g className="cursor-grab active:cursor-grabbing" {...dragProps('agent')}>
          <circle cx={cx} cy={cy} r="22" fill="transparent" />
          <circle cx={cx} cy={cy} r="15" fill="#0b120d" stroke="#00ff66" strokeWidth="1.5" />
          <text x={cx} y={cy + 32} textAnchor="middle" className="fill-on-surface-variant" style={{ font: '12px Inter, sans-serif' }}>the agent</text>
        </g>

        {/* links, curved toward the centre */}
        {links.map((e, i) => {
          const a = P(`${e.src_type}:${e.src_id}`);
          const b = P(`${e.dst_type}:${e.dst_id}`);
          if (!a || !b) return null;
          const mx = (a.x + b.x) / 2 * 0.8 + cx * 0.2;
          const my = (a.y + b.y) / 2 * 0.8 + cy * 0.2;
          const on = edgeLit(e);
          return (
            <path
              key={i}
              d={`M${a.x} ${a.y} Q${mx} ${my} ${b.x} ${b.y}`}
              fill="none"
              stroke={e.relation === 'requires' ? '#e0a43a' : '#f87171'}
              strokeOpacity={on ? (lit ? 0.85 : 0.35) : 0.05}
              strokeWidth={1 + Math.log2(e.count)}
              className="kg-edge"
              style={{ animationDelay: `${200 + i * 12}ms` }}
            />
          );
        })}

        {/* nodes */}
        {shown.map((n, i) => {
          const k = key(n);
          const p = P(k);
          if (!p) return null;
          const on = !lit || lit.has(k);
          const sel = focus === k;
          const r = radius(n);
          const c = COLORS[n.type === 'tool' && invented.has(n.id) ? 'invented' : n.type];
          const showLabel = !narrow || n.type === 'failure_mode' || k === active;
          // Labels point away from the centre. Tool names run radially, like
          // spokes, so neighbours on the ring can never overlap; the few
          // failures and capabilities read horizontally.
          const dx = Math.cos(p.a); const dy = Math.sin(p.a);
          // On phones the rim has no room, so a tapped label sits centred under its node.
          const radial = n.type === 'tool' && !narrow;
          const flip = dx < 0;
          const deg = (p.a * 180) / Math.PI + (flip ? 180 : 0);
          const under = narrow && n.type !== 'failure_mode';
          const anchor = under ? 'middle' : radial ? (flip ? 'end' : 'start') : dx > 0.3 ? 'start' : dx < -0.3 ? 'end' : 'middle';
          const lx = under ? Math.min(W - 60, Math.max(60, p.x)) : p.x + dx * (r + 7);
          const ly = under ? p.y + r + 16 : radial ? p.y + dy * (r + 7) : p.y + dy * (r + 9) + (anchor === 'middle' ? (dy > 0 ? 11 : -3) : 4);
          const labelTransform = radial ? `rotate(${deg} ${lx} ${ly})` : undefined;
          const raw = n.type === 'tool' ? n.id.replace(/^internal_api:/, '') : n.type === 'failure_mode' ? (FAILURE[n.id]?.title ?? n.id) : n.id.replace(/_/g, ' ');
          const max = n.type === 'tool' ? (narrow ? 14 : 18) : 26;
          const label = raw.length > max ? `${raw.slice(0, max - 1)}…` : raw;
          return (
            <g
              key={k}
              className="kg-node cursor-grab active:cursor-grabbing"
              {...dragProps(k)}
              style={{ touchAction: 'none', animationDelay: `${n.type === 'failure_mode' ? 0 : n.type === 'tool' ? 150 + i * 18 : 400 + i * 18}ms`, transformOrigin: `${p.x}px ${p.y}px` }}
              opacity={on ? 1 : 0.15}
              onMouseEnter={() => setHover(k)}
              onMouseLeave={() => setHover(null)}
              role="button"
              tabIndex={0}
              aria-label={`${n.type.replace('_', ' ')} ${raw}, seen ${n.count} times`}
              onKeyDown={(ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onFocus(k); } }}
            >
              <circle cx={p.x} cy={p.y} r={Math.max(r, 14)} fill="transparent" />
              {sel && n.type === 'failure_mode' && <circle cx={p.x} cy={p.y} r={r + 8} fill="none" stroke="#f87171" strokeOpacity="0.5" className="kg-pulse" style={{ transformOrigin: `${p.x}px ${p.y}px` }} />}
              <circle
                cx={p.x} cy={p.y} r={r}
                fill={c.fill}
                stroke={sel ? '#ffffff' : c.stroke}
                strokeWidth={n.type === 'failure_mode' ? 2 : 2}
              />
              {n.type === 'failure_mode' && (
                <text x={p.x} y={p.y + 5} textAnchor="middle" className="fill-on-background" style={{ font: '700 14px Inter, sans-serif' }}>{n.count}</text>
              )}
              {showLabel && (
                <text
                  x={lx} y={ly} textAnchor={anchor} transform={labelTransform} dominantBaseline={radial ? 'middle' : undefined}
                  className={n.type === 'failure_mode' ? 'fill-on-background' : 'fill-on-surface-variant'}
                  style={{ font: n.type === 'failure_mode' ? '600 13px Inter, sans-serif' : n.type === 'tool' ? '500 11px "JetBrains Mono", monospace' : '500 12px Inter, sans-serif' }}
                >
                  {label}
                  {label !== raw && <title>{raw}</title>}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ─── The card for whatever is selected ─── */
function FocusCard({ focusKey, nodes, edges, lessons, totalFailures, runs }) {
  if (!focusKey) return null;
  const [type, ...rest] = focusKey.split(':');
  const id = rest.join(':');
  const node = nodes.find((n) => n.type === type && n.id === id);
  if (!node) return null;

  if (type === 'failure_mode') {
    const f = FAILURE[id] ?? { title: id, short: '', why: '', fix: '' };
    const hits = edges.filter((e) => e.relation === 'exhibits' && e.dst_id === id).sort((a, b) => b.count - a.count);
    const latest = node.evidence?.[node.evidence.length - 1];
    const myLessons = lessons.map(lessonHeadline).filter((l) => l.kind === id);
    const share = totalFailures ? Math.round((node.count / totalFailures) * 100) : 0;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-[13px] text-error">Failure</p>
            <h2 className="font-headline-lg text-[26px] font-bold text-on-background leading-tight">{f.title}</h2>
          </div>
          <div className="text-right">
            <p className="font-headline-lg text-[34px] font-bold leading-none tabular-nums text-on-background">{node.count}</p>
            <p className="text-[13px] text-on-surface-variant">{share}% of failures</p>
          </div>
        </div>
        <p className="text-[16px] leading-snug text-on-background">{f.short}</p>
        <div className="flex flex-wrap gap-1.5">
          {hits.slice(0, 6).map((e) => (
            <span key={e.src_id} className="rounded-md border border-outline-variant/50 px-2 py-1 font-label-sm text-[12px] text-on-surface-variant">
              {e.src_id.replace(/^internal_api:/, '')}{e.count > 1 ? ` ×${e.count}` : ''}
            </span>
          ))}
          {hits.length > 6 && <span className="px-1 py-1 text-[12px] text-on-surface-variant">+{hits.length - 6} more</span>}
        </div>
        {latest && (
          <blockquote className="border-l-2 border-error/60 pl-3 text-[14px] leading-snug text-on-surface-variant">
            <span className="line-clamp-3">“{latest.explanation}”</span>
            <span className="mt-1 block text-[12px] text-on-surface-variant/90">the judge, on {latest.tool}</span>
          </blockquote>
        )}
        {myLessons.length > 0 && (
          <div className="rounded-lg border border-primary-container/25 bg-primary-container/[0.05] px-3 py-2.5">
            <p className="text-[12px] text-primary-container">What the agent is told next run</p>
            <ul className="mt-1 flex flex-col gap-0.5">
              {myLessons.map((l) => <li key={l.head} className="text-[14px] text-on-background">{l.head} <span className="text-on-surface-variant">· {l.n}</span></li>)}
            </ul>
          </div>
        )}
        <details className="group">
          <summary className="cursor-pointer min-h-11 flex items-center text-[14px] text-on-surface-variant hover:text-on-background">Why does this happen?</summary>
          <div className="mt-1 flex flex-col gap-2 text-[14px] leading-relaxed text-on-surface-variant">
            <p>{f.why}</p>
            <p><span className="text-on-background">Fix: </span>{f.fix}</p>
            {node.seen_in_runs && <p className="text-[13px]">Seen in {node.seen_in_runs.length} of the runs since per-run tracking began ({runs} recorded).</p>}
          </div>
        </details>
      </div>
    );
  }

  if (type === 'tool') {
    const modes = edges.filter((e) => e.relation === 'exhibits' && e.src_id === id);
    const cap = edges.find((e) => e.relation === 'requires' && e.src_id === id);
    return (
      <div className="flex flex-col gap-3">
        <p className="text-[13px] text-on-surface-variant">{cap ? 'Invented tool' : 'Tool'}</p>
        <h2 className="font-label-sm text-[18px] text-on-background break-all">{id}</h2>
        <p className="text-[16px] text-on-background">
          Flagged {node.count} time{node.count === 1 ? '' : 's'}{node.last_verdict ? `, last as ${node.last_verdict.toLowerCase()}` : ''}.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {modes.map((e) => (
            <span key={e.dst_id} className="rounded-md border border-error/40 px-2 py-1 text-[13px] text-on-background">{FAILURE[e.dst_id]?.title ?? e.dst_id} ×{e.count}</span>
          ))}
        </div>
        {cap && <p className="text-[15px] text-on-surface-variant">It does not exist. The agent wanted to <span className="text-amber-300">{cap.dst_id.replace(/_/g, ' ')}</span> and made a tool up for it.</p>}
      </div>
    );
  }

  // capability
  const tried = edges.filter((e) => e.relation === 'requires' && e.dst_id === id);
  const goals = edges.filter((e) => e.relation === 'missing_in' && e.src_id === id);
  const attempts = tried.reduce((n, e) => n + e.count, 0);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[13px] text-amber-300">Missing capability</p>
      <h2 className="font-headline-lg text-[24px] font-bold text-on-background">{id.replace(/_/g, ' ')}</h2>
      <p className="text-[16px] text-on-background">
        The agent reached for this {attempts} time{attempts === 1 ? '' : 's'} with {tried.length} different invented name{tried.length === 1 ? '' : 's'}. It has no tool that can do it.
      </p>
      <div className="flex flex-wrap gap-1.5">
        {tried.map((e) => <span key={e.src_id} className="rounded-md border border-outline-variant/50 px-2 py-1 font-label-sm text-[12px] text-on-surface-variant">{e.src_id.replace(/^internal_api:/, '')}</span>)}
      </div>
      {goals[0] && <p className="text-[14px] text-on-surface-variant line-clamp-2">Needed for: {goals[0].dst_id}</p>}
    </div>
  );
}

/* ─── Main page ─── */
export default function KnowledgeGraphPage() {
  const { connected, on } = useSocket();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState(null);
  const [openLesson, setOpenLesson] = useState(null);
  const [lastLearnedTs, setLastLearnedTs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    document.title = 'Failure memory · SentinelMind';
  }, []);

  /* A button that succeeds silently is indistinguishable from a broken one.
     `announce` lets the mount effect fetch without setting state synchronously. */
  const load = useCallback((announce) => {
    if (announce) {
      setBusy(true);
      setError(null);
    }
    return fetch('/knowledge')
      .then((r) => {
        if (!r.ok) throw new Error(`GET /knowledge returned ${r.status}`);
        return r.json();
      })
      .then((d) => {
        setData(d);
        setLastUpdated(new Date());
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false);
        setBusy(false);
      });
  }, []);

  const refresh = useCallback(() => load(true), [load]);

  /* Destructive, so it asks first; the backend requires {confirm: true}. */
  const clearMemory = useCallback(() => {
    if (!window.confirm('Delete all accumulated failure memory? This cannot be undone.')) return;
    setBusy(true);
    setError(null);
    fetch('/knowledge/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ confirm: true }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(body.error || `POST /knowledge/clear returned ${r.status}`);
        }
      })
      .then(refresh)
      .catch((e) => {
        setError(e.message);
        setBusy(false);
      });
  }, [refresh]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- state is only set in promise callbacks
  useEffect(() => { load(false); }, [load]);

  useEffect(() => {
    const off = on('learned', () => {
      setLastLearnedTs(Date.now());
      refresh();
    });
    const off2 = on('knowledge_cleared', () => {
      setData(null);
      setPicked(null);
    });
    return () => { off && off(); off2 && off2(); };
  }, [on, refresh]);

  const nodes = useMemo(() => data?.nodes ?? [], [data]);
  const edges = useMemo(() => data?.edges ?? [], [data]);
  const lessons = useMemo(() => data?.lessons ?? [], [data]);
  const runs = data?.summary?.runs ?? 0;
  const failures = useMemo(() => nodes.filter((n) => n.type === 'failure_mode').sort((a, b) => b.count - a.count), [nodes]);
  const totalFailures = failures.reduce((s, f) => s + f.count, 0);
  // Never open on nothing selected: default to the most frequent failure.
  const focusKey = picked && nodes.some((n) => key(n) === picked) ? picked : (failures[0] ? key(failures[0]) : null);

  return (
    <div className="min-h-screen bg-[#050505] text-on-background font-body-md">
      <header className="sticky top-0 z-50 bg-surface-container-lowest/95 border-b border-outline-variant/30 backdrop-blur-md">
        <div className="max-w-container-max mx-auto flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-margin-mobile md:px-margin-desktop py-2">
          <div className="flex items-center gap-4">
            <Link to="/" className="inline-flex min-h-11 items-center font-headline-lg text-[20px] font-extrabold text-on-background tracking-tight hover:text-primary-container transition-colors">
              SentinelMind
            </Link>
            <span className="flex items-center gap-2 text-[14px] text-on-surface-variant" role="status">
              <span className="relative flex w-2 h-2" aria-hidden="true">
                {connected && <span className="absolute inset-0 rounded-full bg-primary-container opacity-60 animate-ping" />}
                <span className={`relative w-2 h-2 rounded-full ${connected ? 'bg-primary-container' : 'bg-on-surface-variant/50'}`} />
              </span>
              {lastLearnedTs ? 'Learning' : connected ? 'Live' : 'Disconnected'}
            </span>
            {error && <span className="text-[13px] text-error max-w-[260px] truncate" title={error}>{error}</span>}
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={refresh} disabled={busy} title={lastUpdated ? `Updated ${lastUpdated.toLocaleTimeString()}` : undefined} className="inline-flex min-h-11 items-center rounded-md border border-outline-variant/50 px-3 text-[14px] text-on-background hover:bg-surface-container-high transition-colors disabled:opacity-40">
              {busy ? 'Refreshing…' : 'Refresh'}
            </button>
            <button type="button" onClick={clearMemory} disabled={busy} className="inline-flex min-h-11 items-center rounded-md border border-error/40 px-3 text-[14px] text-error hover:bg-error/10 transition-colors disabled:opacity-40">
              Clear memory
            </button>
            <Link to="/dashboard" className="inline-flex min-h-11 items-center rounded-md border border-primary-container/40 px-3 text-[14px] text-primary-container hover:bg-primary-container/10 transition-colors">
              Dashboard
            </Link>
          </div>
        </div>
      </header>

      <main className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-6 md:py-8 flex flex-col gap-5">
        <div>
          <h1 className="font-headline-lg text-[28px] md:text-[34px] font-bold leading-tight text-on-background">How this agent fails, and why</h1>
          <p className="mt-2 max-w-[780px] text-[16px] leading-relaxed text-on-surface-variant">
            Every warning and anomaly is remembered here across {runs} run{runs === 1 ? '' : 's'}. Pick a failure
            to see the tools behind it and what the agent is told because of it. Drag the graph around to explore.
          </p>
        </div>

        {loading ? (
          <p className="min-h-[100vh] py-32 text-center text-[15px] text-on-surface-variant">Loading failure memory…</p>
        ) : failures.length === 0 ? (
          <div className="flex min-h-[420px] flex-col items-center justify-center gap-3 rounded-xl border border-outline-variant/40 bg-surface-container-low text-center px-6">
            <p className="text-[18px] text-on-background">Nothing remembered yet</p>
            <p className="max-w-[420px] text-[15px] text-on-surface-variant">
              Run <code className="font-label-sm text-primary-container">python backend/real_agent.py</code>. Every warning and anomaly the judge finds lands here, live.
            </p>
          </div>
        ) : (
          <>
            {/* Failure tiles: count, share and spread at a glance -- and the
                keyboard / screen-reader way into the graph. */}
            <div role="tablist" aria-label="Failure modes" className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {failures.map((f) => {
                const active = focusKey === key(f);
                const share = totalFailures ? Math.round((f.count / totalFailures) * 100) : 0;
                const tools = edges.filter((e) => e.relation === 'exhibits' && e.dst_id === f.id).length;
                return (
                  <button
                    key={f.id}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setPicked(key(f))}
                    className={`kpi-tile text-left rounded-xl border p-4 transition-colors ${
                      active ? 'border-error/60 bg-error/[0.08]' : 'border-outline-variant/40 bg-surface-container-low hover:border-outline-variant'
                    }`}
                  >
                    <span className="block text-[15px] text-on-background">{FAILURE[f.id]?.title ?? f.id}</span>
                    <span className="mt-2 block font-headline-lg text-[28px] font-bold leading-none tabular-nums text-on-background">{f.count}</span>
                    <span className="mt-2 block text-[13px] text-on-surface-variant">
                      {share}% of failures · {tools} tool{tools === 1 ? '' : 's'}
                    </span>
                    <span className="mt-3 block h-1.5 rounded-full bg-outline-variant/30 overflow-hidden">
                      <span className="block h-full rounded-full bg-error/80 bar-grow-x" style={{ width: `${share}%` }} />
                    </span>
                  </button>
                );
              })}
            </div>

            <section className="rounded-xl border border-outline-variant/40 bg-surface-container-low overflow-hidden">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-5 pt-4 text-[13px] text-on-surface-variant">
                  {Object.values(COLORS).map((c) => (
                    <span key={c.label} className="inline-flex items-center gap-1.5">
                      <svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill={c.fill} stroke={c.stroke} strokeWidth="2" /></svg>
                      {c.label}
                    </span>
                  ))}
                  <span className="ml-auto hidden md:inline">Drag to move · hover to trace · click to inspect</span>
                </div>
                <MemoryGraph nodes={nodes} edges={edges} focus={focusKey} onFocus={setPicked} />
            </section>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 items-start">
              <aside className="rounded-xl border border-outline-variant/40 bg-surface-container-low p-5" aria-live="polite">
                <FocusCard focusKey={focusKey} nodes={nodes} edges={edges} lessons={lessons} totalFailures={totalFailures} runs={runs} />
              </aside>
            {/* What the agent is told -- headlines; the exact text on click */}
            <section className="rounded-xl border border-outline-variant/40 bg-surface-container-low p-5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-headline-lg text-[19px] text-on-background">What the agent is told next run</h2>
                <span className="text-[13px] text-on-surface-variant">with <code className="font-label-sm">real_agent.py --learn</code> · click one for the exact wording</span>
              </div>
              {lessons.length === 0 ? (
                <p className="mt-3 text-[15px] text-on-surface-variant">No lessons yet.</p>
              ) : (
                <ul className="mt-4 grid grid-cols-1 gap-2.5">
                  {lessons.map((l, i) => {
                    const h = lessonHeadline(l);
                    const open = openLesson === i;
                    return (
                      <li key={i}>
                        <button
                          type="button"
                          aria-expanded={open}
                          onClick={() => setOpenLesson(open ? null : i)}
                          className={`w-full text-left rounded-lg border px-4 py-3 transition-colors ${open ? 'border-primary-container/50 bg-primary-container/[0.05]' : 'border-outline-variant/40 hover:border-outline-variant'}`}
                          style={{ boxShadow: `inset 3px 0 0 ${h.kind === 'infinite_loop' ? '#fbbf24' : '#e0a43a'}` }}
                        >
                          <span className="flex items-baseline justify-between gap-3">
                            <span className="text-[15px] font-semibold text-on-background">{h.head}</span>
                            {h.n && <span className="shrink-0 text-[13px] tabular-nums text-on-surface-variant">{h.n}</span>}
                          </span>
                          {open && <span className="mt-2 block text-[14px] leading-snug text-on-surface-variant">{l}</span>}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
            </div>

            <details className="rounded-xl border border-outline-variant/40 bg-surface-container-low">
              <summary className="px-5 min-h-11 flex items-center cursor-pointer text-[15px] text-on-surface-variant hover:text-on-background">
                Raw graph data · {nodes.length} nodes, {edges.length} edges
              </summary>
              <div className="max-h-80 overflow-auto border-t border-outline-variant/30">
                <table className="w-full font-label-sm text-[12px] text-left">
                  <thead className="text-on-surface-variant">
                    <tr><th className="px-5 py-2">From</th><th className="py-2">Relation</th><th className="py-2">To</th><th className="px-5 py-2 text-right">Count</th></tr>
                  </thead>
                  <tbody>
                    {edges.map((e, i) => (
                      <tr key={i} className="border-t border-outline-variant/20 text-on-surface-variant">
                        <td className="px-5 py-2 break-all">{e.src_id}</td>
                        <td className="py-2">{e.relation}</td>
                        <td className="py-2 break-all">{e.dst_id}</td>
                        <td className="px-5 py-2 text-right tabular-nums">{e.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </>
        )}
      </main>
    </div>
  );
}
