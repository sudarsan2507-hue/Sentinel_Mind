import React from 'react';
import { Zap, Cpu, Database } from 'lucide-react';

export default function Capabilities() {
  const capabilities = [
    {
      icon: <Zap className="w-6 h-6" />,
      color: 'bg-blue-500/10 border-blue-500/20 text-blue-400',
      title: 'Deterministic Loop Fingerprinting',
      desc: (
        <>
          Computes SHA256 hashes of <code className="text-blue-300 bg-slate-800 px-1 rounded">tool + args</code>. Catches infinite loops instantly without wasting model tokens or latency on counting.
        </>
      ),
    },
    {
      icon: <Cpu className="w-6 h-6" />,
      color: 'bg-indigo-500/10 border-indigo-500/20 text-indigo-400',
      title: 'Meta-Agent Evaluation',
      desc: 'LLaMA-3.3 70B via Groq evaluates goals, tool registries, and execution contexts in real time to generate precise English explanations for every verdict.',
    },
    {
      icon: <Database className="w-6 h-6" />,
      color: 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400',
      title: 'Failure Knowledge Graph',
      desc: 'Transforms non-OK verdicts into persistent graph memory. Distills capability gaps into negative prompt lessons to prevent repeated mistakes across runs.',
    },
  ];

  return (
    <section id="features" className="py-24 max-w-7xl mx-auto px-6 relative z-10">
      <div className="text-center max-w-3xl mx-auto mb-16">
        <h2 className="text-3xl font-bold text-white mb-4">Engineered for Critical AI Observability</h2>
        <p className="text-slate-400">Traditional logging tells you what failed after the fact. SentinelMind acts while the agent is running.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {capabilities.map((item, idx) => (
          <div key={idx} className="p-6 rounded-2xl bg-slate-900/60 border border-slate-800 hover:border-slate-700 transition-all">
            <div className={`w-12 h-12 rounded-xl border flex items-center justify-center mb-6 ${item.color}`}>
              {item.icon}
            </div>
            <h3 className="text-xl font-bold text-white mb-2">{item.title}</h3>
            <p className="text-slate-400 text-sm leading-relaxed">{item.desc}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
