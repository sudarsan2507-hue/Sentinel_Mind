import React from 'react';
import { Code2, CheckCircle2 } from 'lucide-react';

export default function CodeIntegration() {
  const codeSnippet = `from decorator import monitor

@monitor(tool_name="search_docs")
def search_docs(query: str) -> str:
    """Emits trace event automatically to SentinelMind."""
    return vector_store.similarity_search(query)

@monitor(tool_name="lookup_customer")
def lookup_customer(customer_id: str) -> dict:
    return db.customers.find_one({"id": customer_id})`;

  return (
    <section id="code" className="py-20 bg-slate-950/60 border-t border-slate-800/80 relative z-10">
      <div className="max-w-7xl mx-auto px-6 grid grid-cols-1 lg:grid-cols-12 gap-12 items-center">
        
        <div className="lg:col-span-5">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20 text-xs font-mono mb-4">
            <Code2 className="w-3.5 h-3.5" /> 1-Line Python Decorator
          </div>
          <h2 className="text-3xl font-bold text-white mb-4">Integration Takes One Line of Code</h2>
          <p className="text-slate-300 leading-relaxed mb-6">
            Wrap any tool or model call in your pipeline with <code className="text-blue-300">@monitor</code>. Returns untouched outputs and exceptions while emitting telemetry asynchronously.
          </p>
          <ul className="space-y-3 text-sm text-slate-400">
            <li className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              Zero change to function execution or return types
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              Non-blocking telemetry (&lt;1ms POST response)
            </li>
            <li className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              Framework-agnostic (LangChain, CrewAI, or Vanilla Python)
            </li>
          </ul>
        </div>

        <div className="lg:col-span-7">
          <div className="rounded-2xl border border-slate-800 bg-[#0b0e17] overflow-hidden shadow-2xl">
            <div className="flex items-center justify-between px-4 py-3 bg-slate-900/80 border-b border-slate-800">
              <span className="text-xs font-mono text-slate-400">backend/monitored_agent.py</span>
              <span className="text-xs font-mono text-emerald-400">Python 3.11+</span>
            </div>
            <pre className="p-6 text-sm font-mono text-slate-200 overflow-x-auto leading-relaxed">
<code>{codeSnippet}</code>
            </pre>
          </div>
        </div>

      </div>
    </section>
  );
}
