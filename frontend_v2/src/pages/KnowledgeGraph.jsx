import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useSocket } from '../hooks/useSocket';

/* ─── Node type display config ─── */
const NODE_TYPE_CONFIG = {
  tool: {
    label: 'Tool',
    bg: 'bg-primary-container/10',
    border: 'border-primary-container/30',
    text: 'text-primary-container',
    dot: 'bg-primary-container',
    icon: 'construction',
  },
  failure_mode: {
    label: 'Failure Mode',
    bg: 'bg-error/10',
    border: 'border-error/30',
    text: 'text-error',
    dot: 'bg-error',
    icon: 'dangerous',
  },
  capability: {
    label: 'Capability',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    text: 'text-amber-400',
    dot: 'bg-amber-500',
    icon: 'extension_off',
  },
  goal: {
    label: 'Goal',
    bg: 'bg-surface-container-high/60',
    border: 'border-outline-variant/30',
    text: 'text-on-surface-variant',
    dot: 'bg-secondary',
    icon: 'flag',
  },
};

const RELATION_STYLES = {
  exhibits:    { label: 'exhibits failure', color: 'text-error/70' },
  requires:    { label: 'requires capability', color: 'text-amber-400/70' },
  missing_in:  { label: 'missing in goal', color: 'text-on-surface-variant/50' },
};

/* ─── Animated pulse dot ─── */
function Dot({ color }) {
  return <span className={`inline-block w-2 h-2 rounded-full ${color} shrink-0`} />;
}

/* ─── Node card ─── */
function NodeCard({ node, onClick, selected }) {
  const cfg = NODE_TYPE_CONFIG[node.type] || NODE_TYPE_CONFIG.tool;
  return (
    <button
      onClick={() => onClick(node)}
      className={`w-full text-left p-4 rounded-xl border transition-all group ${cfg.bg} ${cfg.border} ${
        selected ? 'ring-1 ring-primary-container/40 shadow-[0_0_12px_rgba(0,255,102,0.08)]' : 'hover:brightness-110'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="mt-0.5">
          <Dot color={cfg.dot} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`font-label-sm text-[10px] uppercase tracking-widest ${cfg.text} opacity-70`}>{cfg.label}</span>
            <span className="font-label-sm text-[10px] text-on-surface-variant/40 bg-surface-container-high/50 px-1.5 py-0.5 rounded">
              ×{node.count}
            </span>
          </div>
          <p className="font-label-sm text-[12px] text-on-surface break-all leading-snug">{node.id}</p>
          {node.last_verdict && (
            <span className={`mt-1 inline-block font-label-sm text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider ${
              node.last_verdict === 'ANOMALY' ? 'bg-error/10 text-error'
              : node.last_verdict === 'WARN' ? 'bg-amber-500/10 text-amber-400'
              : 'bg-primary-container/10 text-primary-container'
            }`}>
              last: {node.last_verdict}
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

/* ─── Edge row ─── */
function EdgeRow({ edge }) {
  const rel = RELATION_STYLES[edge.relation] || { label: edge.relation, color: 'text-on-surface-variant/50' };
  return (
    <div className="flex items-center gap-2 px-4 py-3 border-b border-outline-variant/10 text-[12px] font-label-sm last:border-0">
      <span className="text-on-surface-variant truncate max-w-[140px]" title={edge.src_id}>{edge.src_id}</span>
      <span className={`shrink-0 ${rel.color}`}>— {rel.label} →</span>
      <span className="text-on-surface-variant truncate max-w-[140px]" title={edge.dst_id}>{edge.dst_id}</span>
      <span className="ml-auto text-on-surface-variant/40 shrink-0">×{edge.count}</span>
    </div>
  );
}

/* ─── Main Knowledge Graph Page ─── */
export default function KnowledgeGraphPage() {
  const { connected, on } = useSocket();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState(null);
  const [filter, setFilter] = useState('all');
  const [lastLearnedTs, setLastLearnedTs] = useState(null);

  const refresh = useCallback(() => {
    fetch('/knowledge')
      .then((r) => r.json())
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  /* Initial load */
  useEffect(() => { refresh(); }, [refresh]);

  /* Auto-refresh when backend learns something new */
  useEffect(() => {
    const off = on('learned', (d) => {
      setLastLearnedTs(Date.now());
      refresh();
    });
    const off2 = on('knowledge_cleared', () => {
      setData(null);
      setSelectedNode(null);
    });
    return () => { off && off(); off2 && off2(); };
  }, [on, refresh]);

  /* Derived data */
  const nodes = data?.nodes ?? [];
  const edges = data?.edges ?? [];
  const lessons = data?.lessons ?? [];
  const summary = data?.summary ?? {};

  const filteredNodes = filter === 'all'
    ? nodes
    : nodes.filter((n) => n.type === filter);

  /* Edges connected to selected node */
  const relatedEdges = selectedNode
    ? edges.filter((e) => e.src_id === selectedNode.id || e.dst_id === selectedNode.id)
    : [];

  const nodeTypeGroups = ['tool', 'failure_mode', 'capability', 'goal'];

  return (
    <div className="min-h-screen bg-[#050505] text-on-background font-body-md">
      {/* ── Top bar ── */}
      <header className="sticky top-0 z-50 flex items-center justify-between px-margin-mobile md:px-margin-desktop py-4 bg-surface-container-lowest border-b border-outline-variant/20 backdrop-blur-md">
        <div className="flex items-center gap-6">
          <Link to="/" className="font-headline-lg text-[20px] font-extrabold text-on-background tracking-tighter hover:text-primary transition-colors">
            SentinelMind
          </Link>
          <div className="hidden md:flex items-center gap-1 text-on-surface-variant/30">
            <span className="font-label-sm text-[11px]">/</span>
          </div>
          <span className="hidden md:block font-label-sm text-[11px] text-on-surface-variant/50 uppercase tracking-widest">Knowledge Graph</span>
        </div>
        <div className="flex items-center gap-3">
          {lastLearnedTs && (
            <span className="font-label-sm text-[10px] text-primary-container/70 animate-pulse">
              ● New learning detected
            </span>
          )}
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-primary-container shadow-[0_0_6px_rgba(0,255,102,0.5)]' : 'bg-on-surface-variant/30'}`} />
            <span className="font-label-sm text-[11px] text-on-surface-variant/60">
              {connected ? 'Live' : 'Disconnected'}
            </span>
          </div>
          <button
            onClick={refresh}
            className="px-3 py-1.5 bg-surface-container-high/50 border border-outline-variant/20 rounded-lg font-label-sm text-[11px] text-on-surface hover:bg-surface-variant transition-colors"
          >
            Refresh
          </button>
          <button
            onClick={() => { fetch('/knowledge/clear', { method: 'POST' }).then(refresh); }}
            className="px-3 py-1.5 bg-error/10 border border-error/20 rounded-lg font-label-sm text-[11px] text-error hover:bg-error/20 transition-colors"
          >
            Clear Memory
          </button>
          <Link to="/dashboard" className="px-3 py-1.5 border border-outline-variant/30 rounded-lg font-label-sm text-[11px] text-on-surface-variant hover:text-primary hover:border-primary-container/30 transition-colors">
            ← Dashboard
          </Link>
          <Link to="/" className="px-3 py-1.5 border border-outline-variant/30 rounded-lg font-label-sm text-[11px] text-on-surface-variant hover:text-primary hover:border-primary-container/30 transition-colors">
            Home
          </Link>
        </div>
      </header>

      <main className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-8 flex flex-col gap-6">

        {/* ── Summary stat row ── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Total Nodes', value: summary.nodes ?? 0, color: 'text-on-background' },
            { label: 'Edges', value: summary.edges ?? 0, color: 'text-on-background' },
            { label: 'Runs Recorded', value: summary.runs ?? 0, color: 'text-primary-container' },
            { label: 'Lessons Distilled', value: lessons.length, color: 'text-amber-400' },
          ].map((s) => (
            <div key={s.label} className="bg-surface-container-low border border-outline-variant/20 rounded-xl p-4 flex flex-col gap-1.5">
              <span className="font-label-sm text-[10px] uppercase tracking-widest text-on-surface-variant/50">{s.label}</span>
              <span className={`font-headline-lg text-[26px] font-bold tabular-nums ${s.color}`}>{s.value}</span>
            </div>
          ))}
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-32 text-on-surface-variant/30">
            <div className="flex flex-col items-center gap-4">
              <span className="material-symbols-outlined text-[48px] animate-spin" style={{ animationDuration: '2s' }}>autorenew</span>
              <p className="font-label-sm text-[11px] uppercase tracking-widest">Loading knowledge graph…</p>
            </div>
          </div>
        ) : nodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 gap-4 text-on-surface-variant/30">
            <span className="material-symbols-outlined text-[64px]">hub</span>
            <p className="font-label-sm text-[13px] uppercase tracking-widest">No knowledge accumulated yet</p>
            <p className="font-body-md text-[14px] text-center max-w-[360px] text-on-surface-variant/50">
              Run <code className="font-label-sm text-primary-container">python backend/demo_agent.py</code> to generate agent traces. WARN and ANOMALY verdicts are ingested as knowledge.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6">
            {/* ── Left: Nodes + Edges ── */}
            <div className="flex flex-col gap-6">
              {/* Filter tabs */}
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => setFilter('all')}
                  className={`px-3 py-1.5 rounded-lg font-label-sm text-[11px] border transition-colors ${
                    filter === 'all'
                      ? 'bg-surface-container border-outline-variant/40 text-on-surface'
                      : 'border-transparent text-on-surface-variant/50 hover:text-on-surface-variant'
                  }`}
                >
                  All ({nodes.length})
                </button>
                {nodeTypeGroups.map((type) => {
                  const cfg = NODE_TYPE_CONFIG[type];
                  const count = nodes.filter((n) => n.type === type).length;
                  if (count === 0) return null;
                  return (
                    <button
                      key={type}
                      onClick={() => setFilter(type)}
                      className={`px-3 py-1.5 rounded-lg font-label-sm text-[11px] border transition-colors ${
                        filter === type
                          ? `${cfg.bg} ${cfg.border} ${cfg.text}`
                          : 'border-transparent text-on-surface-variant/50 hover:text-on-surface-variant'
                      }`}
                    >
                      {cfg.label} ({count})
                    </button>
                  );
                })}
              </div>

              {/* Node grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {filteredNodes.map((node) => (
                  <NodeCard
                    key={`${node.type}:${node.id}`}
                    node={node}
                    onClick={(n) => setSelectedNode(selectedNode?.id === n.id && selectedNode?.type === n.type ? null : n)}
                    selected={selectedNode?.id === node.id && selectedNode?.type === node.type}
                  />
                ))}
              </div>

              {/* Edges panel */}
              <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl overflow-hidden">
                <div className="px-5 py-4 border-b border-outline-variant/15 flex items-center justify-between">
                  <h2 className="font-headline-lg text-[15px] text-on-background">
                    {selectedNode ? `Edges for "${selectedNode.id}"` : 'All Causal Edges'}
                  </h2>
                  <span className="font-label-sm text-[10px] text-on-surface-variant/40 uppercase tracking-widest">
                    {(selectedNode ? relatedEdges : edges).length} edges
                  </span>
                </div>
                <div className="max-h-64 overflow-y-auto">
                  {(selectedNode ? relatedEdges : edges).length === 0 ? (
                    <p className="px-5 py-8 text-center font-label-sm text-[11px] text-on-surface-variant/30 uppercase tracking-widest">No edges</p>
                  ) : (
                    (selectedNode ? relatedEdges : edges).map((e, i) => (
                      <EdgeRow key={i} edge={e} />
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* ── Right: Lessons sidebar ── */}
            <div className="flex flex-col gap-4">
              <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl overflow-hidden">
                <div className="px-5 py-4 border-b border-outline-variant/15">
                  <h2 className="font-headline-lg text-[15px] text-on-background">Distilled Lessons</h2>
                  <p className="font-label-sm text-[11px] text-on-surface-variant/50 mt-1">
                    Injected into agent's system prompt to prevent re-running past mistakes
                  </p>
                </div>
                <div className="flex flex-col divide-y divide-outline-variant/10">
                  {lessons.length === 0 ? (
                    <p className="px-5 py-8 text-center font-label-sm text-[11px] text-on-surface-variant/30 uppercase tracking-widest italic">No lessons yet</p>
                  ) : (
                    lessons.map((lesson, i) => (
                      <div key={i} className="px-5 py-4">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-label-sm text-[10px] text-primary-container/70 uppercase tracking-widest">Lesson {i + 1}</span>
                        </div>
                        <p className="font-body-md text-[13px] text-on-surface-variant leading-relaxed">{lesson}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Node detail card */}
              {selectedNode && (() => {
                const cfg = NODE_TYPE_CONFIG[selectedNode.type] || NODE_TYPE_CONFIG.tool;
                return (
                  <div className={`rounded-2xl border p-5 ${cfg.bg} ${cfg.border}`}>
                    <div className="flex items-center gap-2 mb-3">
                      <span className="material-symbols-outlined text-[18px] text-on-surface-variant/50">{cfg.icon}</span>
                      <span className={`font-label-sm text-[10px] uppercase tracking-widest ${cfg.text}`}>{cfg.label} Detail</span>
                    </div>
                    <p className={`font-label-sm text-[13px] font-bold mb-3 break-all ${cfg.text}`}>{selectedNode.id}</p>
                    <div className="flex flex-col gap-1.5 font-label-sm text-[11px]">
                      <div className="flex justify-between text-on-surface-variant/60">
                        <span>Occurrences</span>
                        <span className="font-bold text-on-surface">{selectedNode.count}</span>
                      </div>
                      {selectedNode.first_seen && (
                        <div className="flex justify-between text-on-surface-variant/60">
                          <span>First seen</span>
                          <span>{new Date(selectedNode.first_seen).toLocaleTimeString()}</span>
                        </div>
                      )}
                      {selectedNode.last_seen && (
                        <div className="flex justify-between text-on-surface-variant/60">
                          <span>Last seen</span>
                          <span>{new Date(selectedNode.last_seen).toLocaleTimeString()}</span>
                        </div>
                      )}
                      {selectedNode.last_verdict && (
                        <div className="flex justify-between text-on-surface-variant/60">
                          <span>Last verdict</span>
                          <span className={
                            selectedNode.last_verdict === 'ANOMALY' ? 'text-error'
                            : selectedNode.last_verdict === 'WARN' ? 'text-amber-400'
                            : 'text-primary-container'
                          }>{selectedNode.last_verdict}</span>
                        </div>
                      )}
                      <div className="flex justify-between text-on-surface-variant/60">
                        <span>Connected edges</span>
                        <span>{relatedEdges.length}</span>
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Type legend */}
              <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl p-5">
                <h3 className="font-label-sm text-[11px] uppercase tracking-widest text-on-surface-variant/50 mb-3">Node Types</h3>
                <div className="flex flex-col gap-2.5">
                  {nodeTypeGroups.map((type) => {
                    const cfg = NODE_TYPE_CONFIG[type];
                    return (
                      <div key={type} className="flex items-center gap-2.5">
                        <Dot color={cfg.dot} />
                        <span className="font-label-sm text-[11px] text-on-surface-variant/70">{cfg.label}</span>
                        <span className="ml-auto font-label-sm text-[11px] text-on-surface-variant/30">
                          {nodes.filter((n) => n.type === type).length}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-4 pt-4 border-t border-outline-variant/10">
                  <h3 className="font-label-sm text-[11px] uppercase tracking-widest text-on-surface-variant/50 mb-3">Edge Relations</h3>
                  <div className="flex flex-col gap-2">
                    {Object.entries(RELATION_STYLES).map(([key, val]) => (
                      <div key={key} className="flex items-center gap-2">
                        <span className={`font-label-sm text-[10px] ${val.color}`}>→</span>
                        <span className="font-label-sm text-[11px] text-on-surface-variant/60">{val.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-outline-variant/10 py-6 px-margin-mobile md:px-margin-desktop mt-4">
        <p className="font-label-sm text-[11px] text-on-surface-variant/30 text-center">
          SentinelMind Knowledge Graph · Failure memory across runs · Codecrash FRONTIER 2026
        </p>
      </footer>
    </div>
  );
}
