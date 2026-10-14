/* The right path for this run: the steps a correct run takes, which are done,
   which come next, which the facts ruled out -- and the route the agent
   actually took, detours and steering included. */

const ROUTE_STYLE = {
  on_path: { label: 'on path', color: '#00e55b' },
  off_path: { label: 'detour', color: '#8a9389' },
  steered: { label: 'steered back', color: '#60a5fa' },
  held: { label: 'held for you', color: '#fbbf24' },
  failed: { label: 'failed', color: '#f87171' },
};

function StepBadge({ state }) {
  const styles = {
    done: 'bg-primary-container/15 text-primary-container border-primary-container/40',
    next: 'bg-[#60a5fa]/15 text-[#93c5fd] border-[#60a5fa]/50',
    ruled: 'bg-error/10 text-error border-error/40',
    later: 'bg-transparent text-on-surface-variant border-outline-variant/50',
  };
  const text = { done: 'Done', next: 'Next', ruled: 'Not allowed', later: 'Later' };
  return <span className={`shrink-0 rounded border px-2 py-0.5 text-[12px] ${styles[state]}`}>{text[state]}</span>;
}

export default function PathPanel({ state, onAutomate, busy }) {
  if (!state?.active) return null;
  const { path, visits = {}, next = [], ruled_out: ruled = {}, route = [], automate, finished, facts = {} } = state;

  const stepState = (n) => {
    if (visits[n.id]) return 'done';
    if (ruled[n.id]) return 'ruled';
    if (next.includes(n.id)) return 'next';
    return 'later';
  };

  return (
    <section className="rounded-xl border border-outline-variant/40 bg-surface-container-low p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-headline-lg text-[17px] text-on-background">The right path</h2>
          <p className="mt-0.5 text-[14px] text-on-surface-variant">{path.title}{finished ? ' · every required step done' : ''}</p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={automate}
          disabled={busy}
          onClick={() => onAutomate(!automate)}
          className={`inline-flex min-h-11 items-center gap-2 rounded-md border px-3 text-[14px] transition-colors disabled:opacity-50 ${
            automate ? 'border-primary-container/60 bg-primary-container/10 text-primary-container' : 'border-outline-variant/60 text-on-background hover:bg-surface-container-high'
          }`}
        >
          <span aria-hidden="true" className={`h-2 w-2 rounded-full ${automate ? 'bg-primary-container' : 'bg-on-surface-variant/60'}`} />
          Autopilot {automate ? 'on' : 'off'}
        </button>
      </div>

      <ol className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
        {path.nodes.map((n) => {
          const st = stepState(n);
          return (
            <li key={n.id} className={`rounded-lg border px-3 py-2.5 ${st === 'next' ? 'border-[#60a5fa]/50' : 'border-outline-variant/30'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className={`text-[15px] ${st === 'ruled' ? 'line-through text-on-surface-variant' : 'text-on-background'}`}>
                  {n.label}{n.optional ? <span className="text-on-surface-variant"> · optional</span> : null}
                </span>
                <StepBadge state={st} />
              </div>
              <code className="font-label-sm text-[12px] text-on-surface-variant">{n.tools.join(', ')}</code>
              {st === 'ruled' && <p className="mt-1 text-[13px] leading-snug text-error/90">{ruled[n.id]}</p>}
              {n.learned && <p className="mt-1 text-[12px] text-primary-container">added from an approved run</p>}
            </li>
          );
        })}
      </ol>

      {Object.keys(facts).length > 0 && (
        <p className="mt-3 text-[13px] text-on-surface-variant">
          Facts seen: {Object.entries(facts).map(([k, v]) => `${k.replace(/_/g, ' ')} = ${v}`).join(' · ')}
        </p>
      )}

      {route.length > 0 && (
        <div className="mt-4">
          <p className="text-[13px] text-on-surface-variant">Route taken</p>
          <ol className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {route.map((r, i) => {
              const style = ROUTE_STYLE[r.kind] || ROUTE_STYLE.off_path;
              return (
                <li key={i} className="flex items-center gap-1.5">
                  {i > 0 && <span aria-hidden="true" className="text-on-surface-variant/60">›</span>}
                  <span
                    className="rounded border px-2 py-0.5 font-label-sm text-[12px] text-on-background"
                    style={{ borderColor: `${style.color}80`, boxShadow: `inset 3px 0 0 ${style.color}` }}
                    title={style.label}
                  >
                    {r.tool.replace(/^internal_api:/, 'api ')}
                    <span className="sr-only"> ({style.label})</span>
                  </span>
                </li>
              );
            })}
          </ol>
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-on-surface-variant">
            {Object.entries(ROUTE_STYLE).map(([k, v]) => (
              <span key={k} className="inline-flex items-center gap-1.5">
                <span aria-hidden="true" className="h-2.5 w-1 rounded-sm" style={{ background: v.color }} />{v.label}
              </span>
            ))}
          </p>
        </div>
      )}
    </section>
  );
}
