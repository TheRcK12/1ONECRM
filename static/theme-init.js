(() => {
  try {
    const saved = localStorage.getItem('one-crm-theme');
    document.documentElement.dataset.theme = saved === 'light' ? 'light' : 'dark';
  } catch (_error) {
    document.documentElement.dataset.theme = 'dark';
  }
})();
