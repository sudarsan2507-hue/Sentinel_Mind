import { ARCHITECTURE } from '../lib/links';

/* A real sequence, so it is numbered. The code is the actual integration from
   backend/demo_agent.py -- one decorator, nothing else. */
const STEPS = [
  {
    title: 'Wrap a tool',
    body: 'The decorator records the input, output, any error and the duration. Your function returns exactly what it did before, and raises exactly what it did before.',
  },
  {
    title: 'Send the trace',
    body: 'Each call is posted to the SentinelMind server, which answers immediately. Judging happens on a separate worker, so watching never slows the agent down.',
  },
  {
    title: 'Judge it in context',
    body: 'A second model sees the step, the goal of the session and the last eight steps, and returns OK, WARN or ANOMALY with a reason and a confidence.',
  },
  {
    title: 'Remember it',
    body: 'Every WARN and ANOMALY goes into a knowledge graph. On the next run its lessons are added to the agent’s prompt. That is retrieval, not training: no weights change.',
  },
];

const HowItWorks = () => {
  return (
    <section id="how-it-works" className="scroll-mt-20 px-margin-mobile md:px-margin-desktop py-16 md:py-24 border-t border-outline-variant/40">
      <div className="max-w-container-max mx-auto grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16">
        <div>
          <h2 className="font-headline-lg text-[32px] md:text-[40px] leading-tight font-semibold text-on-background">How it works</h2>
          <ol className="mt-8 flex flex-col gap-7">
            {STEPS.map((s, i) => (
              <li key={s.title} className="grid grid-cols-[2rem_1fr] gap-3">
                <span className="font-label-sm text-[15px] text-primary-container tabular-nums pt-1">{i + 1}</span>
                <div>
                  <h3 className="font-headline-lg text-[20px] font-semibold text-on-background">{s.title}</h3>
                  <p className="mt-1.5 text-[16px] leading-relaxed text-on-surface-variant">{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
          <a
            href={ARCHITECTURE}
            target="_blank"
            rel="noreferrer"
            className="mt-8 inline-flex min-h-11 items-center text-[16px] text-on-background underline underline-offset-4 decoration-outline-variant hover:decoration-primary-container"
          >
            Read the full architecture
          </a>
        </div>
        <div className="lg:pt-16">
          <pre className="overflow-x-auto rounded-lg border border-outline-variant/50 bg-surface-container-low p-5 font-label-sm text-[14px] leading-relaxed text-on-background">
            <code>{`from decorator import monitor

@monitor(tool_name="search_docs")
def search_docs(query: str) -> str:
    return docs.lookup(query)`}</code>
          </pre>
          <p className="mt-3 text-[16px] md:text-[15px] text-on-surface-variant">
            The whole integration. No framework to adopt, no SDK, no config file.
          </p>
        </div>
      </div>
    </section>
  );
};

export default HowItWorks;
