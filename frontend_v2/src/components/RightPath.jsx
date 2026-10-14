import { useCallback, useEffect, useState } from 'react';

/* The other half of the memory: not how the agent fails, but what a correct
   run looks like -- and the steps people approved during runs, waiting to be
   accepted into the path. Shown on the failure memory page. */
export default function RightPath() {
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = useCallback(() => fetch('/path/state').then((r) => r.json()).then(setState).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);

  if (!state?.active) {
    return (
      <section className="rounded-xl border border-outline-variant/40 bg-surface-container-low p-5">
        <h2 className="font-headline-lg text-[19px] text-on-background">The right path</h2>
        <p className="mt-2 text-[15px] text-on-surface-variant">
          No right path is active for the current goal. Paths live in <code className="font-label-sm">backend/paths/</code>
          {state?.available?.length ? <> (available: {state.available.join(', ')})</> : null}; one is chosen when the session goal matches it.
        </p>
      </section>
    );
  }

  const { path, proposals = [] } = state;
  const resolve = (id, accept) => {
    setBusy(id);
    fetch(`/path/proposals/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accept }),
    }).then(load).finally(() => setBusy(null));
  };
  const requires = (n) => n.requires.map((r) => path.nodes.find((x) => x.id === r)?.label).filter(Boolean);

  return (
    <section className="rounded-xl border border-primary-container/30 bg-surface-container-low p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-headline-lg text-[19px] text-on-background">The right path</h2>
        <span className="text-[13px] text-on-surface-variant">{path.title}</span>
      </div>
      <p className="mt-1 max-w-[760px] text-[15px] text-on-surface-variant">{path.description}</p>

      <ol className="mt-4 flex flex-col gap-2">
        {path.nodes.map((n) => (
          <li key={n.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border border-outline-variant/30 px-3 py-2">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-primary-container" />
            <span className="text-[15px] text-on-background">{n.label}</span>
            <code className="font-label-sm text-[12px] text-on-surface-variant">{n.tools.join(', ')}</code>
            {requires(n).length > 0 && <span className="text-[13px] text-on-surface-variant">after {requires(n).join(' + ').toLowerCase()}</span>}
            {n.when && <span className="text-[13px] text-amber-300">only if {n.when.replace(/_/g, ' ')}</span>}
            {n.optional && <span className="text-[13px] text-on-surface-variant">optional</span>}
            {n.learned && <span className="text-[13px] text-primary-container">added from an approved run</span>}
          </li>
        ))}
      </ol>

      <h3 className="mt-5 text-[15px] font-semibold text-on-background">Proposed from your decisions</h3>
      {proposals.length === 0 ? (
        <p className="mt-1 text-[14px] text-on-surface-variant">
          None yet. When you let an off-path step continue, it appears here; accept it and it becomes part of the path.
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {proposals.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-outline-variant/40 px-3 py-2">
              <span className="text-[15px] text-on-background">
                Allow <code className="font-label-sm text-[13px]">{p.tool}</code>
                <span className="text-on-surface-variant"> · let through {p.count} time{p.count === 1 ? '' : 's'}</span>
              </span>
              <span className="flex gap-2">
                <button type="button" disabled={busy === p.id} onClick={() => resolve(p.id, false)}
                  className="inline-flex min-h-11 items-center rounded-md border border-outline-variant/60 px-3 text-[14px] text-on-background hover:bg-surface-container-high disabled:opacity-50">
                  Reject
                </button>
                <button type="button" disabled={busy === p.id} onClick={() => resolve(p.id, true)}
                  className="inline-flex min-h-11 items-center rounded-md bg-primary-container px-3 text-[14px] font-semibold text-[#00210a] hover:brightness-110 disabled:opacity-50">
                  Accept into the path
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
