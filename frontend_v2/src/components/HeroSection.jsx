import { Link } from 'react-router-dom';
import { DOCS } from '../lib/links';
import LiveTrace from './LiveTrace';

const HeroSection = () => {
  return (
    <header className="pt-28 md:pt-36 pb-16 md:pb-24 px-margin-mobile md:px-margin-desktop">
      <div className="max-w-container-max mx-auto grid grid-cols-1 lg:grid-cols-[1fr_1.05fr] gap-12 lg:gap-16 items-start">
        <div className="lg:pt-6">
          <h1 className="font-display-lg text-[40px] leading-[1.08] md:text-[60px] md:leading-[1.04] font-bold tracking-[-0.03em] text-on-background">
            Catch your AI agent’s mistakes while it is still running.
          </h1>
          <p className="mt-6 max-w-[34rem] text-[18px] leading-[1.6] text-on-surface-variant">
            SentinelMind judges every tool call your agent makes and says, in plain English, what went
            wrong: a tool it invented, a loop it is stuck in, a step that has wandered off the goal.
            Logs tell you afterwards. This tells you now.
          </p>
          <div className="mt-9 flex flex-col sm:flex-row gap-3">
            <Link
              to="/dashboard"
              className="inline-flex min-h-12 items-center justify-center rounded-md bg-primary-container px-6 font-semibold text-[16px] text-[#00210a] hover:brightness-110 active:brightness-95 transition"
            >
              Open the live dashboard
            </Link>
            <a
              href={DOCS}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-12 items-center justify-center rounded-md border border-outline-variant px-6 font-semibold text-[16px] text-on-background hover:border-on-surface-variant active:bg-surface-container-low transition"
            >
              Read the docs
            </a>
          </div>
        </div>
        <LiveTrace />
      </div>
    </header>
  );
};

export default HeroSection;
