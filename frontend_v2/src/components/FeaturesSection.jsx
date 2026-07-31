
const FeaturesSection = () => {
  return (
    <section className="py-24 px-margin-mobile md:px-margin-desktop max-w-container-max mx-auto">
      <div className="text-center mb-16 transition-all duration-700 opacity-100 translate-y-0">
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-gutter transition-all duration-700 opacity-100 translate-y-0">
        <div className="p-8 bg-surface-container-lowest border border-outline-variant/20 rounded-xl glow-hover transition-all flex flex-col h-full group">
          <h3 className="font-headline-lg text-[24px] text-on-background mb-4 leading-snug">Autonomous Anomaly Detection</h3>
          <p className="font-body-md text-on-surface-variant mb-auto">Flag runs with unusual latency, cost spikes, or quality drops before they impact your users.</p>
          <div className="mt-8 flex items-center gap-2 text-on-surface-variant group-hover:text-primary transition-colors">
            <div className="w-8 h-8 rounded-lg bg-surface-container-high border border-outline-variant/30 flex items-center justify-center">
              <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
            </div>
            <span className="font-label-sm">Docs</span>
          </div>
        </div>
        
        <div className="p-8 bg-surface-container-lowest border border-outline-variant/20 rounded-xl glow-hover transition-all flex flex-col h-full group">
          <h3 className="font-headline-lg text-[24px] text-on-background mb-4 leading-snug">Cross-Agent Correlation</h3>
          <p className="font-body-md text-on-surface-variant mb-auto">Trace failures back to root cause across multi-step workflows with comprehensive cross-step correlation.</p>
          <div className="mt-8 flex items-center gap-2 text-on-surface-variant group-hover:text-primary transition-colors">
            <div className="w-8 h-8 rounded-lg bg-surface-container-high border border-outline-variant/30 flex items-center justify-center">
              <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
            </div>
            <span className="font-label-sm">Docs</span>
          </div>
        </div>
        
        <div className="p-8 bg-surface-container-lowest border border-outline-variant/20 rounded-xl glow-hover transition-all flex flex-col h-full group">
          <h3 className="font-headline-lg text-[24px] text-on-background mb-4 leading-snug">Explainable AI Insights</h3>
          <p className="font-body-md text-on-surface-variant mb-auto">Score agent outputs using built-in evals with real-time trend tracking and actionable reasoning.</p>
          <div className="mt-8 flex items-center gap-2 text-on-surface-variant group-hover:text-primary transition-colors">
            <div className="w-8 h-8 rounded-lg bg-surface-container-high border border-outline-variant/30 flex items-center justify-center">
              <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
            </div>
            <span className="font-label-sm">Docs</span>
          </div>
        </div>
      </div>
    </section>
  );
};

export default FeaturesSection;
