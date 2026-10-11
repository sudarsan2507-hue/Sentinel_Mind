import { Link } from 'react-router-dom';

/* What it catches, and -- the part that earns trust -- how it knows. Where a
   signal is computed rather than judged, the copy says so. */
const CATCHES = [
  {
    name: 'Invented tools',
    what: 'The agent calls a tool or endpoint that does not exist, usually because the task needs an action it was never given.',
    how: 'Checked against your tool registry. A fact, not the model’s opinion.',
  },
  {
    name: 'Loops',
    what: 'The same call again and again, including the kind where the agent rewords its query each time so nothing matches exactly.',
    how: 'Exact repeats are counted by hashing each call; reworded ones by counting calls per tool. The judge is handed both numbers.',
  },
  {
    name: 'Drift from the goal',
    what: 'Steps that stop serving what the run was asked to do. The run can finish without an error, on the wrong task.',
    how: 'The judge compares each step with the goal you declare for the session.',
  },
  {
    name: 'Swallowed errors',
    what: 'A call fails and the agent carries on as if it had worked, building later steps on data that never came back.',
    how: 'Raised exceptions are recorded by the decorator and always flagged.',
  },
];

const FeaturesSection = () => {
  return (
    <section id="features" className="scroll-mt-20 px-margin-mobile md:px-margin-desktop py-16 md:py-24 border-t border-outline-variant/40">
      <div className="max-w-container-max mx-auto">
        <h2 className="font-headline-lg text-[32px] md:text-[40px] leading-tight font-semibold text-on-background">What it catches</h2>
        <p className="mt-3 max-w-[40rem] text-[17px] leading-relaxed text-on-surface-variant">
          None of these throw an error on their own, so none of them show up in a dashboard of failures.
        </p>
        <dl className="mt-10 grid grid-cols-1 md:grid-cols-2 border-t border-outline-variant/40">
          {CATCHES.map((c, i) => (
            <div
              key={c.name}
              className={`py-7 md:px-8 border-b border-outline-variant/40 ${i % 2 === 0 ? 'md:pl-0 md:border-r' : 'md:pr-0'}`}
            >
              <dt className="font-headline-lg text-[22px] font-semibold text-on-background">{c.name}</dt>
              <dd className="mt-2 text-[16px] leading-relaxed text-on-surface-variant">{c.what}</dd>
              <dd className="mt-3 text-[16px] md:text-[15px] leading-relaxed text-on-background/90">
                <span className="text-primary-container">How it knows: </span>{c.how}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-8 text-[16px] text-on-surface-variant">
          Every one of these is remembered across runs.{' '}
          <Link to="/graph" className="text-on-background underline underline-offset-4 decoration-outline-variant hover:decoration-primary-container">
            See what this agent has got wrong so far
          </Link>
          .
        </p>
      </div>
    </section>
  );
};

export default FeaturesSection;
