(() => {
  try {
    const theme = localStorage.getItem('one-crm-theme');
    const accent = (localStorage.getItem('one-crm-accent') || 'emerald').toLowerCase();
    const presets = new Set(['emerald','cyan','blue','violet','rose','amber']);
    document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.background = 'obsidian';
    localStorage.setItem('one-crm-background', 'obsidian');
    if (presets.has(accent)) {
      document.documentElement.dataset.accent = accent;
    } else if (/^#[0-9a-f]{6}$/.test(accent)) {
      const n=parseInt(accent.slice(1),16),r=(n>>16)&255,g=(n>>8)&255,b=n&255;
      const mix=(v,t,p)=>Math.round(v+(t-v)*p);
      const strong=`#${[mix(r,0,.22),mix(g,0,.22),mix(b,0,.22)].map(v=>v.toString(16).padStart(2,'0')).join('')}`;
      document.documentElement.dataset.accent='custom';
      document.documentElement.style.setProperty('--accent',accent);
      document.documentElement.style.setProperty('--accent-strong',strong);
      document.documentElement.style.setProperty('--accent-soft',`rgba(${r},${g},${b},.12)`);
      document.documentElement.style.setProperty('--accent-glow',`rgba(${r},${g},${b},.24)`);
      document.documentElement.style.setProperty('--accent-rgb',`${r},${g},${b}`);
      document.documentElement.style.setProperty('--cyan',accent);
      document.documentElement.style.setProperty('--cyan-dark',strong);
    } else {
      document.documentElement.dataset.accent = 'emerald';
    }
  } catch (_error) {
    document.documentElement.dataset.theme = 'dark';
    document.documentElement.dataset.accent = 'emerald';
    document.documentElement.dataset.background = 'obsidian';
  }
})();
