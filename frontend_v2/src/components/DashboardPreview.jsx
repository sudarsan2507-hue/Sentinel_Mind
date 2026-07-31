
const DashboardPreview = () => {
  return (
    <section className="py-24 bg-[#050505]">
      <div className="max-w-container-max mx-auto px-margin-mobile md:px-margin-desktop transition-all duration-700 opacity-100 translate-y-0">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl p-8">
            <div className="mb-8">
              <h4 className="font-headline-lg text-[20px] text-on-background mb-2">Logs</h4>
              <p className="font-body-md text-on-surface-variant text-[14px]">Structured, level-scoped logs for every run. Debug and verify with ease.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full font-label-sm text-[12px] text-left border-separate border-spacing-y-2">
                <thead>
                  <tr className="text-on-surface-variant/50">
                    <th className="pb-4 font-medium uppercase tracking-wider">Date</th>
                    <th className="pb-4 font-medium uppercase tracking-wider">Time</th>
                    <th className="pb-4 font-medium uppercase tracking-wider">Level</th>
                    <th className="pb-4 font-medium uppercase tracking-wider">Entity</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="bg-surface-container-high/50">
                    <td className="p-3 rounded-l-lg">Today</td>
                    <td className="p-3">4:25:52 PM</td>
                    <td className="p-3 text-secondary">DEBUG</td>
                    <td className="p-3 rounded-r-lg"><span className="bg-surface-variant px-2 py-0.5 rounded border border-outline-variant/30">weather-agent</span></td>
                  </tr>
                  <tr className="bg-surface-container-high/50">
                    <td className="p-3 rounded-l-lg">Today</td>
                    <td className="p-3">4:25:50 PM</td>
                    <td className="p-3 text-secondary">DEBUG</td>
                    <td className="p-3 rounded-r-lg"><span className="bg-surface-variant px-2 py-0.5 rounded border border-outline-variant/30">weather-agent</span></td>
                  </tr>
                  <tr className="bg-surface-container-high/50">
                    <td className="p-3 rounded-l-lg">Today</td>
                    <td className="p-3">4:25:38 PM</td>
                    <td className="p-3 text-primary-fixed-dim" data-stitch-orig-opacity="1">INFO</td>
                    <td className="p-3 rounded-r-lg"><span className="bg-surface-variant px-2 py-0.5 rounded border border-outline-variant/30">draft-response-agent</span></td>
                  </tr>
                  <tr className="bg-surface-container-high/50">
                    <td className="p-3 rounded-l-lg">Today</td>
                    <td className="p-3">4:25:36 PM</td>
                    <td className="p-3 text-amber-500">WARN</td>
                    <td className="p-3 rounded-r-lg"><span className="bg-surface-variant px-2 py-0.5 rounded border border-outline-variant/30">draft-response-agent</span></td>
                  </tr>
                  <tr className="bg-surface-container-high/50">
                    <td className="p-3 rounded-l-lg">Today</td>
                    <td className="p-3">4:25:30 PM</td>
                    <td className="p-3 text-error">ERROR</td>
                    <td className="p-3 rounded-r-lg"><span className="bg-surface-variant px-2 py-0.5 rounded border border-outline-variant/30">weather-agent</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          <div className="bg-surface-container-low border border-outline-variant/20 rounded-2xl p-8">
            <div className="mb-8">
              <h4 className="font-headline-lg text-[20px] text-on-background mb-2">Before vs After</h4>
              <p className="font-body-md text-on-surface-variant text-[14px]">See how SentinelMind transforms brittle agent loops into resilient, self-healing systems.</p>
            </div>
            <div className="flex flex-col gap-8 font-label-sm text-[11px]">
              <div>
                <span className="text-on-surface-variant/40 uppercase tracking-widest text-[10px] mb-4 block">Without Sentinel</span>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Agent</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Loop</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Loop</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Loop</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Loop</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1 bg-error/10 border border-error/20 rounded text-error font-medium flex items-center gap-1 text-[11px]"><span className="material-symbols-outlined text-[14px]">dangerous</span> Crash</div>
                </div>
              </div>
              <div className="h-px bg-outline-variant/10"></div>
              <div>
                <span className="text-on-surface-variant/40 uppercase tracking-widest text-[10px] mb-4 block">With Sentinel</span>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Agent</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Loop</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1 bg-amber-500/10 border border-amber-500/20 text-amber-500 rounded font-medium flex items-center gap-1 text-[11px]">Sentinel Detects</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1.5 bg-surface-container-high border border-outline-variant/20 rounded text-on-surface-variant">Recovery</div>
                  <span className="material-symbols-outlined text-on-surface-variant/20 text-[16px]">arrow_forward</span>
                  <div className="px-3 py-1 bg-primary-container/10 border border-primary-container/20 text-primary-container rounded font-medium flex items-center gap-1 text-[11px]"><span className="material-symbols-outlined text-[14px]">check_circle</span> Completed</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default DashboardPreview;
