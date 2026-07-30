import React from 'react';

export default function MetricsBanner() {
  const metrics = [
    { label: 'p50 Verdict Latency', value: '0.56s', color: 'text-white' },
    { label: 'Labelled Eval Score', value: '8–9 / 9', color: 'text-emerald-400' },
    { label: 'Offline Test Suite', value: '20 / 20', color: 'text-blue-400' },
    { label: 'Agent POST Overhead', value: '< 1ms', color: 'text-indigo-400' },
  ];

  return (
    <section id="evals" className="border-y border-slate-800/80 bg-slate-950/40 py-12 relative z-10">
      <div className="max-w-7xl mx-auto px-6 grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
        {metrics.map((m, idx) => (
          <div key={idx}>
            <div className={`text-3xl font-extrabold font-mono ${m.color}`}>{m.value}</div>
            <div className="text-xs font-medium text-slate-400 uppercase tracking-wider mt-1">{m.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
