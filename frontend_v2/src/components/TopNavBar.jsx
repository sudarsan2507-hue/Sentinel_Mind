import { Link, useNavigate } from 'react-router-dom';

const TopNavBar = () => {
  const navigate = useNavigate();
  return (
    <nav className="fixed top-0 left-0 w-full z-50 flex justify-between items-center px-margin-mobile md:px-margin-desktop py-4 bg-background/80 backdrop-blur-md border-b border-outline-variant/30">
      <div className="flex items-center gap-8">
        <div className="flex items-center gap-2">
          <Link to="/">
            <span className="font-headline-lg text-[24px] font-extrabold text-on-background tracking-tighter cursor-pointer">SentinelMind</span>
          </Link>
        </div>
        <div className="hidden md:flex items-center gap-6">
          <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-colors duration-200 flex items-center gap-1" href="#">Product</a>
          <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-colors duration-200" href="#">Resources</a>
          <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-colors duration-200" href="#">Pricing</a>
          <a className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-colors duration-200" href="#">Customers</a>
          <Link className="font-label-sm text-label-sm text-on-surface-variant hover:text-primary transition-colors duration-200" to="/dashboard">Dashboard</Link>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/dashboard')}
          className="hidden sm:block px-5 py-2 bg-surface-container-high/50 border border-outline-variant/20 rounded-full font-label-sm text-label-sm text-on-surface hover:bg-surface-variant transition-colors cursor-pointer"
        >
          Login
        </button>
        <button
          onClick={() => navigate('/dashboard')}
          className="px-5 py-2 bg-surface-container-high/50 border border-outline-variant/20 rounded-full font-label-sm text-label-sm text-on-surface hover:bg-surface-variant transition-colors cursor-pointer"
        >
          Sign Up
        </button>
      </div>
    </nav>
  );
};

export default TopNavBar;
