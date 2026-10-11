import { Link } from 'react-router-dom';

const VisualCTA = () => {
  return (
    <section className="px-margin-mobile md:px-margin-desktop py-16 md:py-24 border-t border-outline-variant/40">
      <div className="max-w-container-max mx-auto flex flex-col md:flex-row md:items-end md:justify-between gap-8">
        <div className="max-w-[36rem]">
          <h2 className="font-headline-lg text-[32px] md:text-[40px] leading-tight font-semibold text-on-background">
            Watch it judge a real agent.
          </h2>
          <p className="mt-3 text-[17px] leading-relaxed text-on-surface-variant">
            Start the server, run <code className="font-label-sm text-[15px] text-on-background">python backend/real_agent.py</code>,
            and the dashboard fills in as each step is judged.
          </p>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <Link
            to="/dashboard"
            className="inline-flex min-h-12 items-center justify-center rounded-md bg-primary-container px-6 font-semibold text-[16px] text-[#00210a] hover:brightness-110 active:brightness-95 transition"
          >
            Open the live dashboard
          </Link>
          <Link
            to="/graph"
            className="inline-flex min-h-12 items-center justify-center rounded-md border border-outline-variant px-6 font-semibold text-[16px] text-on-background hover:border-on-surface-variant active:bg-surface-container-low transition"
          >
            See the failure memory
          </Link>
        </div>
      </div>
    </section>
  );
};

export default VisualCTA;
