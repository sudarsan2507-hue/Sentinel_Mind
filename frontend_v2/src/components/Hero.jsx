import React from 'react';
import { motion } from 'framer-motion';
import { Sparkles, ExternalLink } from 'lucide-react';
import TraceSimulator from './TraceSimulator';

export default function Hero() {
  return (
    <section className="relative z-10 pt-16 pb-24 max-w-7xl mx-auto px-6">
      <div className="text-center max-w-4xl mx-auto mb-16">
        
        <motion.div 
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-slate-800/80 border border-slate-700 text-xs font-medium text-blue-300 mb-6 shadow-sm"
        >
          <Sparkles className="w-3.5 h-3.5 text-blue-400" />
          <span>FRONTIER 2026 • AI Safety & Observability Track</span>
        </motion.div>

        <motion.h1 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.1 }}
          className="text-4xl sm:text-6xl font-extrabold tracking-tight text-white leading-[1.15] mb-6"
        >
          An AI Agent That Watches Other AI Agents <br className="hidden sm:inline" />
          <span className="bg-gradient-to-r from-blue-400 via-indigo-300 to-emerald-400 bg-clip-text text-transparent">
            In Real Time, With Reasons.
          </span>
        </motion.h1>

        <motion.p 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="text-lg text-slate-300 max-w-2xl mx-auto leading-relaxed mb-10"
        >
          LLM agents fail silently—hallucinating tools, stuck in infinite loops, or drifting from goals. 
          <strong className="text-white font-semibold"> SentinelMind</strong> judges every step in real time with a 70B meta-agent and distilled failure memory.
        </motion.p>

        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
          className="flex flex-wrap items-center justify-center gap-4"
        >
          <a 
            href="http://127.0.0.1:5000"
            target="_blank"
            rel="noreferrer"
            className="px-6 py-3.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-base transition-all shadow-xl shadow-blue-600/30 flex items-center gap-2 hover:scale-[1.02]"
          >
            Open Live Dashboard
            <ExternalLink className="w-4 h-4" />
          </a>
          <a 
            href="#architecture"
            className="px-6 py-3.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700 text-slate-200 font-semibold text-base transition-all flex items-center gap-2"
          >
            How It Works
          </a>
        </motion.div>

      </div>

      <TraceSimulator />
    </section>
  );
}
