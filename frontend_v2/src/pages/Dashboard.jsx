import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { useSocket } from '../hooks/useSocket';
import {
  StatusMark, StatusLegend, MixBar, Sparkline, Tile,
  RunTimeline, LatencyChart, ToolBreakdown, Confidence,
} from '../components/dashboard/viz';
import { STATUS, quantile, fmtS } from '../components/dashboard/status';

const headerButton = 'inline-flex min-h-11 items-center rounded-md border border-outline-variant/50 px-3 text-[14px] text-on-background hover:bg-surface-container-high active:bg-surface-container-high transition-colors';

function Panel({ title, aside, children, className = '', bodyClass = 'p-5' }) {
  return (
    <section className={`rounded-xl border border-outline-variant/40 bg-surface-container-low overflow-hidden ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-5 pt-4">
        <h2 className="font-headline-lg text-[17px] text-on-background">{title}</h2>
        {aside}
      </div>
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

/* Longest run of consecutive calls to the same tool -- the visible face of a
   loop. Computed, like the server's repeat signal, not inferred. */
function longestStreak(steps) {
  let best = { tool: null, n: 0 };
  let cur = { tool: null, n: 0 };
  steps.forEach((s) => {
    cur = s.tool === cur.tool ? { tool: s.tool, n: cur.n + 1 } : { tool: s.tool, n: 1 };
    if (cur.n > best.n) best = cur;
  });
  return best;
}


// Why a step was stopped, in words.
const RULE_LABEL = {
  unregistered: 'not a real tool',
  repeat: 'repeat call',
  judge: 'judged unsafe before it ran',
  unverified: 'could not be verified',
  unreachable: 'guard unreachable',
  approval_denied: 'human said no',
  approval_timeout: 'no human approval',
  circuit_breaker: 'run halted',
};

const fromEntry = (e) => ({
  id: e.event.id,
  tool: e.event.tool,
  status: e.status,
  text: e.verdict.explanation,
  latency: e.verdict.latency_ms,
  duration: e.event.duration_ms,
  confidence: e.verdict.confidence,
  degraded: e.verdict.degraded,
  replayed: e.verdict.replayed,
  rule: e.verdict.rule,
  prechecked: e.verdict.prechecked,
});

export default function Dashboard() {
  const { connected, on } = useSocket();

  // steps: every traced step in run order, PENDING until its verdict lands.
  const [steps, setSteps] = useState([]);
  const [goal, setGoal] = useState('');
  const [model, setModel] = useState('');
  const [selected, setSelected] = useState(null);
  const [ready, setReady] = useState(false);
  // View options. Layout is remembered per browser; storage can be unavailable
  // (private mode), so reads and writes are guarded and the default still works.
  const [layout, setLayout] = useState(() => {
    try { return localStorage.getItem('sm.dashLayout') || 'split'; } catch { return 'split'; }
  });
  const [expandAll, setExpandAll] = useState(false);
  // Replay: re-plays the finished run step by step in every view. Client-side
  // only -- the verdicts are already here, nothing is re-judged or re-sent.
  const [replayN, setReplayN] = useState(null);
  // Guard mode: a halted run and actions waiting for a human.
  const [halt, setHalt] = useState(null);
  const [approvals, setApprovals] = useState([]);
  const [deciding, setDeciding] = useState(null);
  const feedRef = useRef(null);

  useEffect(() => {
    document.title = 'Live dashboard · SentinelMind';
  }, []);

  const reset = useCallback(() => { setSteps([]); setSelected(null); setHalt(null); setApprovals([]); }, []);

  useEffect(() => {
    const offs = [
      on('trace', (event) => setSteps((prev) => (
        prev.some((s) => s.id === event.id)
          ? prev
          : [...prev, { id: event.id, tool: event.tool, status: 'PENDING', duration: event.duration_ms }]
      ))),
      on('verdict', (entry) => setSteps((prev) => {
        const next = fromEntry(entry);
        return prev.some((s) => s.id === next.id)
          ? prev.map((s) => (s.id === next.id ? next : s))
          : [...prev, next];
      })),
      on('goal', (d) => { setGoal(d.goal); reset(); }),
      on('cleared', reset),
      on('halted', (d) => setHalt(d)),
      on('approval_request', (a) => setApprovals((prev) => (prev.some((p) => p.id === a.id) ? prev : [...prev, a]))),
      on('approval_resolved', (r) => setApprovals((prev) => prev.filter((p) => p.id !== r.id))),
    ];
    return () => offs.forEach((off) => off && off());
  }, [on, reset]);

  /* Rehydrate on mount */
  useEffect(() => {
    // The judge model is configuration, not copy -- ask the server which one is live.
    fetch('/health').then((r) => r.json()).then((d) => setModel(d.model || '')).catch(() => {});
    // Draw the page once the session and its verdicts are in. Drawing it empty
    // first and filling in moved every tile below the goal box (layout shift
    // 0.08 on phones); both answers take a few milliseconds locally.
    fetch('/guard/state').then((r) => r.json()).then((g) => {
      if (g.halted) setHalt({ reason: g.halt_reason, strikes: g.strikes });
      if (g.pending_approvals?.length) setApprovals(g.pending_approvals);
    }).catch(() => {});
    Promise.allSettled([
      fetch('/session').then((r) => r.json()).then((d) => setGoal(d.goal || '')),
      fetch('/audit').then((r) => r.json()).then((d) => {
        if (d.entries?.length) setSteps(d.entries.map(fromEntry));
      }),
    ]).then(() => setReady(true));
  }, []);

  const chooseLayout = (next) => {
    setLayout(next);
    try { localStorage.setItem('sm.dashLayout', next); } catch { /* storage unavailable: still switches */ }
  };

  useEffect(() => {
    if (replayN == null) return undefined;
    if (replayN >= steps.length) {
      const done = setTimeout(() => setReplayN(null), 1200);
      return () => clearTimeout(done);
    }
    const t = setTimeout(() => setReplayN((n) => n + 1), 550);
    return () => clearTimeout(t);
  }, [replayN, steps.length]);

  const decide = (id, decision) => {
    setDeciding(id);
    fetch(`/guard/approval/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision }),
    })
      .then(() => setApprovals((prev) => prev.filter((p) => p.id !== id)))
      .finally(() => setDeciding(null));
  };

  /* Selecting a step anywhere scrolls the feed to it. */
  useEffect(() => {
    if (!selected) return;
    feedRef.current?.querySelector(`[data-step="${CSS.escape(selected)}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [selected]);

  /* Derived -- from what is visible, so a replay drives every view at once. */
  const visible = useMemo(() => (replayN == null ? steps : steps.slice(0, replayN)), [steps, replayN]);
  const judged = visible.filter((s) => s.status !== 'PENDING');
  const counts = judged.reduce((a, s) => ({ ...a, [s.status]: (a[s.status] || 0) + 1 }), { OK: 0, WARN: 0, ANOMALY: 0, BLOCKED: 0 });
  const blockedSteps = judged.filter((s) => s.status === 'BLOCKED');
  const blockedByRule = blockedSteps.reduce((a, s) => ({ ...a, [s.rule]: (a[s.rule] || 0) + 1 }), {});
  const latencies = judged.filter((s) => s.status !== 'BLOCKED').map((s) => s.latency).filter(Number.isFinite);
  const p50 = quantile(latencies, 0.5);
  const p95 = quantile(latencies, 0.95);
  const anomalyRate = judged.length ? Math.round((counts.ANOMALY / judged.length) * 100) : null;
  const streak = useMemo(() => longestStreak(visible), [visible]);
  const pending = visible.length - judged.length;
  const runDone = steps.length > 1 && steps.every((s) => s.status !== 'PENDING');
  const latestAnomaly = [...judged].reverse().find((s) => s.status === 'ANOMALY');
  const stepNo = useMemo(() => new Map(steps.map((s, i) => [s.id, i + 1])), [steps]);
  const feed = [...judged].reverse();

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
              <span className="relative flex w-2 h-2" aria-hidden="true">
                {connected && <span className="absolute inset-0 rounded-full bg-primary-container opacity-60 animate-ping" />}
                <span className={`relative w-2 h-2 rounded-full ${connected ? 'bg-primary-container' : 'bg-on-surface-variant/50'}`} />
              </span>
              {connected ? 'Live' : 'Disconnected'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <a href="/audit/export" download className={headerButton}>Export log</a>
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

      {!ready ? <main className="min-h-screen" aria-busy="true" /> : (
      <main className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop py-6 md:py-8 flex flex-col gap-5">
        {/* ── Guard mode: halted run, and actions waiting for a human ── */}
        {halt && (
          <div role="alert" className="anomaly-banner rounded-xl border border-error/60 bg-error/10 px-5 py-4">
            <p className="flex items-center gap-2 text-[15px] font-semibold text-error">
              <StatusMark status="BLOCKED" size={12} />
              SentinelMind stopped this run{halt.strikes ? ` after ${halt.strikes} problems` : ''}
            </p>
            <p className="mt-1 text-[15px] leading-snug text-on-background">{halt.reason}</p>
          </div>
        )}
        {approvals.map((a) => (
          <div key={a.id} role="alert" className="anomaly-banner rounded-xl border border-[#60a5fa]/60 bg-[#60a5fa]/10 px-5 py-4 flex flex-wrap items-center gap-x-6 gap-y-3">
            <div className="min-w-0 flex-1">
              <p className="text-[15px] font-semibold text-on-background">Waiting for your approval</p>
              <p className="mt-1 text-[15px] text-on-surface-variant">
                The agent wants to run <code className="font-label-sm text-[13px] text-on-background">{a.tool}</code>
                {a.input?.kwargs && Object.keys(a.input.kwargs).length > 0 && (
                  <code className="font-label-sm text-[13px] text-on-surface-variant"> {JSON.stringify(a.input.kwargs)}</code>
                )}. It will not run unless you approve.
              </p>
            </div>
            <div className="flex gap-2">
              <button type="button" disabled={deciding === a.id} onClick={() => decide(a.id, 'deny')}
                className="inline-flex min-h-11 items-center rounded-md border border-outline-variant/60 px-4 text-[14px] text-on-background hover:bg-surface-container-high disabled:opacity-50">
                Deny
              </button>
              <button type="button" disabled={deciding === a.id} onClick={() => decide(a.id, 'approve')}
                className="inline-flex min-h-11 items-center rounded-md bg-[#60a5fa] px-4 text-[14px] font-semibold text-[#06152b] hover:brightness-110 disabled:opacity-50">
                Approve
              </button>
            </div>
          </div>
        ))}

        {/* ── Goal + latest anomaly ── */}
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.2fr] gap-5">
          <div className={`rounded-xl border px-5 py-4 ${goal ? 'border-outline-variant/40 bg-surface-container-low' : 'border-amber-500/30 bg-amber-500/5'}`}>
            <p className="text-[13px] text-on-surface-variant">Session goal</p>
            <p className={`mt-1 text-[16px] leading-snug ${goal ? 'text-on-background' : 'text-amber-300'}`}>
              {goal || 'Not declared, so drift from the goal cannot be judged for this run.'}
            </p>
          </div>
          {latestAnomaly ? (
            <button
              type="button"
              onClick={() => setSelected(latestAnomaly.id)}
              className="anomaly-banner group text-left rounded-xl border border-error/40 bg-error/[0.06] px-5 py-4 hover:bg-error/10 transition-colors"
            >
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-error">
                <StatusMark status="ANOMALY" size={11} />
                Latest anomaly · step {stepNo.get(latestAnomaly.id)}
                <span className="font-label-sm text-[12px] text-on-background break-all">{latestAnomaly.tool}</span>
                <span className="ml-auto text-on-surface-variant group-hover:text-on-background transition-colors">Show in feed</span>
              </span>
              <span className="mt-1 block text-[15px] leading-snug text-on-surface-variant line-clamp-2">{latestAnomaly.text}</span>
            </button>
          ) : (
            <div className="rounded-xl border border-outline-variant/40 bg-surface-container-low px-5 py-4">
              <p className="text-[13px] text-on-surface-variant">Latest anomaly</p>
              <p className="mt-1 text-[16px] text-on-background">None yet.</p>
            </div>
          )}
        </div>

        {/* ── KPI tiles ── */}
        <div className={`grid grid-cols-2 gap-3 md:gap-5 ${counts.BLOCKED ? 'lg:grid-cols-5' : 'lg:grid-cols-4'}`}>
          <Tile label="Steps judged" value={judged.length} sub={pending ? `${pending} being judged` : `${counts.OK} OK · ${counts.WARN} warn · ${counts.ANOMALY} anomaly${counts.BLOCKED ? ` · ${counts.BLOCKED} blocked` : ''}`}>
            <MixBar counts={counts} />
          </Tile>
          <Tile
            label="Anomaly rate"
            value={anomalyRate == null ? '—' : `${anomalyRate}%`}
            tone={anomalyRate > 30 ? 'text-error' : anomalyRate > 0 ? 'text-amber-300' : 'text-primary-container'}
            sub={anomalyRate == null ? 'no verdicts yet' : `${counts.ANOMALY} of ${judged.length} steps`}
          />
          <Tile label="Verdict latency" value={fmtS(p50)} sub={latencies.length ? `median · p95 ${fmtS(p95)}` : 'median'}>
            <Sparkline values={latencies} />
          </Tile>
          <Tile
            label="Longest repeat"
            value={streak.n > 1 ? `×${streak.n}` : '—'}
            tone={streak.n >= 3 ? 'text-error' : streak.n === 2 ? 'text-amber-300' : 'text-on-background'}
            sub={streak.n > 1 ? <span className="font-label-sm text-[12px] break-all">{streak.tool} in a row</span> : 'no tool called twice in a row'}
          />
          {counts.BLOCKED > 0 && (
            <Tile
              label="Stopped before running"
              value={counts.BLOCKED}
              tone="text-[#60a5fa]"
              sub={Object.entries(blockedByRule).map(([r, n]) => `${n} ${RULE_LABEL[r] || r}`).join(' · ')}
            />
          )}
        </div>

        {/* ── View controls ── */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div role="radiogroup" aria-label="Layout" className="inline-flex rounded-lg border border-outline-variant/50 p-1 bg-surface-container-low">
            {[['split', 'Split'], ['stacked', 'Stacked']].map(([v, label]) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={layout === v}
                onClick={() => chooseLayout(v)}
                className={`min-h-11 md:min-h-9 rounded-md px-4 text-[14px] transition-colors ${
                  layout === v ? 'bg-surface-container-high text-on-background' : 'text-on-surface-variant hover:text-on-background'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {replayN != null ? (
            <div className="flex items-center gap-3 text-[14px]">
              <span className="tabular-nums text-on-surface-variant" aria-live="polite">Replaying step {Math.min(replayN, steps.length)} of {steps.length}</span>
              <button type="button" onClick={() => setReplayN(null)} className={headerButton}>Stop</button>
            </div>
          ) : (
            <button
              type="button"
              disabled={!runDone}
              onClick={() => { setSelected(null); setReplayN(1); }}
              title={runDone ? 'Play this run back step by step' : 'Available once every step has a verdict'}
              className={`${headerButton} disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              Replay run
            </button>
          )}
        </div>

        {/* ── Timeline + charts | feed ── */}
        <div className={`grid grid-cols-1 gap-5 items-start ${layout === 'split' ? 'lg:grid-cols-[1.45fr_1fr]' : ''}`}>
          <div className="flex flex-col gap-5 min-w-0">
            <Panel
              title="Run timeline"
              aside={<StatusLegend statuses={counts.BLOCKED ? ['OK', 'WARN', 'ANOMALY', 'BLOCKED', 'PENDING'] : ['OK', 'WARN', 'ANOMALY', 'PENDING']} />}
              bodyClass="px-3 pb-4 pt-2"
            >
              <p className="px-2 pb-2 text-[13px] text-on-surface-variant">One lane per tool, one column per step. A lane lighting up again and again is a loop.</p>
              <RunTimeline steps={visible} selected={selected} onSelect={setSelected} />
            </Panel>
            <Panel title="Verdict latency per step" aside={<span className="text-[13px] text-on-surface-variant">time from trace to verdict; colour is the verdict</span>}>
              <LatencyChart steps={visible} selected={selected} onSelect={setSelected} />
            </Panel>
            <Panel title="Verdicts by tool" aside={<StatusLegend statuses={counts.BLOCKED ? ['OK', 'WARN', 'ANOMALY', 'BLOCKED'] : ['OK', 'WARN', 'ANOMALY']} />}>
              <ToolBreakdown
                steps={visible}
                onPickTool={(tool) => {
                  const last = [...judged].reverse().find((s) => s.tool === tool);
                  if (last) setSelected(last.id);
                }}
              />
            </Panel>
          </div>

          {/* Verdict feed */}
          <Panel
            title="Verdict feed"
            aside={(
              <button
                type="button"
                onClick={() => setExpandAll((v) => !v)}
                aria-pressed={expandAll}
                className="min-h-11 md:min-h-0 text-[13px] text-on-surface-variant underline underline-offset-4 decoration-outline-variant hover:text-on-background"
              >
                {expandAll ? 'Collapse all' : 'Expand all'}
              </button>
            )}
            className={layout === 'split' ? 'lg:sticky lg:top-20' : ''}
            bodyClass="pt-3"
          >
            <ol ref={feedRef} className={`min-h-[320px] overflow-y-auto ${layout === 'split' ? 'max-h-[560px] lg:max-h-[calc(100vh-11rem)]' : 'max-h-[640px]'}  overscroll-contain px-3 pb-3 flex flex-col gap-2`}>
              {feed.length === 0 && (
                <li className="px-3 py-10 text-center text-[15px] text-on-surface-variant">
                  Run <code className="font-label-sm text-primary-container">python backend/real_agent.py</code> and each verdict lands here.
                </li>
              )}
              {feed.map((s) => {
                const sel = selected === s.id;
                // Compact by default: one line per verdict. Selecting a step (here
                // or in any chart) or "Expand all" shows the full reasoning.
                const open = sel || expandAll;
                return (
                  <li key={s.id} data-step={s.id} className="feed-item">
                    <button
                      type="button"
                      onClick={() => setSelected(sel ? null : s.id)}
                      aria-expanded={open}
                      className={`w-full text-left rounded-lg border px-4 ${open ? 'py-3' : 'py-2.5'} transition-colors ${
                        sel ? 'border-on-surface-variant bg-surface-container-high' : 'border-outline-variant/30 hover:border-outline-variant/70'
                      }`}
                      style={{ boxShadow: `inset 3px 0 0 ${STATUS[s.status].color}` }}
                    >
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-on-background">
                          <StatusMark status={s.status} size={11} />
                          {STATUS[s.status].label}
                        </span>
                        <span className="font-label-sm text-[12px] text-primary-container break-all">{s.tool}</span>
                        <span className="ml-auto text-[12px] tabular-nums text-on-surface-variant">step {stepNo.get(s.id)} · {fmtS(s.latency)}</span>
                      </span>
                      <span className={`mt-1 text-[15px] md:text-[14px] leading-snug ${open ? 'block' : 'line-clamp-1'} ${s.degraded ? 'italic text-on-surface-variant' : 'text-on-surface-variant'}`}>
                        {s.text}
                      </span>
                      {open && (
                        <span className="mt-2 flex items-center gap-3">
                          <Confidence value={s.confidence} />
                          {s.degraded && <span className="text-[12px] text-amber-300">judge unavailable</span>}
                          {s.replayed && <span className="text-[12px] text-on-surface-variant">replayed</span>}
                          {s.status === 'BLOCKED' && <span className="text-[12px] text-[#93c5fd]">never ran · {RULE_LABEL[s.rule] || s.rule}</span>}
                          {s.prechecked && <span className="text-[12px] text-on-surface-variant">checked before it ran</span>}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ol>
          </Panel>
        </div>

        {/* ── Failure memory ── */}
        <Link
          to="/graph"
          className="group flex items-center justify-between gap-4 rounded-xl border border-primary-container/25 bg-surface-container-low p-5 hover:border-primary-container/50 hover:bg-primary-container/[0.04] transition-colors"
        >
          <span>
            <span className="block font-headline-lg text-[17px] text-on-background">Failure memory</span>
            <span className="block mt-0.5 text-[15px] text-on-surface-variant">How this agent has failed across runs, why, and the lessons fed back to it.</span>
          </span>
          <ArrowRight aria-hidden="true" className="text-primary-container group-hover:translate-x-1 transition-transform w-6 h-6 shrink-0" />
        </Link>
      </main>
      )}

      <footer className="border-t border-outline-variant/20 py-6 px-margin-mobile md:px-margin-desktop mt-4">
        <p className="text-[13px] text-on-surface-variant text-center">
          Judge: {model || '…'} via Groq
        </p>
      </footer>
    </div>
  );
}
