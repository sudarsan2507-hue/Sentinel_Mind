import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { useSocket } from '../hooks/useSocket';

/* ─── vis-network, bundled ───
   Was injected from unpkg at runtime, so the trace graph silently stayed empty
   on any machine without internet -- including a venue with bad wifi. A dynamic
   import keeps it in its own chunk, so the landing page does not pay for it. */
function loadVisNetwork() {
  return import('vis-network/standalone');
}

/* ─── Colour map matching vis-network PENDING/OK/WARN/ANOMALY ─── */
const VERDICT_COLORS = {
  OK:      { border: '#00ff66', background: '#0a2115' },
  WARN:    { border: '#fbbf24', background: '#2a1f08' },
  ANOMALY: { border: '#f87171', background: '#2a0e0e' },
  PENDING: { border: '#3b4b3a', background: '#1b1c1c' },
};

/* ─── Status pill ─── */
const statusStyles = {
  OK:      'bg-primary-container/15 text-primary-container border border-primary-container/20',
  WARN:    'bg-amber-500/10 text-amber-400 border border-amber-500/20',
  ANOMALY: 'bg-error/10 text-error border border-error/20',
  PENDING: 'bg-surface-container-high text-on-surface-variant border border-outline-variant/30',
};

function StatusPill({ status }) {
  return (
    <span className={`font-label-sm text-[12px] font-bold tracking-widest px-2 py-0.5 rounded uppercase ${statusStyles[status] || statusStyles.PENDING}`}>
      {status}
    </span>
  );
}

/* ─── Stat card ─── */
function StatCard({ label, value, tone }) {
  const toneClass = {
    ok: 'text-primary-container',
    warn: 'text-amber-400',
    anomaly: 'text-error',
    neutral: 'text-on-background',
  }[tone] || 'text-on-background';

  return (
    <div className="bg-surface-container-low border border-outline-variant/20 rounded-xl p-5 flex flex-col gap-2">
      <span className="font-label-sm text-[12px] text-on-surface-variant">{label}</span>
      <span className={`font-headline-lg text-[28px] font-bold tabular-nums ${toneClass}`}>{value}</span>
    </div>
  );
}

/* ─── Trace Graph ─── */
function TraceGraph({ nodes, edges }) {
  const hostRef = useRef(null);
  const netRef = useRef(null);
  const dsRef = useRef({ nodes: null, edges: null });
  // vis loads asynchronously. Nodes that arrive first (always, on a reload --
  // /audit answers before the chunk does) were silently dropped, leaving
  // "20 NODES" over an empty canvas. `ready` re-runs the sync once it exists.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadVisNetwork().then((vis) => {
      if (cancelled) return;
      dsRef.current.nodes = new vis.DataSet();
      dsRef.current.edges = new vis.DataSet();
      netRef.current = new vis.Network(
        hostRef.current,
        { nodes: dsRef.current.nodes, edges: dsRef.current.edges },
        {
          nodes: {
            shape: 'box',
            font: { color: '#e3e2e2', size: 12, face: 'JetBrains Mono, monospace' },
            margin: 10,
            borderWidth: 1,
            shapeProperties: { borderRadius: 6 },
          },
          edges: { color: '#3b4b3a', arrows: 'to', smooth: { type: 'cubicBezier' } },
          layout: { hierarchical: { direction: 'UD', sortMethod: 'directed', nodeSpacing: 160 } },
          physics: false,
          interaction: { hover: true, zoomView: true },
        }
      );
      setReady(true);
    });
    return () => { cancelled = true; netRef.current?.destroy(); };
  }, []);

  useEffect(() => {
    const ns = dsRef.current.nodes;
    const es = dsRef.current.edges;
    if (!ns || !es) return;

    nodes.forEach((n) => {
      const item = { id: n.id, label: n.label, color: VERDICT_COLORS[n.status] || VERDICT_COLORS.PENDING, title: n.title || '' };
      ns.get(n.id) ? ns.update(item) : ns.add(item);
    });
    edges.forEach((e) => {
      if (!es.get(e.id)) es.add(e);
    });
    const net = netRef.current;
    if (!net || !nodes.length) return;
    // fit() alone shrank a 20-step run to unreadable dashes. Fit while it is
    // legible; past that, hold a readable zoom and follow the newest step --
    // which is the one a developer mid-incident is looking at. Drag to scroll back.
    // Deferred one draw: new nodes have no layout position until vis redraws.
    net.once('afterDrawing', () => {
      net.fit({ animation: false });
      const MIN_SCALE = 0.75;
      if (net.getScale() < MIN_SCALE) {
        const newest = nodes[nodes.length - 1].id;
        const pos = net.getPositions([newest])[newest];
        // Newest step near the bottom edge, so the view is the recent history.
        const lift = ((hostRef.current?.clientHeight || 400) / 2 - 60) / MIN_SCALE;
        if (pos) net.moveTo({ position: { x: pos.x, y: pos.y - lift }, scale: MIN_SCALE, animation: { duration: 300 } });
      }
    });
    net.redraw();
  }, [nodes, edges, ready]);

  return <div ref={hostRef} className="w-full h-full" />;
}

/* ─── Main Dashboard Page ─── */

const headerButton = 'inline-flex min-h-11 items-center rounded-md border border-outline-variant/50 px-3 text-[14px] text-on-background hover:bg-surface-container-high active:bg-surface-container-high transition-colors';

export default function Dashboard() {
  const { connected, on } = useSocket();

  const [entries, setEntries] = useState([]);
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [goal, setGoal] = useState('');
  const [model, setModel] = useState('');

  useEffect(() => {
    document.title = 'Live dashboard · SentinelMind';
  }, []);
  const lastNodeId = useRef(null);

  /* Add a pending (grey) node as soon as trace arrives */
  const addPending = useCallback((event) => {
    setNodes((prev) => {
      if (prev.some((n) => n.id === event.id)) return prev;
      return [...prev, { id: event.id, label: event.tool, status: 'PENDING', title: 'awaiting verdict…' }];
    });
    setEdges((prev) => {
      const from = lastNodeId.current;
      lastNodeId.current = event.id;
      if (!from) return prev;
      return [...prev, { id: `${from}->${event.id}`, from, to: event.id }];
    });
  }, []);

  /* Wire socket events */
  useEffect(() => {
    const offs = [
      on('trace', addPending),
      on('verdict', (entry) => {
        setEntries((prev) => [entry, ...prev].slice(0, 200));
        setNodes((prev) => {
          const id = entry.event.id;
          const patch = { id, label: entry.event.tool, status: entry.status, title: entry.verdict.explanation };
          return prev.some((n) => n.id === id)
            ? prev.map((n) => (n.id === id ? patch : n))
            : [...prev, patch];
        });
      }),
      on('goal', (d) => {
        setGoal(d.goal);
        setEntries([]); setNodes([]); setEdges([]);
        lastNodeId.current = null;
      }),
      on('cleared', () => {
        setEntries([]); setNodes([]); setEdges([]);
        lastNodeId.current = null;
      }),
    ];
    return () => offs.forEach((off) => off && off());
  }, [on, addPending]);

  /* Rehydrate on mount */
  useEffect(() => {
    fetch('/session').then((r) => r.json()).then((d) => setGoal(d.goal || ''));
    // The judge model is configuration, not copy -- ask the server which one is live.
    fetch('/health').then((r) => r.json()).then((d) => setModel(d.model || '')).catch(() => {});
    fetch('/audit').then((r) => r.json()).then((d) => {
      if (!d.entries?.length) return;
      const all = [...d.entries].reverse().slice(0, 200);
      setEntries(all);
      setNodes(d.entries.map((e) => ({
        id: e.event.id, label: e.event.tool, status: e.status, title: e.verdict.explanation,
      })));
      setEdges(d.entries.slice(1).map((e, i) => ({
        id: `${d.entries[i].event.id}->${e.event.id}`,
        from: d.entries[i].event.id,
        to: e.event.id,
      })));
      lastNodeId.current = d.entries[d.entries.length - 1].event.id;
    });
  }, []);

  /* Derived stats */
  const counts = entries.reduce(
    (acc, e) => ({ ...acc, [e.status]: (acc[e.status] || 0) + 1 }),
    { OK: 0, WARN: 0, ANOMALY: 0 }
  );
  const latencies = entries.map((e) => e.verdict.latency_ms).filter(Number.isFinite);
  const mttd = latencies.length
    ? (latencies.reduce((a, b) => a + b, 0) / latencies.length / 1000).toFixed(2) + 's'
    : '—';
  const latestAnomaly = entries.find((e) => e.status === 'ANOMALY');

  return (
    <div className="min-h-screen bg-[#050505] text-on-background font-body-md">
      {/* ── Top bar ── wraps on phones instead of scrolling sideways */}
      <header className="sticky top-0 z-50 bg-surface-container-lowest/95 border-b border-outline-variant/30 backdrop-blur-md">
        <div className="max-w-container-max mx-auto flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-margin-mobile md:px-margin-desktop py-2">
          <div className="flex items-center gap-4">
            <Link to="/" className="inline-flex min-h-11 items-center font-headline-lg text-[20px] font-extrabold text-on-background tracking-tight hover:text-primary-container transition-colors">
              SentinelMind
            </Link>
            <span className="flex items-center gap-2 text-[14px] text-on-surface-variant" role="status">
              <span
                aria-hidden="true"
                className={`w-2 h-2 rounded-full transition-colors ${
                  connected ? 'bg-primary-container shadow-[0_0_6px_rgba(0,255,102,0.5)]' : 'bg-on-surface-variant/50'
                }`}
              />
              {connected ? 'Live' : 'Disconnected'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a
              href="/audit/export"
              download
              className={headerButton}
            >
              Export log
            </a>
            <button
              type="button"
              onClick={() => {
                // Destructive: wipes this session's verdicts for everyone watching.
                if (window.confirm('Clear all verdicts from this session?')) fetch('/audit/clear', { method: 'POST' });
              }}
              className={headerButton}
            >
              Clear
            </button>
            <Link
              to="/graph"
              className="inline-flex min-h-11 items-center rounded-md border border-primary-container/40 px-3 text-[14px] text-primary-container hover:bg-primary-container/10 transition-colors"
            >
              Failure memory
            </Link>
          </div>
        </div>
      </header>

      <main className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-8 flex flex-col gap-6">

        {/* ── Goal display ── */}
        <div className={`rounded-xl border px-5 py-3 font-body-md text-[16px] md:text-[14px] flex items-center gap-3 ${
          goal
            ? 'bg-surface-container-low border-outline-variant/20'
            : 'bg-amber-500/5 border-amber-500/20'
        }`}>
          <span className="font-label-sm text-[12px] text-on-surface-variant shrink-0">Monitored goal</span>
          <span className={goal ? 'text-on-surface-variant' : 'text-amber-400 italic'}>
            {goal || 'Not declared — goal drift cannot be assessed for this run.'}
          </span>
        </div>

        {/* ── Anomaly banner ── */}
        {latestAnomaly && (
          <div className="rounded-xl border border-error/30 bg-error/5 border-l-4 border-l-error px-5 py-4">
            <div className="font-label-sm text-[12px] text-error font-bold mb-1.5">
              Anomaly detected — {latestAnomaly.event.tool}
            </div>
            <div className="font-body-md text-[16px] md:text-[14px] text-on-surface-variant">{latestAnomaly.verdict.explanation}</div>
          </div>
        )}

        {/* ── Stat cards ── */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
          <StatCard label="Steps observed" value={entries.length} tone="neutral" />
          <StatCard label="OK" value={counts.OK} tone="ok" />
          <StatCard label="Warn" value={counts.WARN} tone="warn" />
          <StatCard label="Anomaly" value={counts.ANOMALY} tone="anomaly" />
          <StatCard label="Mean time to detect" value={mttd} tone="neutral" />
        </div>

        {/* ── Main grid: trace graph + verdict feed ── */}
        <div className="grid grid-cols-1 lg:grid-cols-[1.4fr_1fr] gap-6">
          {/* Trace graph */}
          <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-outline-variant/15 flex items-center justify-between">
              <h2 className="font-headline-lg text-[17px] text-on-background">Live Trace Graph</h2>
              <span className="font-label-sm text-[12px] text-on-surface-variant">{nodes.length} nodes</span>
            </div>
            <div className={`${nodes.length ? 'h-[420px] md:h-[480px]' : 'h-48 md:h-[480px]'} p-2`}>
              {nodes.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center gap-2 px-6 text-center text-on-surface-variant">
                  <p className="text-[16px] text-on-background">No steps yet</p>
                  <p className="text-[15px] max-w-[300px]">Run <code className="font-label-sm text-primary-container">python backend/real_agent.py</code> and each step appears here as it is judged.</p>
                </div>
              ) : (
                <TraceGraph nodes={nodes} edges={edges} />
              )}
            </div>
          </div>

          {/* Verdict feed */}
          <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-outline-variant/15">
              <h2 className="font-headline-lg text-[17px] text-on-background">Verdict Feed</h2>
            </div>
            <div className="flex-1 overflow-y-auto max-h-[480px]">
              {entries.length === 0 ? (
                <p className="px-6 py-10 text-center text-[16px] md:text-[15px] text-on-surface-variant">Verdicts appear here, newest first.</p>
              ) : (
                entries.map((e) => (
                  <div
                    key={e.sequence}
                    className={`px-5 py-4 border-b border-outline-variant/10 border-l-2 transition-colors ${
                      e.status === 'ANOMALY'
                        ? 'border-l-error bg-error/5'
                        : e.status === 'WARN'
                        ? 'border-l-amber-500'
                        : 'border-l-primary-container/40'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1.5">
                      <StatusPill status={e.status} />
                      <span className="font-label-sm text-[12px] text-primary-container">{e.event.tool}</span>
                      <span className="ml-auto font-label-sm text-[12px] text-on-surface-variant tabular-nums">
                        {e.event.duration_ms}ms · {(e.verdict.latency_ms / 1000).toFixed(2)}s
                      </span>
                    </div>
                    <p className={`font-body-md text-[15px] md:text-[14px] leading-snug ${e.verdict.degraded ? 'text-on-surface-variant italic' : 'text-on-surface-variant'}`}>
                      {e.verdict.explanation}
                    </p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* ── Knowledge Graph CTA ── */}
        <Link
          to="/graph"
          className="flex items-center justify-between p-5 bg-surface-container-low border border-primary-container/20 rounded-2xl hover:border-primary-container/40 hover:bg-primary-container/5 transition-all group"
        >
          <div className="flex flex-col gap-1">
            <span className="font-headline-lg text-[17px] text-on-background">Failure memory</span>
            <span className="font-body-md text-[16px] md:text-[13px] text-on-surface-variant">
              How this agent has failed across runs, why, and the lessons fed back to it.
            </span>
          </div>
          <ArrowRight aria-hidden="true" className="text-primary-container group-hover:translate-x-1 transition-transform w-6 h-6 shrink-0 ml-4" />
        </Link>

      </main>

      <footer className="border-t border-outline-variant/10 py-6 px-margin-mobile md:px-margin-desktop mt-4">
        <p className="font-label-sm text-[12px] text-on-surface-variant text-center">
          Meta-agent: {model || '…'} via Groq · Codecrash · FRONTIER 2026 · VIT Chennai
        </p>
      </footer>
    </div>
  );
}
