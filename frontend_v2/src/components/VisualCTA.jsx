import React from 'react';

const VisualCTA = () => {
  return (
    <section className="py-24 px-margin-mobile md:px-margin-desktop max-w-container-max mx-auto overflow-hidden">
      <div className="relative bg-surface-container-low rounded-3xl p-12 border border-outline-variant/20 overflow-hidden flex flex-col md:flex-row items-center gap-12 transition-all duration-700 opacity-100 translate-y-0">
        <div className="relative z-10 flex-1">
          <h3 className="font-headline-lg text-on-background mb-6">Ready to scale your <br /> AI agents?</h3>
          <p className="font-body-md text-on-surface-variant mb-8 max-w-md">Join 500+ enterprises monitoring their autonomous workflows with SentinelMind. Integration takes 2 lines of code.</p>
          <div className="flex gap-4">
            <button className="px-8 py-3 bg-primary text-on-primary font-bold rounded-lg transition-all hover:bg-primary-container">Start Free Trial</button>
            <button className="px-8 py-3 border border-outline-variant font-bold rounded-lg hover:bg-surface-variant transition-all">Book Demo</button>
          </div>
        </div>
        <div className="flex-1 relative h-64 md:h-80 w-full">
          <div className="absolute inset-0 bg-gradient-to-br from-primary-container/20 to-transparent rounded-2xl border border-outline-variant/10 flex items-center justify-center p-4">
            <div className="grid grid-cols-8 gap-2 w-full h-full opacity-40">
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '40%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '60%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '35%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '80%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '45%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '95%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '55%' }}></div>
              <div className="bg-primary-container h-full rounded-t-lg mt-auto" style={{ height: '70%' }}></div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default VisualCTA;
