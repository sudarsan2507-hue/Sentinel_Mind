import { useEffect } from 'react';
import TopNavBar from '../components/TopNavBar';
import HeroSection from '../components/HeroSection';
import FeaturesSection from '../components/FeaturesSection';
import HowItWorks from '../components/HowItWorks';
import Results from '../components/Results';
import VisualCTA from '../components/VisualCTA';
import Footer from '../components/Footer';

/* The old per-section fade-in hid every section until it was scrolled into
   view -- blank gaps in screenshots, for crawlers and on slow phones -- and
   ignored prefers-reduced-motion. The page's one animation is now the trace in
   the hero. Anchor scrolling is CSS (index.css), and off for reduced motion. */
const LandingPage = () => {
  useEffect(() => {
    document.title = 'SentinelMind: catch AI agent mistakes while they happen';
  }, []);

  return (
    <div className="min-h-screen bg-[#050505]">
      <TopNavBar />
      <main>
        <HeroSection />
        <FeaturesSection />
        <HowItWorks />
        <Results />
        <VisualCTA />
      </main>
      <Footer />
    </div>
  );
};

export default LandingPage;
