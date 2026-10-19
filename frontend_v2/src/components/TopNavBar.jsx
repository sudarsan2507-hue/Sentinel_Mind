import { Link } from 'react-router-dom';
import { REPO } from '../lib/links';

const navLink = 'inline-flex min-h-11 items-center text-[15px] text-on-surface-variant hover:text-on-background transition-colors';

const TopNavBar = () => {
  return (
    <nav aria-label="Main" className="fixed top-0 left-0 w-full z-50 bg-[#050505]/85 backdrop-blur-md border-b border-outline-variant/40">
      <div className="max-w-container-max mx-auto flex justify-between items-center gap-4 px-margin-mobile md:px-margin-desktop py-2">
        <div className="flex items-center gap-8">
          <Link to="/" className="inline-flex min-h-11 items-center font-headline-lg text-[22px] font-extrabold text-on-background tracking-tight">
            SentinelMind
          </Link>
          <div className="hidden md:flex items-center gap-6">
            <a className={navLink} href="/#features">What it catches</a>
            <a className={navLink} href="/#how-it-works">How it works</a>
            <a className={navLink} href="/#results">Results</a>
            <Link className={navLink} to="/graph">Failure memory</Link>
            <a className={navLink} href={REPO} target="_blank" rel="noreferrer">GitHub</a>
          </div>
        </div>
        <div className="flex items-center gap-2">
        <Link
          to="/connect"
          className="inline-flex min-h-11 items-center rounded-md border border-primary-container/50 px-3 md:px-4 text-[15px] text-primary-container hover:bg-primary-container/10 active:bg-primary-container/15 transition-colors"
        >
          <span className="md:hidden">Connect</span>
          <span className="hidden md:inline">Connect your agent</span>
        </Link>
        <Link
          to="/dashboard"
          className="inline-flex min-h-11 items-center rounded-md bg-primary-container px-4 font-semibold text-[15px] text-[#00210a] hover:brightness-110 active:brightness-95 transition"
        >
          Dashboard
        </Link>
        </div>
      </div>
    </nav>
  );
};

export default TopNavBar;
