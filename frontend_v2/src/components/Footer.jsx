import React from 'react';

const Footer = () => {
  return (
    <footer className="w-full py-12 px-margin-mobile md:px-margin-desktop bg-surface-container-lowest border-t border-outline-variant/20">
      <div className="max-w-container-max mx-auto flex flex-col md:flex-row justify-between items-start md:items-center gap-8">
        <div className="flex flex-col gap-4">
          <span className="font-headline-lg text-[20px] font-bold text-on-background">SentinelMind</span>
          <p className="font-label-sm text-on-surface-variant/60 max-w-xs">High-performance observability for the next generation of autonomous AI systems.</p>
        </div>
        <div className="flex flex-wrap gap-8">
          <div className="flex flex-col gap-3">
            <span className="font-label-sm text-on-surface font-bold">Product</span>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Features</a>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Security</a>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Enterprise</a>
          </div>
          <div className="flex flex-col gap-3">
            <span className="font-label-sm text-on-surface font-bold">Resources</span>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Documentation</a>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">API Reference</a>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Blog</a>
          </div>
          <div className="flex flex-col gap-3">
            <span className="font-label-sm text-on-surface font-bold">Company</span>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">About Us</a>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Privacy Policy</a>
            <a className="font-label-sm text-on-surface-variant hover:text-primary transition-colors" href="#">Terms of Service</a>
          </div>
        </div>
      </div>
      <div className="max-w-container-max mx-auto mt-12 pt-8 border-t border-outline-variant/10 flex justify-between items-center">
        <p className="font-label-sm text-on-surface-variant/40">© 2024 SentinelMind AI. All rights reserved.</p>
        <div className="flex gap-4">
          <span className="material-symbols-outlined text-on-surface-variant/40 hover:text-primary cursor-pointer">public</span>
          <span className="material-symbols-outlined text-on-surface-variant/40 hover:text-primary cursor-pointer">chat_bubble</span>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
