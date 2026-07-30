import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useSocket } from '../hooks/useSocket';

/* ─── vis-network loaded from CDN (same approach as original frontend/index.html) ─── */
function loadVisNetwork() {
  return new Promise((resolve) => {
    if (window.vis) return resolve(window.vis);
    const script = document.createElement('script');
    script.src = 'https://unpkg.com/vis-network/standalone/umd/vis-network.min.js';
    script.onload = () => resolve(window.vis);
    document.head.appendChild(script);
  });
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
    <span className={`font-label-sm text-[10px] font-bold tracking-widest px-2 py-0.5 rounded uppercase ${statusStyles[status] || statusStyles.PENDING}`}>
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
      <span className="font-label-sm text-[10px] uppercase tracking-widest text-on-surface-variant/60">{label}</span>
      <span className={`font-headline-lg text-[28px] font-bold tabular-nums ${toneClass}`}>{value}</span>
    </div>
  );
}

/* ─── Trace Graph ─── */
function TraceGraph({ nodes, edges }) {
  const hostRef = useRef(null);
  const netRef = useRef(null);
  const dsRef = useRef({ nodes: null, edges: null });

  useEffect(() => {
    loadVisNetwork().then((vis) => {
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
    });
    return () => netRef.current?.destroy();
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
    if (nodes.length) netRef.current?.fit({ animation: { duration: 300 } });
  }, [nodes, edges]);

  return <div ref={hostRef} className="w-full h-full" />;
}

/* ─── Main Dashboard Page ─── */

export default function Dashboard() {
  const { connected, on } = useSocket();

  const [entries, setEntries] = useState([]);
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [goal, setGoal] = useState('');
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
      {/* ── Top bar ── */}
      <header className="sticky top-0 z-50 flex items-center justify-between px-margin-mobile md:px-margin-desktop py-4 bg-surface-container-lowest border-b border-outline-variant/20 backdrop-blur-md">
        <div className="flex items-center gap-6">
          <Link to="/" className="font-headline-lg text-[20px] font-extrabold text-on-background tracking-tighter hover:text-primary transition-colors">
            SentinelMind
          </Link>
          <span className="hidden md:block font-label-sm text-[11px] text-on-surface-variant/40 uppercase tracking-widest">Live Dashboard</span>
        </div>
        <div className="flex items-center gap-4">
          {/* Connection indicator */}
          <div className="flex items-center gap-2">
            <span
              className={`w-2 h-2 rounded-full transition-colors ${
                connected ? 'bg-primary-container shadow-[0_0_6px_rgba(0,255,102,0.5)]' : 'bg-on-surface-variant/30'
              }`}
            />
            <span className="font-label-sm text-[11px] text-on-surface-variant/60">
              {connected ? 'Monitoring live' : 'Disconnected'}
            </span>
          </div>
          {/* Action buttons */}
          <button
            onClick={() => window.open('/audit/export', '_blank')}
            className="hidden sm:block px-4 py-1.5 bg-surface-container-high/50 border border-outline-variant/20 rounded-lg font-label-sm text-[11px] text-on-surface hover:bg-surface-variant transition-colors"
          >
            Export Log
          </button>
          <button
            onClick={() => fetch('/audit/clear', { method: 'POST' })}
            className="px-4 py-1.5 bg-surface-container-high/50 border border-outline-variant/20 rounded-lg font-label-sm text-[11px] text-on-surface hover:bg-surface-variant transition-colors"
          >
            Clear
          </button>
          <Link
            to="/graph"
            className="px-4 py-1.5 bg-primary-container/10 border border-primary-container/20 rounded-lg font-label-sm text-[11px] text-primary-container hover:bg-primary-container/20 transition-colors"
          >
            Knowledge Graph
          </Link>
          <Link
            to="/"
            className="px-4 py-1.5 border border-outline-variant/30 rounded-lg font-label-sm text-[11px] text-on-surface-variant hover:text-primary hover:border-primary-container/30 transition-colors"
          >
            ← Home
          </Link>
        </div>
      </header>

      <main className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-8 flex flex-col gap-6">

        {/* ── Goal display ── */}
        <div className={`rounded-xl border px-5 py-3 font-body-md text-[14px] flex items-center gap-3 ${
          goal
            ? 'bg-surface-container-low border-outline-variant/20'
            : 'bg-amber-500/5 border-amber-500/20'
        }`}>
          <span className="font-label-sm text-[10px] uppercase tracking-widest text-on-surface-variant/50 shrink-0">Monitored goal</span>
          <span className={goal ? 'text-on-surface-variant' : 'text-amber-400 italic'}>
            {goal || 'Not declared — goal drift cannot be assessed for this run.'}
          </span>
        </div>

        {/* ── Anomaly banner ── */}
        {latestAnomaly && (
          <div className="rounded-xl border border-error/30 bg-error/5 border-l-4 border-l-error px-5 py-4">
            <div className="font-label-sm text-[11px] uppercase tracking-widest text-error font-bold mb-1.5">
              Anomaly detected — {latestAnomaly.event.tool}
            </div>
            <div className="font-body-md text-[14px] text-on-surface-variant">{latestAnomaly.verdict.explanation}</div>
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
              <h2 className="font-headline-lg text-[15px] text-on-background">Live Trace Graph</h2>
              <span className="font-label-sm text-[10px] text-on-surface-variant/40 uppercase tracking-widest">{nodes.length} nodes</span>
            </div>
            <div className="h-[480px] p-2">
              {nodes.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 text-on-surface-variant/30">
                  <span className="material-symbols-outlined text-[48px]">account_tree</span>
                  <p className="font-label-sm text-[11px] uppercase tracking-widest">No trace yet</p>
                  <p className="font-body-md text-[13px] text-center max-w-[240px]">Run <code className="font-label-sm text-primary-container">python demo_agent.py</code> to start a pipeline</p>
                </div>
              ) : (
                <TraceGraph nodes={nodes} edges={edges} />
              )}
            </div>
          </div>

          {/* Verdict feed */}
          <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-outline-variant/15">
              <h2 className="font-headline-lg text-[15px] text-on-background">Verdict Feed</h2>
            </div>
            <div className="flex-1 overflow-y-auto max-h-[480px]">
              {entries.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 text-on-surface-variant/30 py-16">
                  <span className="material-symbols-outlined text-[48px]">rss_feed</span>
                  <p className="font-label-sm text-[11px] uppercase tracking-widest">No verdicts yet</p>
                </div>
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
                      <span className="ml-auto font-label-sm text-[11px] text-on-surface-variant/40 tabular-nums">
                        {e.event.duration_ms}ms · {(e.verdict.latency_ms / 1000).toFixed(2)}s
                      </span>
                    </div>
                    <p className={`font-body-md text-[13px] leading-snug ${e.verdict.degraded ? 'text-on-surface-variant/50 italic' : 'text-on-surface-variant'}`}>
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
            <span className="font-headline-lg text-[15px] text-on-background">Knowledge Graph</span>
            <span className="font-body-md text-[13px] text-on-surface-variant">
              Explore accumulated failure memory — nodes, causal edges, and distilled lessons from past runs.
            </span>
          </div>
          <span className="material-symbols-outlined text-primary-container group-hover:translate-x-1 transition-transform text-[24px] shrink-0 ml-4">arrow_forward</span>
        </Link>

      </main>

      <footer className="border-t border-outline-variant/10 py-6 px-margin-mobile md:px-margin-desktop mt-4">
        <p className="font-label-sm text-[11px] text-on-surface-variant/30 text-center">
          Meta-agent: Claude Sonnet 5 · Codecrash · FRONTIER 2026 · VIT Chennai
        </p>
      </footer>
    </div>
  );
}
