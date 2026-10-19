import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import TopNavBar from '../components/TopNavBar';
import Footer from '../components/Footer';
import { useSocket } from '../hooks/useSocket';
import { REPO } from '../lib/links';

const START = `git clone ${REPO}.git
cd Sentinel_Mind
pip install -r requirements.txt
# put GROQ_API_KEY=... in .env, then:
python backend/app.py`;

const MARK = `import sys
sys.path.insert(0, "path/to/Sentinel_Mind/backend")

from decorator import monitor

@monitor(tool_name="lookup_booking")
def lookup_booking(ref): ...

@monitor(tool_name="rebook", risky=True)          # checked before it runs
def rebook(ref, flight): ...

@monitor(tool_name="charge_card", approval=True)  # waits for you to approve
def charge_card(ref, amount_usd): ...`;

const CONNECT = `import sentinel

sentinel.connect(
    "http://127.0.0.1:5000",
    goal="Rebook the passenger onto the next flight at no extra cost",
    tools=[lookup_booking, rebook, charge_card],
    guard=True,   # stop bad steps; leave out to only watch
)`;

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex min-h-11 items-center rounded-md border border-outline-variant/60 px-3 text-[14px] text-on-background hover:bg-surface-container-high active:bg-surface-container-high transition-colors"
    >
      <span aria-live="polite">{copied ? 'Copied' : 'Copy'}</span>
    </button>
  );
}

function Code({ text, label }) {
  return (
    <div className="mt-4 overflow-hidden rounded-lg border border-outline-variant/40 bg-[#050505]">
      <div className="flex items-center justify-between gap-3 border-b border-outline-variant/30 pl-4 pr-1.5 py-1">
        <span className="text-[13px] text-on-surface-variant">{label}</span>
        <CopyButton text={text} />
      </div>
      <pre className="overflow-x-auto p-4 font-label-sm text-[13px] leading-6 text-on-background"><code>{text}</code></pre>
    </div>
  );
}

function Step({ n, title, done, children }) {
  return (
    <li className="relative min-w-0 pl-14">
      <span
        aria-hidden="true"
        className={`absolute left-0 top-0 grid h-10 w-10 place-items-center rounded-full border font-headline-lg text-[17px] font-bold transition-colors ${
          done ? 'border-primary-container bg-primary-container text-[#00210a]' : 'border-outline-variant text-on-surface-variant'
        }`}
      >
        {done ? '✓' : n}
      </span>
      <h2 className="font-headline-lg text-[21px] font-semibold leading-10 text-on-background">
        {title}
        {done && <span className="sr-only"> (done)</span>}
      </h2>
      <div className="mt-1 max-w-[68ch] text-[16px] leading-7 text-on-surface-variant">{children}</div>
    </li>
  );
}

function Check({ ok, title, detail }) {
  return (
    <li className="flex gap-3 py-3">
      <span
        aria-hidden="true"
        className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${ok ? 'bg-primary-container shadow-[0_0_10px_#00ff66]' : 'border border-on-surface-variant/60'}`}
      />
      <span className="min-w-0">
        <span className={`block text-[15px] ${ok ? 'text-on-background' : 'text-on-surface-variant'}`}>
          {title}
          <span className="sr-only">{ok ? ': done' : ': waiting'}</span>
        </span>
        <span className="mt-0.5 block break-words text-[13px] leading-5 text-on-surface-variant">{detail}</span>
      </span>
    </li>
  );
}

export default function Connect() {
  const { connected, on } = useSocket();
  const [health, setHealth] = useState(null);
  const [session, setSession] = useState({ goal: null, registered: [] });
  const [lastStep, setLastStep] = useState(null);
  const [demo, setDemo] = useState(null);
  const [demoError, setDemoError] = useState('');

  const loadSession = useCallback(() => {
    fetch('/session').then((r) => r.json()).then(setSession).catch(() => {});
  }, []);
  const loadDemo = useCallback(() => {
    fetch('/demo/status').then((r) => r.json()).then(setDemo).catch(() => {});
  }, []);

  useEffect(() => {
    document.title = 'Connect your agent · SentinelMind';
  }, []);

  // Server health: checked now, then every 5s so starting the server ticks step 1.
  useEffect(() => {
    const check = () => fetch('/health').then((r) => r.json()).then(setHealth).catch(() => setHealth(null));
    check();
    const id = setInterval(check, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    loadSession();
    loadDemo();
    fetch('/audit').then((r) => r.json()).then((a) => {
      const last = a.entries?.[a.entries.length - 1];
      if (last) setLastStep({ tool: last.event.tool, status: last.status });
    }).catch(() => {});
  }, [loadSession, loadDemo]);

  useEffect(() => {
    const offs = [
      on('tools', loadSession),
      on('goal', (d) => setSession((s) => ({ ...s, goal: d.goal }))),
      on('verdict', (e) => setLastStep({ tool: e.event.tool, status: e.status })),
      on('cleared', () => setLastStep(null)),
      on('demo', setDemo),
    ];
    return () => offs.forEach((off) => off?.());
  }, [on, loadSession]);

  // While an example runs, watch for it to finish.
  useEffect(() => {
    if (!demo?.running) return undefined;
    const id = setInterval(loadDemo, 2000);
    return () => clearInterval(id);
  }, [demo?.running, loadDemo]);

  const runDemo = (name) => {
    setDemoError('');
    fetch('/demo/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ demo: name }),
    })
      .then(async (r) => {
        const body = await r.json();
        if (!r.ok) setDemoError(body.error || 'The example could not be started.');
        setDemo(body.demos ? body : null);
      })
      .catch(() => setDemoError('The server did not answer. Is python backend/app.py running?'));
  };

  const serverUp = health?.status === 'ok';
  const registered = session.registered || [];
  const toolsDone = registered.length > 0;
  const goalDone = Boolean(session.goal);
  const stepDone = Boolean(lastStep);
  const demoName = demo?.name && demo.demos?.[demo.name];

  return (
    <div className="min-h-screen bg-[#050505]">
      <TopNavBar />
      <main className="mx-auto max-w-container-max px-margin-mobile pb-20 pt-28 md:px-margin-desktop">
        <h1 className="max-w-[20ch] font-headline-lg text-[34px] font-extrabold leading-[1.1] tracking-tight text-on-background md:text-[48px]">
          Connect your agent
        </h1>
        <p className="mt-4 max-w-[60ch] text-[17px] leading-7 text-on-surface-variant">
          Put <code className="font-label-sm text-[15px] text-on-background">@monitor</code> on your agent&apos;s tools and
          call <code className="font-label-sm text-[15px] text-on-background">sentinel.connect()</code> once. From then on every
          step it takes is judged live, and with guard mode the dangerous ones are stopped before they run.
        </p>

        <div className="mt-12 grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-14">
          <aside aria-labelledby="live-check" className="lg:order-2">
            <div className="rounded-xl border border-outline-variant/40 bg-surface-container-low p-5 lg:sticky lg:top-24">
              <div className="flex items-center justify-between gap-3">
                <h2 id="live-check" className="font-headline-lg text-[17px] font-semibold text-on-background">Live check</h2>
                <span className="text-[13px] text-on-surface-variant">{connected ? 'listening' : 'reconnecting'}</span>
              </div>
              <p className="mt-1 text-[13px] leading-5 text-on-surface-variant">Ticks off as your agent connects. Nothing to refresh.</p>
              <ul className="mt-2 divide-y divide-outline-variant/30">
                <Check ok={serverUp} title="Server running" detail={serverUp ? `Judge: ${health.model}` : 'Start it with python backend/app.py'} />
                <Check
                  ok={toolsDone}
                  title="Your tools registered"
                  detail={toolsDone ? registered.slice(0, 6).join(', ') + (registered.length > 6 ? ` and ${registered.length - 6} more` : '') : 'connect() registers them'}
                />
                <Check ok={goalDone} title="Goal set" detail={goalDone ? session.goal : 'Pass goal= to connect()'} />
                <Check
                  ok={stepDone}
                  title="First step judged"
                  detail={stepDone ? `${lastStep.tool}: ${lastStep.status}` : 'Run your agent'}
                />
              </ul>
              {stepDone && (
                <Link
                  to="/dashboard"
                  className="mt-4 flex min-h-11 items-center justify-center rounded-md bg-primary-container px-4 text-[15px] font-semibold text-[#00210a] hover:brightness-110 active:brightness-95 transition"
                >
                  Watch it on the dashboard
                </Link>
              )}
            </div>
          </aside>

          <ol className="flex min-w-0 flex-col gap-12 lg:order-1">
            <Step n={1} title="Start SentinelMind" done={serverUp}>
              <p>
                {serverUp
                  ? 'It is running: this page is served by it. Skip to step 2.'
                  : 'Clone the project, add a free Groq API key, and start the server.'}
              </p>
              {!serverUp && <Code label="Terminal" text={START} />}
            </Step>

            <Step n={2} title="Mark your tools" done={toolsDone}>
              <p>
                Add <code className="font-label-sm text-[14px] text-on-background">@monitor</code> to each function your agent can
                call. Nothing else in them changes. Mark tools that move money or change records as{' '}
                <code className="font-label-sm text-[14px] text-on-background">risky</code>, and ones a person must sign off as{' '}
                <code className="font-label-sm text-[14px] text-on-background">approval</code>.
              </p>
              <Code label="your_agent.py" text={MARK} />
            </Step>

            <Step n={3} title="Connect once, at start-up" done={toolsDone && goalDone}>
              <p>
                This checks the server is up, registers your tools, sets the goal the judge measures each step against, and
                starts sending steps. If the server is down it raises an error instead of quietly watching nothing.
              </p>
              <Code label="your_agent.py" text={CONNECT} />
            </Step>

            <Step n={4} title="Run your agent" done={stepDone}>
              <p>Run it the way you always do. The live check fills in as its first steps arrive.</p>

              <div className="mt-6 rounded-xl border border-outline-variant/40 p-5">
                <h3 className="text-[16px] font-semibold text-on-background">No agent to hand? Run an example</h3>
                <p className="mt-1 text-[15px] leading-6">
                  Both run on this machine and report here like any other agent. Each starts a fresh run on the dashboard,
                  and the guarded one will ask you to approve or deny an action there.
                </p>
                <div className="mt-4 flex flex-wrap gap-3">
                  <button
                    type="button"
                    disabled={demo?.running}
                    onClick={() => runDemo('travel')}
                    className="inline-flex min-h-11 items-center rounded-md bg-primary-container px-4 text-[15px] font-semibold text-[#00210a] hover:brightness-110 active:brightness-95 disabled:opacity-50 transition"
                  >
                    Run the travel agent
                  </button>
                  <button
                    type="button"
                    disabled={demo?.running}
                    onClick={() => runDemo('refund')}
                    className="inline-flex min-h-11 items-center rounded-md border border-outline-variant/60 px-4 text-[15px] text-on-background hover:bg-surface-container-high active:bg-surface-container-high disabled:opacity-50 transition-colors"
                  >
                    Run the rogue refund agent, guarded
                  </button>
                </div>
                <p role="status" className="mt-3 min-h-6 text-[14px]">
                  {demoError && <span className="text-error">{demoError}</span>}
                  {!demoError && demo?.running && <span className="text-on-background">Running: {demoName}. </span>}
                  {!demoError && demo && !demo.running && demo.name && (
                    <span>
                      {demo.exit_code === 0 ? 'Finished' : `Stopped with exit code ${demo.exit_code}`}: {demoName}.{' '}
                    </span>
                  )}
                  {!demoError && demo?.name && (
                    <Link to="/dashboard" className="inline-flex min-h-11 items-center text-primary-container underline underline-offset-4">
                      Open the dashboard
                    </Link>
                  )}
                </p>
              </div>
            </Step>
          </ol>
        </div>
      </main>
      <Footer />
    </div>
  );
}
