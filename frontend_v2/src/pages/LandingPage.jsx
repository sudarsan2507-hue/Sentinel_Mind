import { useEffect } from 'react';
import TopNavBar from '../components/TopNavBar';
import HeroSection from '../components/HeroSection';
import FeaturesSection from '../components/FeaturesSection';
import DashboardPreview from '../components/DashboardPreview';
import VisualCTA from '../components/VisualCTA';
import Footer from '../components/Footer';

const LandingPage = () => {
  useEffect(() => {
    // Smooth scroll for anchor links
    const handleAnchorClick = (e) => {
      const target = e.target.closest('a[href^="#"]');
      if (target) {
        const href = target.getAttribute('href');
        if (href && href !== '#') {
          e.preventDefault();
          const el = document.querySelector(href);
          if (el) el.scrollIntoView({ behavior: 'smooth' });
        }
      }
    };
    document.addEventListener('click', handleAnchorClick);

    // Scroll-reveal animation (mirrors original Stitch JS)
    const observerOptions = { threshold: 0.1 };
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('opacity-100', 'translate-y-0');
          entry.target.classList.remove('opacity-0', 'translate-y-8');
        }
      });
    }, observerOptions);

    const elements = document.querySelectorAll('section > div');
    elements.forEach((el) => {
      el.classList.add('transition-all', 'duration-700', 'opacity-0', 'translate-y-8');
      observer.observe(el);
    });

    return () => {
      document.removeEventListener('click', handleAnchorClick);
      elements.forEach((el) => observer.unobserve(el));
    };
  }, []);

  return (
    <>
      <TopNavBar />
      <HeroSection />
      <FeaturesSection />
      <DashboardPreview />
      <VisualCTA />
      <Footer />
    </>
  );
};

export default LandingPage;
