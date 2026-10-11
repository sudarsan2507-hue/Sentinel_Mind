import { Link } from 'react-router-dom';
import { ARCHITECTURE, DOCS, REPO } from '../lib/links';

const link = 'inline-flex min-h-11 md:min-h-0 items-center text-[16px] md:text-[15px] text-on-surface-variant hover:text-on-background transition-colors';

const Footer = () => {
  return (
    <footer className="px-margin-mobile md:px-margin-desktop py-12 border-t border-outline-variant/40">
      <div className="max-w-container-max mx-auto flex flex-col md:flex-row justify-between gap-10">
        <div className="max-w-xs">
          <p className="font-headline-lg text-[20px] font-bold text-on-background">SentinelMind</p>
          <p className="mt-2 text-[16px] md:text-[15px] leading-relaxed text-on-surface-variant">
            An AI agent that watches other AI agents and says what went wrong while it is happening.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-x-16 gap-y-1">
          <div className="flex flex-col md:gap-3">
            <p className="text-[16px] md:text-[15px] font-semibold text-on-background mb-1">Product</p>
            <Link className={link} to="/dashboard">Live dashboard</Link>
            <Link className={link} to="/graph">Failure memory</Link>
            <a className={link} href="#features">What it catches</a>
          </div>
          <div className="flex flex-col md:gap-3">
            <p className="text-[16px] md:text-[15px] font-semibold text-on-background mb-1">Project</p>
            <a className={link} href={DOCS} target="_blank" rel="noreferrer">Documentation</a>
            <a className={link} href={ARCHITECTURE} target="_blank" rel="noreferrer">Architecture</a>
            <a className={link} href={REPO} target="_blank" rel="noreferrer">Source on GitHub</a>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
