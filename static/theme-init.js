(() => {
  try {
    const theme = localStorage.getItem('one-crm-theme');
    const legacy = {emerald:'#55e69d',cyan:'#48dfe5',blue:'#62a8ff',violet:'#a983ff',rose:'#ff72ad',amber:'#f0b95d'};
    const stored = (localStorage.getItem('one-crm-accent') || '#55e69d').toLowerCase();
    const accent = /^#[0-9a-f]{6}$/.test(stored) ? stored : (legacy[stored] || '#55e69d');
    document.documentElement.dataset.theme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.background = 'obsidian';
    document.documentElement.dataset.accent = 'custom';
    localStorage.setItem('one-crm-background', 'obsidian');
    localStorage.setItem('one-crm-accent', accent);
    const n=parseInt(accent.slice(1),16),r=(n>>16)&255,g=(n>>8)&255,b=n&255;
    const mix=(v,t,p)=>Math.round(v+(t-v)*p);
    const strong=`#${[mix(r,0,.22),mix(g,0,.22),mix(b,0,.22)].map(v=>v.toString(16).padStart(2,'0')).join('')}`;
    const luminance=(0.2126*r+0.7152*g+0.0722*b)/255;
    document.documentElement.style.setProperty('--accent',accent);
    document.documentElement.style.setProperty('--accent-strong',strong);
    document.documentElement.style.setProperty('--accent-soft',`rgba(${r},${g},${b},.12)`);
    document.documentElement.style.setProperty('--accent-glow',`rgba(${r},${g},${b},.24)`);
    document.documentElement.style.setProperty('--accent-rgb',`${r},${g},${b}`);
    document.documentElement.style.setProperty('--accent-contrast',luminance>.62?'#07100c':'#f7fbff');
    document.documentElement.style.setProperty('--cyan',accent);
    document.documentElement.style.setProperty('--cyan-dark',strong);
  } catch (_error) {
    document.documentElement.dataset.theme = 'dark';
    document.documentElement.dataset.accent = 'custom';
    document.documentElement.dataset.background = 'obsidian';
  }
})();
