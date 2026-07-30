import React from 'react';
import { ShieldCheck, ArrowRight } from 'lucide-react';

export default function Navbar() {
  return (
    <nav className="relative z-10 border-b border-slate-800/80 bg-[#07090e]/80 backdrop-blur-md sticky top-0">
      <div className="max-w-7xl mx-auto px-6 h-20 flex items-center justify-between">
        
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 p-0.5 shadow-lg shadow-blue-500/20">
            <div className="w-full h-full bg-[#0b0e17] rounded-[10px] flex items-center justify-center">
              <ShieldCheck className="w-5 h-5 text-blue-400" />
            </div>
          </div>
          <div>
            <span className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
              SentinelMind
              <span className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">v2.0</span>
            </span>
            <p className="text-xs text-slate-400">Real-Time Agent Observability</p>
          </div>
        </div>

        <div className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-300">
          <a href="#features" className="hover:text-blue-400 transition-colors">Capabilities</a>
          <a href="#architecture" className="hover:text-blue-400 transition-colors">Architecture</a>
          <a href="#code" className="hover:text-blue-400 transition-colors">Integration</a>
          <a href="#evals" className="hover:text-blue-400 transition-colors">Metrics</a>
        </div>

        <div className="flex items-center gap-4">
          <div className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-mono text-emerald-400">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            Backend Active :5000
          </div>
          <a 
            href="http://127.0.0.1:5000" 
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm transition-all shadow-lg shadow-blue-600/25 hover:shadow-blue-500/40 active:scale-[0.98]"
          >
            Launch Dashboard
            <ArrowRight className="w-4 h-4" />
          </a>
        </div>

      </div>
    </nav>
  );
}
