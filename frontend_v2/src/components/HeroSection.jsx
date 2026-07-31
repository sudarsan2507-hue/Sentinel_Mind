
const HeroSection = () => {
  return (
    <header className="relative pt-32 pb-20 overflow-hidden flex flex-col items-center text-center">
      <div className="px-margin-mobile md:px-margin-desktop max-w-container-max mx-auto relative z-10">
        <h1 className="font-headline-lg-mobile md:font-display-lg text-headline-lg-mobile md:text-display-lg text-on-background mb-6 leading-tight">
          Full Visibility Into Every <br className="hidden md:block" /> Agent Run in Production
        </h1>
        <p className="font-body-md text-body-md text-on-surface-variant max-w-[700px] mx-auto mb-10 leading-relaxed">
          An AI agent that watches other AI agents in real time, detects anomalies, <br className="hidden md:block" /> and explains <span className="text-primary">WHY</span> they happened with cryptographic precision.
        </p>
        <div className="flex flex-col sm:flex-row gap-4 justify-center">
          <button className="px-10 py-4 bg-white text-black font-label-sm text-label-sm rounded-full font-bold transition-all hover:shadow-[0_0_15px_rgba(0,229,91,0.3)]">
            <span className="flex items-center justify-center gap-2">Get Started </span>
          </button>
          <button className="px-10 py-4 bg-surface-container-high/50 border border-outline-variant/20 text-on-background font-label-sm text-label-sm rounded-full font-bold hover:bg-surface-variant transition-all">Documentation</button>
        </div>
      </div>
    </header>
  );
};

export default HeroSection;
