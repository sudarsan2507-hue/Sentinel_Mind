/* Measured, with the caveat attached to each number. Sources: evals/results/
   (2026-10-11) and the test suite. If a number here changes, change it there first. */
const RESULTS = [
  {
    value: '9 of 9',
    label: 'labelled cases judged correctly, on each of three runs',
    note: 'Nine cases is a demonstration, not a statistic. Judge: gpt-oss-120b, reasoning effort medium.',
  },
  {
    value: '1.5–2.0 s',
    label: 'slowest verdict on the labelled set',
    note: 'On live runs, Groq’s free-tier token limit queues verdicts; mid-run they take 10–20 s.',
  },
  {
    value: '172',
    label: 'automated tests, run offline with no API key',
    note: 'They prove the plumbing. The labelled set is what tests the judgement.',
  },
];

const Results = () => {
  return (
    <section id="results" className="scroll-mt-20 px-margin-mobile md:px-margin-desktop py-16 md:py-24 border-t border-outline-variant/40">
      <div className="max-w-container-max mx-auto">
        <h2 className="font-headline-lg text-[32px] md:text-[40px] leading-tight font-semibold text-on-background">Measured, not claimed</h2>
        <dl className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-10 md:gap-8">
          {RESULTS.map((r) => (
            <div key={r.value}>
              <dt className="font-display-lg text-[40px] leading-none font-bold tabular-nums text-on-background">{r.value}</dt>
              <dd className="mt-3 text-[17px] leading-snug text-on-background">{r.label}</dd>
              <dd className="mt-2 text-[16px] md:text-[15px] leading-relaxed text-on-surface-variant">{r.note}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
};

export default Results;
