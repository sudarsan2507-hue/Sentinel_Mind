import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useSocket } from '../hooks/useSocket';

/* ─── Why each failure mode happens ───
   The graph records THAT an agent failed. This is the general reasoning for
   WHY agents fail that way -- true of LLM agents broadly, not just this one --
   so a reader can check the pattern against agents they have run themselves.
   The page pairs it with this store's own evidence: counts, spread across
   tools and runs, and the judge's actual words. Text here is deliberately
   free of statistics we have not measured. */
const FAILURE_REASONING = {
  hallucinated_tool: {
    title: 'Hallucinated tool',
    what: 'The agent called a tool or endpoint that does not exist in its registry.',
    why: 'A language model continues patterns. When a task implies an action — issue a refund, notify the customer — and no tool provides it, the most plausible next token is a plausible-looking tool name. The model writes the tool it expects to exist rather than admitting the gap.',
    impact: 'Best case the call fails noisily. Worst case the invented name matches a real endpoint and performs an action nobody approved.',
    remedy: 'Make the gap explicit: the agent should say the action needs a human. The distilled lesson below tells it exactly that, by capability rather than by URL, because the invented path changes every run while the missing capability does not.',
  },
  infinite_loop: {
    title: 'Loop',
    what: 'The same tool called again and again — with identical or reworded input — without the task moving forward.',
    why: 'An agent has no built-in sense of “I already tried this”. Each step is chosen from the context; if the last result did not resolve the uncertainty, the same action is still the most likely next one. Rewording the query hides the loop from exact-match checks, which is why SentinelMind also counts calls per tool.',
    impact: 'Burns time, tokens and rate limits, and only ends when a step ceiling cuts it off.',
    remedy: 'Call once or twice, then act on what came back or answer. The distilled lesson names the tool that loops.',
  },
  goal_drift: {
    title: 'Goal drift',
    what: 'Steps stop serving the goal the run was given.',
    why: 'In a long context the original instruction is one message among many; the most recent tool output steers the next step more strongly than the goal does. The agent follows the trail of its own results.',
    impact: 'The run can finish without a single error — on the wrong task. Nothing in the logs flags it.',
    remedy: 'Judge every step against the declared session goal, which is what the meta-agent does. There is no deterministic remedy to inject, so no lesson is distilled for it yet.',
  },
  exception: {
    title: 'Exception',
    what: 'The step raised an error — a permission denial, timeout or upstream failure.',
    why: 'Often a downstream effect of another failure: an invented endpoint answers 403. Agents also tend to swallow the error and carry on, because the next step is still generated whether or not the last one worked.',
    impact: 'If swallowed, later steps build on data that was never returned.',
    remedy: 'Surface the error in the final answer instead of retrying blindly. Look at which other failure mode the same tools show — that is usually the cause.',
  },
  inefficient_reasoning: {
    title: 'Inefficient reasoning',
    what: 'The step worked, but something was off: slow, oddly shaped input, or output only loosely tied to the request.',
    why: 'This is the catch-all for warnings with no hard signal behind them. Individually minor; repeated on one tool it usually precedes a sharper failure.',
    impact: 'Wasted latency and cost; an early signal worth watching.',
    remedy: 'Watch the trend on the tools listed. No lesson is injected for it.',
  },
};

const RELATION_LABEL = { exhibits: 'hit', requires: 'reached for', missing_in: 'missing in' };

/* Which distilled lessons speak to which failure mode. The backend writes only
   two kinds -- missing capabilities and loops -- so the mapping is exact. */
function lessonsFor(failureId, lessons) {
  if (failureId === 'hallucinated_tool') return lessons.filter((l) => /^You have NO tool|NOT in your tool registry/.test(l));
  if (failureId === 'infinite_loop') return lessons.filter((l) => /flagged as a loop/.test(l));
  return [];
}

/* failure -> tools that hit it -> capabilities they reached for -> goals they were missing in */
function chainFor(failureId, edges) {
  const hits = edges.filter((e) => e.relation === 'exhibits' && e.dst_id === failureId);
  const tools = new Set(hits.map((e) => e.src_id));
  const reaches = edges.filter((e) => e.relation === 'requires' && tools.has(e.src_id));
  const caps = new Set(reaches.map((e) => e.dst_id));
  const gaps = edges.filter((e) => e.relation === 'missing_in' && caps.has(e.src_id));
  return { hits, reaches, gaps, tools: [...tools], caps: [...caps], goals: [...new Set(gaps.map((e) => e.dst_id))] };
}

const short = (s, n = 34) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

/* ─── Graph ───
   Layered left to right in the order you read the chain, instead of a physics
   simulation: same input, same picture, every time. */
const LEVEL = { failure_mode: 0, tool: 1, capability: 2, goal: 3 };
const STYLE = {
  failure_mode: { background: '#2a1416', border: '#f87171' },
  tool:         { background: '#141917', border: '#3d5c48' },
  capability:   { background: '#221b0e', border: '#c08a2e' },
  goal:         { background: '#18181b', border: '#52525b' },
};

function ChainGraph({ nodes, edges, onPickFailure }) {
  const hostRef = useRef(null);
  const netRef = useRef(null);
  const pickRef = useRef(onPickFailure);
  useEffect(() => { pickRef.current = onPickFailure; }, [onPickFailure]);

  const tallest = Math.max(1, ...Object.values(
    nodes.reduce((acc, n) => ({ ...acc, [n.type]: (acc[n.type] || 0) + 1 }), {}),
  ));
  const height = Math.min(620, Math.max(220, tallest * 40 + 40));

  useEffect(() => {
    let cancelled = false;
    import('vis-network/standalone').then(({ Network, DataSet }) => {
      if (cancelled || !hostRef.current) return;
      netRef.current?.destroy();
      const net = new Network(
        hostRef.current,
        {
          nodes: new DataSet(nodes.map((n) => ({
            id: `${n.type}:${n.id}`,
            label: short(n.type === 'tool' ? n.id.replace(/^internal_api:/, 'api ') : n.id.replace(/_/g, ' ')),
            title: `${n.id} · ×${n.count}`,
            level: LEVEL[n.type],
            color: { ...STYLE[n.type], highlight: STYLE[n.type], hover: STYLE[n.type] },
            font: n.type === 'failure_mode' ? { bold: true } : {},
          }))),
          edges: new DataSet(edges.map((e, i) => ({
            id: i,
            from: `${e.src_type}:${e.src_id}`,
            to: `${e.dst_type}:${e.dst_id}`,
            // Thickness carries the count; per-edge labels turned the graph into noise.
            width: 1 + Math.log2(e.count),
            title: `${e.src_id} ${RELATION_LABEL[e.relation] || e.relation} ${e.dst_id} ×${e.count}`,
          }))),
        },
        {
          layout: { hierarchical: { direction: 'LR', levelSeparation: 260, nodeSpacing: 40, sortMethod: 'directed' } },
          physics: false,
          nodes: {
            shape: 'box',
            margin: { top: 7, bottom: 7, left: 10, right: 10 },
            borderWidth: 1,
            shapeProperties: { borderRadius: 4 },
            font: { color: '#e4e4e7', size: 12, face: 'Inter, system-ui, sans-serif' },
          },
          edges: {
            color: { color: '#3f3f46', highlight: '#a1a1aa', hover: '#a1a1aa' },
            width: 1,
            arrows: { to: { enabled: false } },
            smooth: { type: 'cubicBezier', forceDirection: 'horizontal', roundness: 0.5 },
          },
          interaction: { hover: true, dragNodes: false, zoomView: false, dragView: false, tooltipDelay: 150 },
        },
      );
      net.once('afterDrawing', () => {
        net.fit({ animation: false });
        if (net.getScale() > 1.1) net.moveTo({ scale: 1.1 }); // a 3-node chain should not fill the screen
      });
      net.on('click', ({ nodes: hit }) => {
        if (hit[0]?.startsWith('failure_mode:')) pickRef.current(hit[0].slice('failure_mode:'.length));
      });
      netRef.current = net;
    });
    return () => { cancelled = true; };
  }, [nodes, edges]);

  useEffect(() => () => { netRef.current?.destroy(); netRef.current = null; }, []);

  return <div ref={hostRef} data-testid="knowledge-network" style={{ height }} className="w-full" />;
}

/* ─── Phone view of the same chain ───
   A four-column graph cannot be read at 390px -- vis just shrinks it. On small
   screens the chain is the same facts as a list, in the same order. */
function ChainList({ chain }) {
  const cols = [
    ['Tools that hit it', [...chain.hits].sort((a, b) => b.count - a.count).map((e) => [e.src_id, e.count])],
    ['Capability they reached for', chain.caps.map((c) => [c.replace(/_/g, ' '), chain.reaches.filter((e) => e.dst_id === c).reduce((n, e) => n + e.count, 0)])],
    ['Goal it was missing in', chain.goals.map((g) => [g, null])],
  ];
  return (
    <div className="px-5 py-4 flex flex-col gap-4">
      {cols.filter(([, items]) => items.length).map(([label, items]) => (
        <div key={label}>
          <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-2">{label}</h3>
          <ul className="flex flex-col gap-1.5">
            {items.map(([name, n]) => (
              <li key={name} className="flex justify-between gap-3 font-body-md text-[16px] md:text-[14px] text-on-surface">
                <span className="break-all">{name}</span>
                {n != null && <span className="tabular-nums text-on-surface-variant">×{n}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/* Phones get the list, so they should not download the 690 KB graph library
   just to hide it. Tracks the breakpoint the layout uses (md = 768px). */
function useWide() {
  const query = '(min-width: 768px)';
  const [wide, setWide] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = (e) => setWide(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return wide;
}

/* ─── Section shell ─── */
function Panel({ title, aside, children, className = '' }) {
  return (
    <section className={`bg-surface-container-low border border-outline-variant/20 rounded-xl overflow-hidden ${className}`}>
      <div className="px-5 py-3.5 border-b border-outline-variant/15 flex items-center justify-between gap-4">
        <h2 className="font-headline-lg text-[17px] text-on-background">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

/* ─── Main Knowledge Graph Page ─── */
export default function KnowledgeGraphPage() {
  const { connected, on } = useSocket();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [picked, setPicked] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [lastLearnedTs, setLastLearnedTs] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);
  const wide = useWide();

  useEffect(() => {
    document.title = 'Failure memory · SentinelMind';
  }, []);

  /* A button that succeeds silently is indistinguishable from a broken one.
     Every action reports: busy while in flight, a timestamp on success, and the
     server's own message on failure.

     `announce` exists so the mount effect can fetch WITHOUT setting state
     synchronously in the effect body -- that cascades renders, and React's lint
     rule flags it. State set inside the promise callbacks is async and fine;
     only the busy/error reset up front was the problem. */
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

  /* What the Refresh button calls: the same fetch, but it reports it is working. */
  const refresh = useCallback(() => load(true), [load]);

  /* Clear sent no body, so the backend rejected it with 400 and the page
     refreshed unchanged -- a silent no-op that looked like a dead button.
     The confirm flag is required precisely because this is destructive. */
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

  /* Initial load. `false` skips the busy/error reset, so nothing is set
     synchronously here -- every setState in load() happens inside a promise
     callback, which is the subscribe-to-an-external-system pattern the rule
     exists to allow. The rule cannot see through the guard, so it is silenced
     with the reason rather than contorting correct code to satisfy it. */
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { load(false); }, [load]);

  /* Auto-refresh when backend learns something new */
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

  /* Derived data */
  const lessons = useMemo(() => data?.lessons ?? [], [data]);
  const summary = data?.summary ?? {};
  const allNodes = useMemo(() => data?.nodes ?? [], [data]);
  const allEdges = useMemo(() => data?.edges ?? [], [data]);

  const failures = useMemo(
    () => allNodes.filter((n) => n.type === 'failure_mode').sort((a, b) => b.count - a.count),
    [allNodes],
  );
  const totalFailures = failures.reduce((s, f) => s + f.count, 0);
  // Never open on the full hairball: default to the most frequent failure.
  const focusId = picked && failures.some((f) => f.id === picked) ? picked : failures[0]?.id;
  const focus = failures.find((f) => f.id === focusId);

  const chain = useMemo(() => (focusId ? chainFor(focusId, allEdges) : null), [focusId, allEdges]);

  const graph = useMemo(() => {
    if (showAll || !chain) return { nodes: allNodes, edges: allEdges };
    const keep = new Set([
      `failure_mode:${focusId}`,
      ...chain.tools.map((t) => `tool:${t}`),
      ...chain.caps.map((c) => `capability:${c}`),
      ...chain.goals.map((g) => `goal:${g}`),
    ]);
    return {
      nodes: allNodes.filter((n) => keep.has(`${n.type}:${n.id}`)),
      edges: [...chain.hits, ...chain.reaches, ...chain.gaps],
    };
  }, [showAll, chain, allNodes, allEdges, focusId]);

  const pickFailure = useCallback((id) => { setPicked(id); setShowAll(false); }, []);

  const reasoning = focus ? FAILURE_REASONING[focus.id] : null;
  const focusLessons = focus ? lessonsFor(focus.id, lessons) : [];
  const runsTotal = summary.runs ?? 0;
  const topTools = chain ? [...chain.hits].sort((a, b) => b.count - a.count).slice(0, 3) : [];

  return (
    <div className="min-h-screen bg-[#050505] text-on-background font-body-md">
      {/* ── Top bar ── */}
      <header className="sticky top-0 z-50 flex flex-wrap items-center justify-between gap-3 px-margin-mobile md:px-margin-desktop py-4 bg-surface-container-lowest border-b border-outline-variant/20 backdrop-blur-md">
        <div className="flex items-center gap-6">
          <Link to="/" className="inline-flex min-h-11 items-center font-headline-lg text-[20px] font-extrabold text-on-background tracking-tighter hover:text-primary transition-colors">
            SentinelMind
          </Link>
          <span className="hidden md:block font-label-sm text-[12px] text-on-surface-variant">/ Knowledge Graph</span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {lastLearnedTs && (
            <span className="font-label-sm text-[12px] text-primary-container animate-pulse">● New learning detected</span>
          )}
          <div className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-primary-container shadow-[0_0_6px_rgba(0,255,102,0.5)]' : 'bg-on-surface-variant/30'}`} />
            <span className="font-label-sm text-[12px] text-on-surface-variant">{connected ? 'Live' : 'Disconnected'}</span>
          </div>
          {error && (
            <span className="font-label-sm text-[12px] text-error max-w-[280px] truncate" title={error}>⚠ {error}</span>
          )}
          {!error && lastUpdated && (
            <span className="font-label-sm text-[12px] text-on-surface-variant">updated {lastUpdated.toLocaleTimeString()}</span>
          )}
          <button
            onClick={() => refresh()}
            disabled={busy}
            className="inline-flex min-h-11 items-center px-3 bg-surface-container-high/50 border border-outline-variant/20 rounded-lg font-label-sm text-[12px] text-on-surface hover:bg-surface-variant transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busy ? 'Refreshing…' : 'Refresh'}
          </button>
          <button
            onClick={clearMemory}
            disabled={busy}
            className="inline-flex min-h-11 items-center px-3 bg-error/10 border border-error/20 rounded-lg font-label-sm text-[12px] text-error hover:bg-error/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Clear Memory
          </button>
          <Link to="/dashboard" className="inline-flex min-h-11 items-center px-3 border border-outline-variant/30 rounded-lg font-label-sm text-[12px] text-on-surface-variant hover:text-primary hover:border-primary-container/30 transition-colors">
            ← Dashboard
          </Link>
        </div>
      </header>

      <main className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-8 flex flex-col gap-6">
        <div>
          <h1 className="font-headline-lg text-[24px] text-on-background">How this agent fails, and why</h1>
          <p className="font-body-md text-[16px] md:text-[14px] text-on-surface-variant mt-1 max-w-[760px]">
            Every WARN and ANOMALY verdict is remembered here across {runsTotal} run{runsTotal === 1 ? '' : 's'}.
            Pick a failure mode to see the tools that hit it, what they were reaching for, the reasoning behind
            the pattern, and the lesson fed back to the agent.
          </p>
        </div>

        {loading ? (
          // Holds the page's height while loading, so the footer does not jump
          // when the data lands (Lighthouse measured a 0.91 layout shift).
          <p className="min-h-[100vh] py-32 text-center text-[16px] md:text-[15px] text-on-surface-variant">Loading failure memory…</p>
        ) : failures.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-32 gap-3 text-on-surface-variant">
            <p className="font-label-sm text-[13px]">No failures remembered yet</p>
            <p className="font-body-md text-[16px] md:text-[14px] text-center max-w-[400px] text-on-surface-variant">
              Run <code className="font-label-sm text-primary-container">python backend/real_agent.py</code> or{' '}
              <code className="font-label-sm text-primary-container">demo_agent.py</code>. WARN and ANOMALY verdicts are stored here.
            </p>
          </div>
        ) : (
          <>
            {/* ── Failure modes: the general view ── */}
            <div role="tablist" aria-label="Failure modes" className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {failures.map((f) => {
                const active = f.id === focusId && !showAll;
                const share = totalFailures ? Math.round((f.count / totalFailures) * 100) : 0;
                const toolCount = allEdges.filter((e) => e.relation === 'exhibits' && e.dst_id === f.id).length;
                return (
                  <button
                    key={f.id}
                    role="tab"
                    aria-selected={active}
                    onClick={() => pickFailure(f.id)}
                    className={`text-left p-4 rounded-lg border transition-colors ${
                      active
                        ? 'bg-error/10 border-error/50'
                        : 'bg-surface-container-low border-outline-variant/20 hover:border-outline-variant/50'
                    }`}
                  >
                    <span className="block font-body-md text-[16px] md:text-[14px] text-on-background">{FAILURE_REASONING[f.id]?.title ?? f.id}</span>
                    <span className="block mt-2 font-headline-lg text-[22px] tabular-nums text-on-background">{f.count}</span>
                    <span className="block font-label-sm text-[12px] text-on-surface-variant">
                      {share}% of failures · {toolCount} tool{toolCount === 1 ? '' : 's'}
                    </span>
                    <span className="mt-3 block h-1 rounded bg-outline-variant/20 overflow-hidden">
                      <span className="block h-full bg-error/70" style={{ width: `${share}%` }} />
                    </span>
                  </button>
                );
              })}
            </div>

            <div className="flex flex-col gap-6">
              {/* ── Chain graph ── */}
              <Panel
                title={showAll ? 'All remembered failures' : `${reasoning?.title ?? focusId}: where it comes from`}
                aside={
                  <button
                    onClick={() => setShowAll((v) => !v)}
                    className="inline-flex min-h-11 items-center px-3 border border-outline-variant/30 rounded-lg font-label-sm text-[12px] text-on-surface-variant hover:text-on-surface transition-colors"
                  >
                    {showAll ? 'Focus on one failure' : 'Show everything'}
                  </button>
                }
              >
                {!showAll && chain && <div className="md:hidden"><ChainList chain={chain} /></div>}
                <div className={`${showAll ? 'flex' : 'hidden md:flex'} flex-wrap gap-x-5 gap-y-1 px-5 pt-4 font-label-sm text-[12px] text-on-surface-variant`}>
                  {[['failure_mode', 'Failure'], ['tool', 'Tool that hit it'], ['capability', 'Capability it reached for'], ['goal', 'Goal it was missing in']].map(([t, label]) => (
                    <span key={t} className="flex items-center gap-2">
                      <span className="w-3 h-3 rounded-sm border" style={{ background: STYLE[t].background, borderColor: STYLE[t].border }} />
                      {label}
                    </span>
                  ))}
                  <span className="text-on-surface-variant">read left to right · thicker line = more often</span>
                </div>
                {(wide || showAll) && (
                  <div className={showAll ? '' : 'hidden md:block'}>
                    <ChainGraph nodes={graph.nodes} edges={graph.edges} onPickFailure={pickFailure} />
                  </div>
                )}
                {!showAll && chain && chain.caps.length === 0 && (
                  <p className="px-5 pb-4 font-body-md text-[16px] md:text-[13px] text-on-surface-variant">
                    No capability gap behind this one: these tools exist, so the failure is in how they were used, not in what was missing.
                  </p>
                )}
                {showAll && (
                  <p className="px-5 pb-4 font-body-md text-[16px] md:text-[13px] text-on-surface-variant">Click any red failure node to focus on it.</p>
                )}
              </Panel>

              {/* ── Reasoning ── */}
              {focus && reasoning && (
                <Panel title="Reasoning" aside={<span className="font-label-sm text-[12px] text-error">{reasoning.title}</span>}>
                  <div className="px-5 py-5 grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-5 font-body-md text-[16px] md:text-[14px] leading-relaxed">
                    <div>
                      <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-1">What it is</h3>
                      <p className="text-on-surface">{reasoning.what}</p>
                    </div>
                    <div>
                      <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-1">Why agents do this</h3>
                      <p className="text-on-surface-variant">{reasoning.why}</p>
                    </div>
                    <div>
                      <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-1">Why it matters</h3>
                      <p className="text-on-surface-variant">{reasoning.impact}</p>
                    </div>
                    <div>
                      <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-1">How widespread it is here</h3>
                      <p className="text-on-surface-variant">
                        {focus.count} occurrence{focus.count === 1 ? '' : 's'} across {chain.tools.length} tool{chain.tools.length === 1 ? '' : 's'}
                        {/* seen_in_runs only exists for runs recorded after it was added, so it is a floor, not "N of all runs". */}
                        {focus.seen_in_runs ? `, seen in ${focus.seen_in_runs.length} run${focus.seen_in_runs.length === 1 ? '' : 's'} since per-run tracking began` : ''}
                        {topTools.length > 0 && <> — most often <span className="text-on-surface">{topTools.map((t) => `${t.src_id} (×${t.count})`).join(', ')}</span></>}.
                      </p>
                    </div>
                    <div>
                      <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-1">What the judge said</h3>
                      {focus.evidence?.length ? (
                        <ul className="flex flex-col gap-2">
                          {[...focus.evidence].reverse().map((ev, i) => (
                            <li key={i} className="border-l-2 border-outline-variant/40 pl-3">
                              <span className="font-label-sm text-[12px] text-on-surface-variant">{ev.status} · {ev.tool}</span>
                              <p className="text-on-surface-variant text-[16px] md:text-[13px]">“{ev.explanation}”</p>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-on-surface-variant text-[16px] md:text-[13px]">Explanations are kept for failures recorded from now on; this one predates that.</p>
                      )}
                    </div>
                    <div>
                      <h3 className="font-label-sm text-[12px] text-on-surface-variant mb-1">What fixes it</h3>
                      <p className="text-on-surface-variant">{reasoning.remedy}</p>
                    </div>
                    {focusLessons.length > 0 && (
                      <div className="lg:col-span-2 rounded-lg bg-primary-container/5 border border-primary-container/20 p-3">
                        <h3 className="font-label-sm text-[12px] text-primary-container mb-1">Lesson fed back to the agent</h3>
                        {focusLessons.map((l, i) => <p key={i} className="text-on-surface text-[16px] md:text-[13px] mt-1">{l}</p>)}
                      </div>
                    )}
                  </div>
                </Panel>
              )}
            </div>

            {/* ── Everything the agent is told ── */}
            <Panel
              title="Lessons injected into the agent"
              aside={<span className="font-label-sm text-[12px] text-on-surface-variant">real_agent.py --learn</span>}
            >
              {lessons.length === 0 ? (
                <p className="px-5 py-6 font-body-md text-[16px] md:text-[13px] text-on-surface-variant">No lessons yet.</p>
              ) : (
                <ol className="divide-y divide-outline-variant/10">
                  {lessons.map((l, i) => (
                    <li key={i} className="px-5 py-3 flex gap-4 font-body-md text-[16px] md:text-[14px] text-on-surface-variant leading-relaxed">
                      <span className="font-label-sm text-[12px] text-primary-container pt-0.5">{i + 1}</span>
                      <span>{l}</span>
                    </li>
                  ))}
                </ol>
              )}
            </Panel>

            {/* ── Raw data, for anyone checking the claims above ── */}
            <details className="bg-surface-container-low border border-outline-variant/20 rounded-xl">
              <summary className="px-5 py-3.5 cursor-pointer font-headline-lg text-[17px] text-on-background">
                Raw graph data <span className="font-label-sm text-[12px] text-on-surface-variant">· {summary.nodes ?? 0} nodes, {summary.edges ?? 0} edges</span>
              </summary>
              <div className="max-h-80 overflow-auto border-t border-outline-variant/15">
                <table className="w-full font-label-sm text-[12px] text-left">
                  <thead className="text-on-surface-variant uppercase text-[12px] tracking-widest">
                    <tr><th className="px-5 py-2">From</th><th className="py-2">Relation</th><th className="py-2">To</th><th className="px-5 py-2 text-right">Count</th></tr>
                  </thead>
                  <tbody>
                    {allEdges.map((e, i) => (
                      <tr key={i} className="border-t border-outline-variant/10 text-on-surface-variant">
                        <td className="px-5 py-2 break-all">{e.src_id}</td>
                        <td className="py-2 text-on-surface-variant">{e.relation}</td>
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

        <footer className="pt-4 text-center font-label-sm text-[12px] text-on-surface-variant">
          Failure memory across runs · retrieval-augmented prompting, not training
        </footer>
      </main>
    </div>
  );
}
