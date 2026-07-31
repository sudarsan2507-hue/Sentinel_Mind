import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Activity, ShieldCheck, RefreshCw } from 'lucide-react';

export default function TraceSimulator() {
  const [simulatedStep, setSimulatedStep] = useState(0);

  const traceSteps = [
    { id: 1, tool: 'search_docs', latency: '80.5ms', status: 'OK', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', desc: 'Valid similarity search' },
    { id: 2, tool: 'lookup_customer', latency: '50.3ms', status: 'OK', color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/30', desc: 'Fetched user history' },
    { id: 3, tool: 'fetch_pricing', latency: '2400.8ms', status: 'WARN', color: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/30', desc: 'Degraded upstream latency' },
    { id: 4, tool: 'delete_user_record', latency: '40.7ms', status: 'ANOMALY', color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/30', desc: 'Hallucinated unapproved tool call' },
    { id: 5, tool: 'fetch_pricing (x3)', latency: '182.0ms', status: 'ANOMALY', color: 'text-rose-400', bg: 'bg-rose-500/10 border-rose-500/30', desc: 'Deterministic loop detected (sha256 match)' },
  ];

  useEffect(() => {
    const timer = setInterval(() => {
      setSimulatedStep((prev) => (prev + 1) % traceSteps.length);
    }, 2800);
    return () => clearInterval(timer);
  }, [traceSteps.length]);

  return (
    <motion.div 
      initial={{ opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, delay: 0.4 }}
      className="relative max-w-5xl mx-auto rounded-2xl border border-slate-800 bg-[#0b0e17]/90 p-6 shadow-2xl backdrop-blur-xl"
    >
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="w-3 h-3 rounded-full bg-rose-500/80" />
          <div className="w-3 h-3 rounded-full bg-amber-500/80" />
          <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
          <span className="ml-2 text-xs font-mono text-slate-400">sentinel-mind://live-trace-stream</span>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-md border border-emerald-500/20">
          <Activity className="w-3.5 h-3.5 animate-pulse" />
          Meta-Agent: LLaMA-3.3 70B Active
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        
        {/* Steps Simulation list */}
        <div className="lg:col-span-7 space-y-3">
          <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center justify-between">
            <span>Monitored Agent Pipeline</span>
            <span className="text-slate-500 font-mono">Goal: Customer Refund Eligibility</span>
          </div>

          {traceSteps.map((step, idx) => {
            const isActive = idx === simulatedStep;
            return (
              <motion.div
                key={step.id}
                animate={{ scale: isActive ? 1.01 : 1 }}
                className={`p-3.5 rounded-xl border transition-all ${step.bg} ${isActive ? 'ring-1 ring-blue-500 shadow-lg' : 'opacity-80'}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-slate-500">#{step.id}</span>
                    <span className="font-mono text-sm font-semibold text-slate-200">{step.tool}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-slate-400">{step.latency}</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded ${step.color} bg-black/40`}>
                      {step.status}
                    </span>
                  </div>
                </div>
                <p className="text-xs text-slate-400 mt-1.5 pl-7">{step.desc}</p>
              </motion.div>
            );
          })}
        </div>

        {/* Meta Agent Verdict Stream */}
        <div className="lg:col-span-5 bg-slate-950/60 rounded-xl p-4 border border-slate-800 flex flex-col justify-between">
          <div>
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-blue-400" />
              <span>Meta-Agent Realtime Verdict</span>
            </div>

            <AnimatePresence mode="wait">
              <motion.div
                key={simulatedStep}
                initial={{ opacity: 0, x: 10 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -10 }}
                className="space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-mono text-slate-400">Step Tool:</span>
                  <span className="text-xs font-mono text-blue-400">{traceSteps[simulatedStep].tool}</span>
                </div>

                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <span className="text-xs font-mono text-slate-500 block mb-1">Reasoning Explanation:</span>
                  <p className="text-sm text-slate-200 leading-snug">
                    {traceSteps[simulatedStep].desc}
                  </p>
                </div>

                <div className="flex justify-between items-center text-xs text-slate-400 pt-2 border-t border-slate-800">
                  <span>Evaluator Latency:</span>
                  <span className="font-mono text-emerald-400">0.56s (p50)</span>
                </div>
              </motion.div>
            </AnimatePresence>
          </div>

          <div className="mt-6 pt-4 border-t border-slate-800 text-center">
            <span className="text-xs text-slate-500 flex items-center justify-center gap-2">
              <RefreshCw className="w-3 h-3 animate-spin text-blue-400" />
              Streaming live events via WebSockets
            </span>
          </div>
        </div>

      </div>
    </motion.div>
  );
}
