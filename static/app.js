document.addEventListener('DOMContentLoaded', () => {
  // Theme toggle (persists)
  const root = document.documentElement;
  const themeBtn = document.getElementById('theme-toggle');
  const saved = localStorage.getItem('axis_theme');
  root.setAttribute('data-theme', (saved === 'dark' || saved === 'light') ? saved : 'light');
  if (themeBtn) themeBtn.addEventListener('click', () => {
    const cur = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', cur);
    localStorage.setItem('axis_theme', cur);
  });

  // Mobile sidebar toggle
  const btn = document.getElementById('mobile-menu-btn');
  const sidebar = document.getElementById('sidebar');
  if (btn && sidebar) btn.addEventListener('click', () => sidebar.classList.toggle('hidden'));

  // Auto-dismiss flash
  setTimeout(() => {
    document.querySelectorAll('[data-flash]').forEach(el => {
      el.style.transition = 'opacity 250ms ease';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    });
  }, 3500);

  // CSRF: add hidden input to all POST forms
  const meta = document.querySelector('meta[name="csrf-token"]');
  const token = meta ? meta.content : null;
  if (token) {
    document.querySelectorAll('form').forEach(f => {
      const m = (f.getAttribute('method') || 'GET').toUpperCase();
      if (m === 'POST' && !f.querySelector('input[name="csrf_token"]')) {
        const hid = document.createElement('input');
        hid.type = 'hidden';
        hid.name = 'csrf_token';
        hid.value = token;
        f.appendChild(hid);
      }
    });
  }

  // Helpers for charts
  function cssVar(name){ return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
  function hexToRgba(hex, alpha){
    const h=hex.replace('#',''); const v = parseInt(h.length===3 ? h.split('').map(c=>c+c).join('') : h, 16);
    const r=(v>>16)&255, g=(v>>8)&255, b=v&255; return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }

  // KPI Chart (if present)
  const el = document.getElementById('kpiChart');
  if (el && window.Chart){
    try{
      const labels = JSON.parse(el.dataset.labels || '[]');
      const values = JSON.parse(el.dataset.values || '[]');
      const brand = cssVar('--brand') || cssVar('--brand1') || '#2f6fec';
      const ctx = el.getContext('2d');
      new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            label: 'Appointments',
            data: values,
            tension: .35, borderWidth: 2,
            borderColor: brand,
            backgroundColor: hexToRgba(brand, 0.12),
            fill: true, pointRadius: 2, pointHoverRadius: 4
          }]
        },
        options: {
          responsive: true,
          plugins: { legend: { display:false } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
    }catch(e){ console.error('Chart init failed', e); }
  }
});
