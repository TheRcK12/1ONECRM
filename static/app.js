'use strict';

const state = {
  user: null,
  csrf: '',
  version: '',
  appName: 'ONE CRM',
  catalogs: {},
  plans: [],
  users: [],
  teams: [],
  roles: [],
  roleData: null,
  currentSales: [],
  currentSale: null,
  aiMessages: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const nativeRoleLabels = {owner:'Dono',manager:'Gerente',bko:'BKO',seller:'Vendedor'};
const roleLabel = role => state.roles.find(item=>item.code===role)?.name || nativeRoleLabels[role] || role;
const baseRole = user => user?.base_role || state.roles.find(item=>item.code===user?.role_code)?.base_role || user?.role_code || 'seller';
const money = value => Number(value || 0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const fmtDate = value => {
  if (!value) return '-';
  const raw = String(value).slice(0,10);
  const [y,m,d] = raw.split('-');
  return y && m && d ? `${d}/${m}/${y}` : value;
};
const fmtDateTime = value => {
  if (!value) return '-';
  const date = new Date(String(value).replace('Z',''));
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('pt-BR');
};
const initials = name => String(name || 'OC').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
const has = permission => baseRole(state.user) === 'owner' || state.user?.permissions?.includes(permission);
const currentTheme = () => document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
function updateThemeUi() {
  const light = currentTheme() === 'light';
  const icon = $('#theme-icon');
  const button = $('#theme-toggle-btn');
  const authIcon = $('#auth-theme-icon');
  const authButton = $('#auth-theme-toggle');
  if (icon) icon.textContent = light ? '☀' : '☾';
  if (authIcon) authIcon.textContent = light ? '☀' : '☾';
  if (button) {
    button.title = light ? 'Usar tema escuro' : 'Usar tema claro';
    button.setAttribute('aria-label', button.title);
  }
  if (authButton) {
    authButton.title = light ? 'Usar tema escuro' : 'Usar tema claro';
    authButton.setAttribute('aria-label', authButton.title);
  }
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = light ? '#f3f7f8' : '#0d1518';
}
function applyTheme(theme, {saveLocal=true}={}) {
  const normalized = theme === 'light' ? 'light' : 'dark';
  document.documentElement.dataset.theme = normalized;
  if (saveLocal) localStorage.setItem('one-crm-theme', normalized);
  updateThemeUi();
}
async function toggleTheme() {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  if (state.user) {
    state.user.theme_preference = next;
    try { await api('/api/me/theme',{method:'PUT',body:{theme:next}}); }
    catch(error) { toast('Tema aplicado neste navegador, mas não foi salvo na conta: ' + error.message,'error'); }
  }
}
const qs = obj => new URLSearchParams(Object.entries(obj).filter(([,v]) => v !== '' && v !== null && v !== undefined)).toString();
const onlyNumbers = (value, max=99) => String(value ?? '').replace(/\D/g,'').slice(0,max);
const brazilianDdds = new Set('11 12 13 14 15 16 17 18 19 21 22 24 27 28 31 32 33 34 35 37 38 41 42 43 44 45 46 47 48 49 51 53 54 55 61 62 63 64 65 66 67 68 69 71 73 74 75 77 79 81 82 83 84 85 86 87 88 89 91 92 93 94 95 96 97 98 99'.split(' '));
const formatCep = value => {
  const d = onlyNumbers(value,8);
  return d.length > 5 ? `${d.slice(0,5)}-${d.slice(5)}` : d;
};
const formatPhone = value => {
  let d = onlyNumbers(value,13);
  if ((d.length === 12 || d.length === 13) && d.startsWith('55')) d = d.slice(2);
  if (!d) return '';
  if (d.length <= 2) return `(${d}`;
  if (d.length <= 6) return `(${d.slice(0,2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0,2)}) ${d.slice(2,6)}-${d.slice(6)}`;
  return `(${d.slice(0,2)}) ${d.slice(2,7)}-${d.slice(7,11)}`;
};
const formatDocument = (value, type='CPF') => {
  const d = onlyNumbers(value, type === 'CNPJ' ? 14 : 11);
  if (type === 'CNPJ') {
    return d.replace(/^(\d{2})(\d)/,'$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/,'$1.$2.$3')
      .replace(/\.(\d{3})(\d)/,'.$1/$2').replace(/(\d{4})(\d)/,'$1-$2');
  }
  return d.replace(/^(\d{3})(\d)/,'$1.$2').replace(/^(\d{3})\.(\d{3})(\d)/,'$1.$2.$3')
    .replace(/\.(\d{3})(\d)/,'.$1-$2');
};
function validCpf(value) {
  const d = onlyNumbers(value,11);
  if (d.length !== 11 || /^(\d)\1{10}$/.test(d)) return false;
  for (let size=9; size<=10; size++) {
    let total=0;
    for (let i=0;i<size;i++) total += Number(d[i]) * (size + 1 - i);
    let check=(total*10)%11; if(check===10) check=0;
    if(check!==Number(d[size])) return false;
  }
  return true;
}
function validCnpj(value) {
  const d=onlyNumbers(value,14);
  if(d.length!==14 || /^(\d)\1{13}$/.test(d)) return false;
  const calc=(base,weights)=>{const rem=[...base].reduce((sum,n,i)=>sum+Number(n)*weights[i],0)%11;return rem<2?0:11-rem;};
  const first=calc(d.slice(0,12),[5,4,3,2,9,8,7,6,5,4,3,2]);
  const second=calc(d.slice(0,12)+first,[6,5,4,3,2,9,8,7,6,5,4,3,2]);
  return d.endsWith(`${first}${second}`);
}
function normalizeMobileInput(value) {
  let d=onlyNumbers(value,13);
  if((d.length===12||d.length===13)&&d.startsWith('55')) d=d.slice(2);
  if(d.length===10) d=`${d.slice(0,2)}9${d.slice(2)}`;
  return formatPhone(d);
}
function validMobile(value) {
  let d=onlyNumbers(value,13);
  if((d.length===12||d.length===13)&&d.startsWith('55')) d=d.slice(2);
  if(d.length===10) d=`${d.slice(0,2)}9${d.slice(2)}`;
  return d.length===11 && brazilianDdds.has(d.slice(0,2)) && d[2]==='9';
}

async function fetchJsonWithTimeout(url, timeout=6500) {
  const controller = new AbortController();
  const timer = setTimeout(()=>controller.abort(),timeout);
  try {
    const response = await fetch(url,{headers:{Accept:'application/json'},signal:controller.signal,cache:'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally { clearTimeout(timer); }
}

async function lookupCepInBrowser(cep) {
  const providers = [
    {name:'BrasilAPI',url:`https://brasilapi.com.br/api/cep/v2/${cep}`,map:p=>({street:p.street||'',complement:p.complement||'',neighborhood:p.neighborhood||'',city:p.city||'',uf:p.state||'',source:`BrasilAPI · ${p.service||'fallback'}`})},
    {name:'ViaCEP',url:`https://viacep.com.br/ws/${cep}/json/`,map:p=>({street:p.logradouro||'',complement:p.complemento||'',neighborhood:p.bairro||'',city:p.localidade||'',uf:p.uf||'',source:'ViaCEP'})},
    {name:'OpenCEP',url:`https://opencep.com/v1/${cep}.json`,map:p=>({street:p.logradouro||'',complement:p.complemento||'',neighborhood:p.bairro||'',city:p.localidade||'',uf:p.uf||'',source:'OpenCEP'})},
  ];
  for (const provider of providers) {
    try {
      const payload = await fetchJsonWithTimeout(provider.url);
      if (payload?.erro || payload?.error) continue;
      const address = provider.map(payload || {});
      address.uf=String(address.uf||'').toUpperCase();
      if (address.city && address.uf.length===2) {
        address.cep=cep;address.cached=false;address.browserFallback=true;
        if(!address.street) address.warning='CEP geral encontrado. Preencha o logradouro e o número manualmente.';
        return address;
      }
    } catch (_) { /* tenta a próxima fonte */ }
  }
  throw new Error('Nenhuma fonte de CEP respondeu no servidor nem no navegador. Tente novamente ou preencha manualmente.');
}

function toast(message, type='success') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = message;
  $('#toast-root').appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function api(path, options={}) {
  const headers = {'Accept':'application/json', ...(options.headers || {})};
  if (options.body && typeof options.body !== 'string') {
    headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(options.body);
  }
  if (options.method && options.method !== 'GET' && state.csrf) headers['X-CSRF-Token'] = state.csrf;
  const response = await fetch(path, {...options, headers, credentials:'same-origin'});
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    if (response.status === 401) {
      state.user = null;
      showAuth(false);
    }
    throw new Error(data?.error || data || `Erro HTTP ${response.status}`);
  }
  return data;
}

function formObject(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  $$('input[type=checkbox]', form).forEach(input => data[input.name] = input.checked);
  return data;
}

function optionList(items, selected='', placeholder='Selecione...') {
  return `<option value="">${esc(placeholder)}</option>` + (items || []).map(item => {
    const value = item.code ?? item.id;
    const label = item.label ?? item.name;
    return `<option value="${esc(value)}" ${String(value)===String(selected)?'selected':''}>${esc(label)}</option>`;
  }).join('');
}

function catalogOptions(category, selected='', placeholder='Selecione...') {
  return optionList(state.catalogs[category] || [], selected, placeholder);
}

function badge(label, code='') {
  const text = String(label || code || '-');
  const low = `${code} ${text}`.toLowerCase();
  let color = 'cyan';
  if (/instalado|ativado|ok|conclu/.test(low)) color = 'green';
  else if (/cancel|não|nao|reprov|trash|sem sucesso/.test(low)) color = 'red';
  else if (/pendente|aguard|tratamento|prometeu|retorno|reagend/.test(low)) color = 'amber';
  else if (/bko|violet/.test(low)) color = 'violet';
  return `<span class="badge ${color}"><span class="status-dot"></span>${esc(text)}</span>`;
}

function modal(title, body, {wide=false, footer=''}={}) {
  $('#modal-root').innerHTML = `
    <div class="modal-backdrop" data-close-modal>
      <section class="modal ${wide?'wide':''}" onclick="event.stopPropagation()">
        <header class="modal-head"><h3>${esc(title)}</h3><button class="icon-btn" data-close-modal>×</button></header>
        <div class="modal-body">${body}</div>
        ${footer ? `<footer class="modal-foot">${footer}</footer>` : ''}
      </section>
    </div>`;
  $$('[data-close-modal]').forEach(el => el.addEventListener('click', closeModal));
}
function closeModal(){ $('#modal-root').innerHTML=''; }

function drawer(title, body) {
  $('#modal-root').innerHTML = `
    <div class="drawer-backdrop" data-close-modal>
      <section class="drawer" onclick="event.stopPropagation()">
        <header class="drawer-head"><h3>${esc(title)}</h3><button class="icon-btn" data-close-modal>×</button></header>
        <div class="drawer-body">${body}</div>
      </section>
    </div>`;
  $$('[data-close-modal]').forEach(el => el.addEventListener('click', closeModal));
}

async function ensureReferenceData() {
  const calls = [];
  if (!Object.keys(state.catalogs).length) calls.push(api('/api/catalogs').then(r => state.catalogs = r.catalogs));
  if (!state.plans.length) calls.push(api('/api/plans').then(r => state.plans = r.plans));
  if ((has('users.view') || has('sales.all') || has('workflow.bko')) && !state.users.length) calls.push(api('/api/users').then(r => state.users = r.users).catch(()=>{}));
  if (!state.teams.length) calls.push(api('/api/teams').then(r => state.teams = r.teams).catch(()=>{}));
  await Promise.all(calls);
}

function setPage(title, eyebrow='ONE CRM') {
  $('#page-title').textContent = title;
  $('#page-eyebrow').textContent = eyebrow;
  document.title = `${title} · ${state.appName || 'ONE CRM'}`;
}

const salesNavigationItems = [
  {id:'sales',label:'Todas as vendas',icon:'▤',test:()=>has('sales.own')||has('sales.all')||baseRole(state.user)==='bko'},
  {id:'new-sale',label:'Nova venda',icon:'＋',permission:'sales.create'},
  {id:'bko',label:'Gestão BKO',icon:'◎',permission:'workflow.bko'},
];

const administrativeNavigationItems = [
  {id:'users',label:'Funcionários',icon:'♙',permission:'users.view'},
  {id:'teams',label:'Equipes',icon:'◫',test:()=>has('teams.view')||has('teams.manage')},
  {id:'plans',label:'Planos',icon:'▱',permission:'plans.manage'},
  {id:'catalogs',label:'Catálogos',icon:'⚙',permission:'catalogs.manage'},
  {id:'roles',label:'Cargos e permissões',icon:'⌘',permission:'roles.manage'},
  {id:'audit',label:'Auditoria',icon:'◷',permission:'audit.view'},
  {id:'backups',label:'Backups',icon:'⇩',permission:'backups.manage'},
  {id:'integrations',label:'Integrações',icon:'⌁',permission:'integrations.manage'},
];

const navigationItems = [
  {id:'dashboard',label:'Dashboard',icon:'⌂',permission:'dashboard.view'},
  {id:'sales-group',label:'Vendas',icon:'▤',children:salesNavigationItems},
  {id:'daily',label:'Análise do dia',icon:'↗',permission:'daily.view'},
  {id:'powerbi',label:'Power BI',icon:'▥',permission:'powerbi.view'},
  {id:'ranking',label:'Ranking',icon:'◇',test:()=>has('ranking.own')||has('ranking.all')},
  {id:'intelligence',label:'Inteligência',icon:'✦',permission:'intelligence.view'},
  {id:'administrative-group',label:'Administrativo',icon:'⚙',children:administrativeNavigationItems},
];

function menuAllowed(item) {
  return item.test ? item.test() : item.permission ? has(item.permission) : true;
}
function visibleChildren(item) { return (item.children || []).filter(menuAllowed); }
function routeBelongsToGroup(route, group) { return visibleChildren(group).some(item => item.id === route); }

function closeNavigationPopover() {
  $('#nav-popover')?.remove();
  $$('[data-nav-group]').forEach(button => button.setAttribute('aria-expanded','false'));
}

function navigationDescription(item) {
  const descriptions = {
    sales:'Consultar, filtrar e acompanhar',
    'new-sale':'Cadastrar uma nova venda',
    bko:'Tratar ativação, biometria e instalação',
    users:'Usuários, cargos e acessos',teams:'Equipes, gestores e metas',plans:'Produtos e ofertas',
    catalogs:'Opções usadas nos formulários',roles:'Limites de cada cargo',audit:'Histórico de alterações',
    backups:'Proteção do banco de dados',integrations:'Power BI, webhook, WhatsApp e IA'
  };
  return descriptions[item.id] || 'Abrir módulo';
}

function openNavigationPopover(button, group) {
  const children = visibleChildren(group);
  if (!children.length) return;
  const existing = $('#nav-popover');
  if (existing?.dataset.group === group.id) { closeNavigationPopover(); return; }
  closeNavigationPopover();
  const popover = document.createElement('div');
  popover.id = 'nav-popover';
  popover.className = 'nav-popover';
  popover.dataset.group = group.id;
  popover.setAttribute('role','menu');
  popover.innerHTML = `
    <div class="nav-popover-head"><span>${esc(group.label)}</span><small>${children.length} opção(ões)</small></div>
    <div class="nav-popover-grid">${children.map(item => `
      <button class="nav-popover-item" type="button" data-popover-route="${item.id}" role="menuitem">
        <span class="nav-popover-icon">${item.icon}</span>
        <span><strong>${esc(item.label)}</strong><small>${esc(navigationDescription(item))}</small></span>
      </button>`).join('')}</div>`;
  document.body.appendChild(popover);
  const rect = button.getBoundingClientRect();
  const width = Math.min(group.id === 'administrative-group' ? 560 : 390, window.innerWidth - 24);
  let left = Math.min(rect.left, window.innerWidth - width - 12);
  left = Math.max(12,left);
  popover.style.width = `${width}px`;
  popover.style.left = `${left}px`;
  popover.style.top = `${Math.min(rect.bottom + 8,window.innerHeight - 80)}px`;
  button.setAttribute('aria-expanded','true');
  $$('[data-popover-route]',popover).forEach(item => item.addEventListener('click',()=>{
    closeNavigationPopover(); navigate(item.dataset.popoverRoute);
  }));
}

function renderContextSubnav(active) {
  const container = $('#context-subnav');
  const group = navigationItems.find(item => item.children && routeBelongsToGroup(active,item));
  if (!group) { container.innerHTML=''; container.classList.add('hidden'); return; }
  const children = visibleChildren(group);
  container.classList.remove('hidden');
  container.innerHTML = `<span class="context-subnav-label">${esc(group.label)}</span>${children.map(item => `
    <button class="context-subnav-item ${active===item.id?'active':''}" type="button" data-context-route="${item.id}" ${active===item.id?'aria-current="page"':''}>
      <span>${item.icon}</span>${esc(item.label)}
    </button>`).join('')}`;
  $$('[data-context-route]',container).forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.contextRoute)));
  requestAnimationFrame(()=>container.querySelector('.context-subnav-item.active')?.scrollIntoView({block:'nearest',inline:'center'}));
}

function renderTopMenu(active) {
  const container = $('#top-nav');
  if (!container) return;
  const visible = navigationItems.filter(item => item.children ? visibleChildren(item).length : menuAllowed(item));
  container.innerHTML = visible.map(item => {
    const grouped = Boolean(item.children);
    const activeItem = grouped ? routeBelongsToGroup(active,item) : active === item.id;
    return `<button class="top-nav-item ${activeItem?'active':''} ${grouped?'has-children':''}" type="button"
      ${grouped?`data-nav-group="${item.id}" aria-haspopup="menu" aria-expanded="false"`:`data-top-route="${item.id}"`}
      ${activeItem?'aria-current="page"':''}>
      <span class="top-nav-icon">${item.icon}</span><span>${esc(item.label)}</span>${grouped?'<span class="nav-chevron">⌄</span>':''}
    </button>`;
  }).join('');
  $$('[data-top-route]',container).forEach(button=>button.addEventListener('click',()=>navigate(button.dataset.topRoute)));
  $$('[data-nav-group]',container).forEach(button=>{
    const group = navigationItems.find(item=>item.id===button.dataset.navGroup);
    button.addEventListener('click',event=>{event.stopPropagation();openNavigationPopover(button,group);});
  });
  renderContextSubnav(active);
  requestAnimationFrame(()=>container.querySelector('.top-nav-item.active')?.scrollIntoView({block:'nearest',inline:'center'}));
}

function navigate(route, params='') {
  closeNavigationPopover();
  location.hash = `#/${route}${params ? '?' + params : ''}`;
}

function parseRoute() {
  const raw = location.hash.replace(/^#\//,'') || 'dashboard';
  const [route, query=''] = raw.split('?');
  return {route, params:new URLSearchParams(query)};
}

async function renderRoute() {
  if (!state.user) return;
  const {route, params} = parseRoute();
  renderTopMenu(route);
  $('#content').innerHTML = '<div class="loader">Carregando...</div>';
  try {
    const handlers = {
      dashboard: renderDashboard,
      sales: () => renderSales(params),
      'new-sale': () => openSaleForm(null, true),
      bko: renderBko,
      daily: () => renderDaily(params),
      ranking: () => renderRanking(params),
      intelligence: renderIntelligence,
      powerbi: renderPowerBI,
      users: renderUsers,
      teams: renderTeams,
      plans: renderPlans,
      catalogs: renderCatalogs,
      roles: renderRoles,
      audit: renderAudit,
      backups: renderBackups,
      integrations: renderIntegrations,
      account: renderAccount,
    };
    if (!handlers[route]) return navigate('dashboard');
    await handlers[route]();
  } catch (error) {
    $('#content').innerHTML = `<div class="panel"><div class="empty"><strong>Não foi possível carregar esta página.</strong><p>${esc(error.message)}</p></div></div>`;
    toast(error.message,'error');
  }
}

async function boot() {
  try {
    const data = await api('/api/bootstrap');
    state.version = data.version;
    state.appName = data.app || 'ONE CRM';
    $('#auth-version').textContent = data.version;
    $('#header-version').textContent = data.version;
    if (data.authenticated) {
      state.user = data.user;
      state.csrf = data.csrf_token;
      applyTheme(state.user.theme_preference || localStorage.getItem('one-crm-theme') || 'dark');
      showApp();
    } else {
      showAuth(data.setup_required, data.setup_token_required);
    }
  } catch (error) {
    document.body.innerHTML = `<main class="auth-screen"><section class="auth-card"><h1>ONE CRM não respondeu</h1><p>${esc(error.message)}</p><p class="muted">Verifique a janela do servidor e o arquivo logs/one_crm.log.</p></section></main>`;
  }
}

function showAuth(setupRequired, setupTokenRequired=false) {
  $('#app-shell').classList.add('hidden');
  $('#auth-screen').classList.remove('hidden');
  $('#setup-panel').classList.toggle('hidden', !setupRequired);
  $('#login-panel').classList.toggle('hidden', setupRequired);
  const tokenField = $('#setup-token-field');
  const tokenInput = $('#setup-token');
  tokenField?.classList.toggle('hidden', !setupTokenRequired);
  if (tokenInput) {
    tokenInput.required = Boolean(setupTokenRequired);
    if (!setupTokenRequired) tokenInput.value = '';
  }
  if (!setupRequired) {
    const rememberedEmail = localStorage.getItem('one-crm-remembered-email') || '';
    const emailInput = $('#login-form input[name="email"]');
    const rememberInput = $('#remember-email');
    if (emailInput && !emailInput.value) emailInput.value = rememberedEmail;
    if (rememberInput) rememberInput.checked = Boolean(rememberedEmail);
    setTimeout(() => (rememberedEmail ? $('#login-password') : emailInput)?.focus(), 80);
  } else {
    setTimeout(() => $('#setup-form input[name="name"]')?.focus(), 80);
  }
}

function setPasswordVisibility(button) {
  const input = document.getElementById(button.dataset.passwordTarget || '');
  if (!input) return;
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.classList.toggle('revealed', reveal);
  button.title = reveal ? 'Ocultar senha' : 'Mostrar senha';
  button.setAttribute('aria-label', button.title);
  input.focus({preventScroll:true});
}

$$('[data-password-target]').forEach(button => button.addEventListener('click', () => setPasswordVisibility(button)));

function refreshUserUi() {
  if (!state.user) return;
  const visibleName = state.user.display_name || state.user.name;
  $('#user-name').textContent = visibleName;
  $('#user-role').textContent = state.user.role_name || roleLabel(state.user.role_code);
  $('#user-initials').textContent = initials(visibleName);
}

function showApp() {
  $('#auth-screen').classList.add('hidden');
  $('#app-shell').classList.remove('hidden');
  applyTheme(state.user.theme_preference || localStorage.getItem('one-crm-theme') || 'dark');
  refreshUserUi();
  if (!location.hash) location.hash = '#/dashboard';
  renderRoute();
  if (state.user.must_change_password) setTimeout(() => { toast('Troque a senha temporária em Minha conta.','error'); navigate('account'); }, 400);
}

$('#setup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = $('button[type="submit"]', event.currentTarget); button.disabled = true;
  try {
    const data = await api('/api/setup',{method:'POST',body:formObject(event.currentTarget)});
    state.csrf = data.csrf_token;
    const bootData = await api('/api/bootstrap');
    state.user = bootData.user; state.csrf = bootData.csrf_token;
    applyTheme(state.user.theme_preference || 'dark');
    showApp(); toast('Primeiro Dono criado.');
  } catch(error) { toast(error.message,'error'); }
  finally { button.disabled = false; }
});

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = $('button[type="submit"]', event.currentTarget); button.disabled = true;
  const email = String(new FormData(event.currentTarget).get('email') || '').trim();
  if ($('#remember-email')?.checked) localStorage.setItem('one-crm-remembered-email', email);
  else localStorage.removeItem('one-crm-remembered-email');
  try {
    const data = await api('/api/login',{method:'POST',body:formObject(event.currentTarget)});
    state.csrf = data.csrf_token;
    const bootData = await api('/api/bootstrap');
    state.user = bootData.user; state.csrf = bootData.csrf_token;
    state.catalogs={};state.plans=[];state.users=[];state.teams=[];
    showApp();
  } catch(error) { toast(error.message,'error'); }
  finally { button.disabled = false; }
});

$('#logout-btn').addEventListener('click', async () => {
  try { await api('/api/logout',{method:'POST'}); } catch(_) {}
  state.user=null;state.csrf='';location.hash='';showAuth(false, false);
});
$('#theme-toggle-btn').addEventListener('click',toggleTheme);
$('#auth-theme-toggle').addEventListener('click',toggleTheme);
$('#brand-home-btn').addEventListener('click',()=>navigate('dashboard'));
$('#account-btn').addEventListener('click',()=>navigate('account'));
updateThemeUi();
$('#global-search-btn').addEventListener('click',openGlobalSearch);
window.addEventListener('hashchange',renderRoute);
window.addEventListener('keydown',event=>{ if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();openGlobalSearch();} if(event.key==='Escape'){closeNavigationPopover();closeModal();} });
document.addEventListener('click',event=>{if(!event.target.closest('#nav-popover')&&!event.target.closest('[data-nav-group]'))closeNavigationPopover();});
window.addEventListener('resize',closeNavigationPopover);
window.addEventListener('scroll',closeNavigationPopover,true);

function openGlobalSearch() {
  modal('Pesquisa global', `<form id="global-search-form" class="form-stack"><label>Cliente, CPF, telefone ou OS<input name="search" autofocus placeholder="Digite para pesquisar"></label><button class="btn primary">Pesquisar vendas</button></form>`);
  setTimeout(()=>$('#global-search-form input')?.focus(),50);
  $('#global-search-form').addEventListener('submit',e=>{e.preventDefault();const value=new FormData(e.currentTarget).get('search');closeModal();navigate('sales',qs({search:value}));});
}

async function renderDashboard() {
  setPage('Dashboard','CENTRAL DE OPERAÇÃO');
  const data = await api('/api/dashboard');
  const c = data.cards;
  const conversion = c.total ? Math.round(c.installed * 100 / c.total) : 0;
  const visibleName = state.user.display_name || state.user.name;
  const cards = [
    ['Vendas totais',c.total,`${c.today} cadastrada(s) hoje`,'▤','--cyan'],
    ['Instaladas',c.installed,`${conversion}% de conversão`,'✓','--green'],
    ['Em tratamento',c.treatment,'Precisam de acompanhamento','◷','--amber'],
    ['Agenda de hoje',c.agenda_today,fmtDate(new Date().toISOString()),'▦','--blue'],
    ['Biometria concluída',c.biometric_ok,`${c.biometric_pending} pendente(s)`,'◉','--violet'],
    ['Canceladas',c.cancelled,c.total ? `${Math.round(c.cancelled*100/c.total)}% do total` : '0%','×','--red'],
  ];
  $('#content').innerHTML = `
    <section class="dashboard-hero">
      <div><p class="eyebrow">PAINEL PRINCIPAL</p><h1>Olá, ${esc(visibleName)}</h1><p>Indicadores essenciais no topo, atalhos ao alcance e menos caça ao número certo.</p></div>
      <div class="dashboard-hero-actions">${has('sales.create')?'<button class="btn primary" id="dashboard-new-sale">＋ Nova venda</button>':''}<button class="btn" id="dashboard-view-sales">Ver vendas</button></div>
    </section>
    <section class="dashboard-metrics" aria-label="Indicadores principais">${cards.map(([title,value,note,icon,color])=>`<article class="stat-card compact" style="--accent:var(${color})"><div class="stat-top"><span>${title}</span><span class="stat-icon">${icon}</span></div><div class="stat-value">${value}</div><div class="stat-note">${note}</div></article>`).join('')}</section>
    <section class="panel dashboard-recent"><header class="panel-head"><div><h3>Vendas recentes</h3><small class="muted">Últimas movimentações no seu alcance</small></div><button class="btn small" onclick="navigate('sales')">Ver todas</button></header>${salesTable(data.recent)}</section>
    ${data.teams?.length ? `<section class="panel"><header class="panel-head"><div><h3>Desempenho das equipes</h3><small class="muted">Comparação rápida do dia</small></div><button class="btn small ghost" onclick="navigate('daily')">Análise completa</button></header><div class="panel-body dashboard-teams">${data.teams.map(t=>`<article class="team-card"><h4>${esc(t.team_name)}</h4><div class="metric-row"><span>Hoje</span><strong>${t.today}</strong></div><div class="metric-row"><span>Total</span><strong>${t.total}</strong></div><div class="metric-row"><span>Instaladas</span><strong>${t.installed}</strong></div></article>`).join('')}</div></section>`:''}`;
  $('#dashboard-new-sale')?.addEventListener('click',()=>openSaleForm(null,true));
  $('#dashboard-view-sales')?.addEventListener('click',()=>navigate('sales'));
  bindSaleRows();
}

function salesTable(sales, {showBko=true}={}) {
  if (!sales?.length) return '<div class="empty">Nenhuma venda encontrada.</div>';
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Cliente</th><th>Vendedor</th><th>Plano</th><th>Ativação</th><th>Biometria</th><th>Instalação</th><th>Agendamento</th>${showBko?'<th>BKO</th>':''}<th></th></tr></thead><tbody>
    ${sales.map(s=>`<tr data-sale-id="${s.id}">
      <td><div class="cell-main">${esc(s.client_name)}</div><div class="cell-sub">${esc(formatPhone(s.phone))} · #${s.id}</div></td>
      <td><div class="cell-main">${esc(s.seller_name||'-')}</div><div class="cell-sub">${esc(s.team_name||'Sem equipe')}</div></td>
      <td><div class="cell-main">${esc(s.plan_name_snapshot)}</div><div class="cell-sub">${money(s.plan_price_snapshot)}</div></td>
      <td>${badge(s.activation_status_label,s.activation_status)}</td>
      <td>${badge(s.biometric_status_label,s.biometric_status)}</td>
      <td>${badge(s.installation_status_label,s.installation_status)}</td>
      <td>${s.appointment_date?`<div class="cell-main">${fmtDate(s.appointment_date)}</div><div class="cell-sub">${esc(s.appointment_period||'')}</div>`:'-'}</td>
      ${showBko?`<td>${esc(s.bko_name||'Não atribuído')}</td>`:''}
      <td><button class="btn small sale-open">Abrir</button></td></tr>`).join('')}
    </tbody></table></div>`;
}

function bindSaleRows() {
  $$('.sale-open').forEach(btn => btn.addEventListener('click', event => {
    event.stopPropagation();
    const id = Number(btn.closest('tr').dataset.saleId);
    openSaleDetail(id);
  }));
  $$('tr[data-sale-id]').forEach(row => row.addEventListener('dblclick',()=>openSaleDetail(Number(row.dataset.saleId))));
}

async function renderSales(params = new URLSearchParams()) {
  setPage('Vendas','OPERAÇÃO COMERCIAL');
  await ensureReferenceData();
  const filters = {
    search: params.get('search') || '',
    status: params.get('status') || '',
    date_from: params.get('date_from') || '',
    date_to: params.get('date_to') || '',
  };
  const data = await api('/api/sales?' + qs(filters));
  state.currentSales = data.sales;
  $('#content').innerHTML = `
    <div class="page-head"><div><h1>Todas as vendas</h1><p class="muted">O backend aplica o escopo do cargo. Esconder linha no navegador seria segurança de brinquedo.</p></div>
      <div class="page-actions">${has('export.data')?'<a class="btn" href="/api/export/sales.csv">Exportar CSV</a>':''}${has('sales.create')?'<button class="btn primary" id="sales-new">＋ Nova venda</button>':''}</div></div>
    <section class="panel"><header class="panel-head"><form id="sales-filter" class="filters">
      <input name="search" value="${esc(filters.search)}" placeholder="Cliente, CPF, telefone ou OS">
      <select name="status">${catalogOptions('sale_status',filters.status,'Todos os status')}</select>
      <input type="date" name="date_from" value="${esc(filters.date_from)}" title="Data inicial">
      <input type="date" name="date_to" value="${esc(filters.date_to)}" title="Data final">
      <button class="btn primary">Filtrar</button><button type="button" class="btn ghost" id="clear-sales-filter">Limpar</button>
    </form><span class="muted">${data.sales.length} registro(s)</span></header>${salesTable(data.sales)}</section>`;
  $('#sales-new')?.addEventListener('click',()=>openSaleForm(null,true));
  $('#sales-filter').addEventListener('submit',e=>{e.preventDefault();navigate('sales',qs(formObject(e.currentTarget)));});
  $('#clear-sales-filter').addEventListener('click',()=>navigate('sales'));
  bindSaleRows();
}

function saleFormHtml(sale={}) {
  const sellers = state.users.filter(u=>u.active && ['seller','manager','owner'].includes(baseRole(u)));
  const personType = sale.person_type || 'CPF';
  return `<form id="sale-form" class="sale-wizard" novalidate>
    <nav class="wizard-steps" aria-label="Etapas da venda">
      ${[['1','Dados do cliente'],['2','Endereço'],['3','Plano e faturamento'],['4','Revisão']].map(([number,label],index)=>`
        <button type="button" class="wizard-step ${index===0?'active':''}" data-wizard-step="${number}">
          <span>${number}</span><small>${label}</small>
        </button>`).join('')}
    </nav>

    <section class="wizard-card active" data-step-card="1">
      <header class="wizard-card-head"><div><span class="wizard-kicker">ETAPA 1 DE 4</span><h3>Dados do cliente</h3><p>Identificação e canais de contato do titular.</p></div><span class="wizard-card-icon">♙</span></header>
      <div class="form-grid wizard-fields">
        <label>Tipo de pessoa<select name="person_type" id="sale-person-type"><option value="CPF" ${personType==='CPF'?'selected':''}>Pessoa física · CPF</option><option value="CNPJ" ${personType==='CNPJ'?'selected':''}>Pessoa jurídica · CNPJ</option></select></label>
        <label>Nome completo / Razão social<input name="client_name" required minlength="3" maxlength="180" autocomplete="name" value="${esc(sale.client_name||'')}"></label>
        <label><span id="document-label">${personType}</span><input name="cpf_cnpj" id="sale-document" required inputmode="numeric" autocomplete="off" maxlength="18" placeholder="${personType==='CNPJ'?'00.000.000/0000-00':'000.000.000-00'}" value="${esc(formatDocument(sale.cpf_cnpj||'',personType))}"><small class="field-hint">Somente números são aceitos. O ONE CRM valida os dígitos do documento.</small></label>
        <label>Data de nascimento<input name="birth_date" type="date" value="${esc(sale.birth_date||'')}"></label>
        <label>Telefone principal<input name="phone" id="sale-phone" required inputmode="tel" autocomplete="tel" maxlength="15" placeholder="(61) 99111-1111" value="${esc(formatPhone(sale.phone||''))}"><small class="field-hint">Celular com DDD. O formato é aplicado automaticamente.</small></label>
        <label>Segundo telefone<input name="contact_phone" id="sale-contact-phone" inputmode="tel" maxlength="15" placeholder="(61) 99111-1111" value="${esc(formatPhone(sale.contact_phone||''))}"></label>
        <label>E-mail<input name="email" type="email" autocomplete="email" maxlength="160" value="${esc(sale.email||'')}"></label>
        <label>Nome da mãe<input name="mother_name" maxlength="160" value="${esc(sale.mother_name||'')}"></label>
      </div>
      <footer class="wizard-actions"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button type="button" class="btn primary" data-wizard-next>Avançar para endereço</button></footer>
    </section>

    <section class="wizard-card" data-step-card="2">
      <header class="wizard-card-head"><div><span class="wizard-kicker">ETAPA 2 DE 4</span><h3>Endereço</h3><p>Digite o CEP para preencher automaticamente logradouro, bairro, cidade e UF.</p></div><span class="wizard-card-icon">⌖</span></header>
      <div class="form-grid wizard-fields">
        <label class="cep-field">CEP<div class="input-action"><input name="cep" id="sale-cep" required inputmode="numeric" autocomplete="postal-code" maxlength="9" placeholder="00000-000" value="${esc(formatCep(sale.cep||''))}"><button type="button" class="btn" id="lookup-cep">Consultar</button></div><small id="cep-status" class="field-hint">O ONE CRM consulta múltiplas fontes e mantém os resultados válidos em cache local.</small></label>
        <label>Logradouro<input name="address" id="sale-address" required maxlength="240" autocomplete="address-line1" value="${esc(sale.address||'')}"></label>
        <label>Número<input name="address_number" id="sale-address-number" required maxlength="40" autocomplete="address-line2" value="${esc(sale.address_number||'')}"></label>
        <label>Complemento<input name="complement" maxlength="120" placeholder="Apartamento, bloco, lote..." value="${esc(sale.complement||'')}"></label>
        <label>Bairro<input name="neighborhood" id="sale-neighborhood" required maxlength="120" value="${esc(sale.neighborhood||'')}"></label>
        <label>Cidade<input name="city" id="sale-city" required maxlength="120" autocomplete="address-level2" value="${esc(sale.city||'')}"></label>
        <label>UF<input name="uf" id="sale-uf" required inputmode="text" maxlength="2" autocomplete="address-level1" value="${esc(sale.uf||'')}"></label>
        <label>Tipo de imóvel<select name="property_type">${catalogOptions('property_type',sale.property_type)}</select></label>
      </div>
      <div class="address-note">O preenchimento automático depende de internet no primeiro acesso ao CEP. Depois, o ONE CRM reutiliza o endereço salvo no cache local. Campos continuam editáveis para CEPs gerais ou correções.</div>
      <footer class="wizard-actions"><button type="button" class="btn ghost" data-wizard-back>Voltar</button><button type="button" class="btn primary" data-wizard-next>Avançar para plano</button></footer>
    </section>

    <section class="wizard-card" data-step-card="3">
      <header class="wizard-card-head"><div><span class="wizard-kicker">ETAPA 3 DE 4</span><h3>Plano e faturamento</h3><p>Defina o produto vendido, faturamento e sugestão de agenda.</p></div><span class="wizard-card-icon">▱</span></header>
      <div class="form-grid wizard-fields">
        <label>Plano<select name="plan_id" required>${optionList(state.plans,sale.plan_id,'Selecione o plano')}</select></label>
        ${has('sales.all')?`<label>Vendedor<select name="seller_id" required>${optionList(sellers,sale.seller_id||state.user.id,'Selecione o vendedor')}</select></label>`:''}
        <label>Forma de pagamento<select name="payment_method">${catalogOptions('payment_method',sale.payment_method)}</select></label>
        <label>Vencimento<select name="due_day">${catalogOptions('due_day',sale.due_day)}</select></label>
        <label>Canal de venda<select name="channel">${catalogOptions('sales_channel',sale.channel)}</select></label>
        <label>Sugestão de agendamento<input type="date" name="suggested_date" value="${esc(sale.suggested_date||'')}"></label>
        <label>Sugestão de período<select name="suggested_period">${catalogOptions('period',sale.suggested_period)}</select></label>
        <label class="full">Observações<textarea name="notes" maxlength="5000">${esc(sale.notes||'')}</textarea></label>
      </div>
      <footer class="wizard-actions"><button type="button" class="btn ghost" data-wizard-back>Voltar</button><button type="button" class="btn primary" data-wizard-next>Revisar venda</button></footer>
    </section>

    <section class="wizard-card" data-step-card="4">
      <header class="wizard-card-head"><div><span class="wizard-kicker">ETAPA 4 DE 4</span><h3>Revisão</h3><p>Confira as informações antes de gravar a venda.</p></div><span class="wizard-card-icon">✓</span></header>
      <div id="sale-review" class="review-grid"></div>
      <footer class="wizard-actions"><button type="button" class="btn ghost" data-wizard-back>Voltar e corrigir</button><button type="submit" class="btn primary">${sale.id?'Salvar alterações':'Cadastrar venda'}</button></footer>
    </section>
  </form>`;
}

function validateSaleWizardStep(form, step) {
  const card = $(`[data-step-card="${step}"]`,form);
  for (const input of $$('input,select,textarea',card)) {
    input.setCustomValidity('');
    if (!input.checkValidity()) { input.reportValidity(); input.focus(); return false; }
  }
  if (step===1) {
    const type=form.elements.person_type.value;
    const document=form.elements.cpf_cnpj;
    const documentOk=type==='CNPJ'?validCnpj(document.value):validCpf(document.value);
    if(!documentOk){document.setCustomValidity(`${type} inválido. Confira os números digitados.`);document.reportValidity();document.focus();return false;}
    for(const fieldName of ['phone','contact_phone']){
      const field=form.elements[fieldName];
      if(field.value && !validMobile(field.value)){field.setCustomValidity('Informe um celular válido com DDD, por exemplo (61) 99111-1111.');field.reportValidity();field.focus();return false;}
    }
  }
  if(step===2){
    const cep=form.elements.cep;
    if(onlyNumbers(cep.value,8).length!==8){cep.setCustomValidity('Informe um CEP com 8 números.');cep.reportValidity();cep.focus();return false;}
    const uf=form.elements.uf;
    if(!/^[A-Za-z]{2}$/.test(uf.value)){uf.setCustomValidity('Informe a UF com duas letras.');uf.reportValidity();uf.focus();return false;}
  }
  return true;
}

function updateSaleReview(form) {
  const data=formObject(form);
  const plan=form.elements.plan_id.selectedOptions[0]?.textContent||'-';
  const seller=form.elements.seller_id?.selectedOptions[0]?.textContent||state.user.name;
  const address=[data.address,data.address_number,data.complement,data.neighborhood,`${data.city||''} - ${String(data.uf||'').toUpperCase()}`,formatCep(data.cep)].filter(Boolean).join(', ');
  $('#sale-review').innerHTML=`
    <article class="review-card"><span>Cliente</span><strong>${esc(data.client_name)}</strong><small>${esc(data.person_type)} ${esc(data.cpf_cnpj)}<br>${esc(data.phone)}${data.contact_phone?` · ${esc(data.contact_phone)}`:''}</small></article>
    <article class="review-card"><span>Endereço</span><strong>${esc(address||'-')}</strong><small>${esc(data.property_type||'Tipo de imóvel não informado')}</small></article>
    <article class="review-card"><span>Plano</span><strong>${esc(plan)}</strong><small>${esc(data.payment_method||'Pagamento não informado')} · vencimento ${esc(data.due_day||'-')}</small></article>
    <article class="review-card"><span>Responsável</span><strong>${esc(seller)}</strong><small>${esc(data.channel||'Canal não informado')}</small></article>`;
}

async function openSaleForm(sale=null, fromRoute=false) {
  await ensureReferenceData();
  if (fromRoute) navigate('sales');
  modal(sale?'Editar venda':'Nova venda',saleFormHtml(sale||{}),{wide:true});
  const form=$('#sale-form');
  let currentStep=1;
  let cepTimer=null;
  let lastCep='';

  const showStep=step=>{
    currentStep=Math.max(1,Math.min(4,Number(step)||1));
    $$('[data-step-card]',form).forEach(card=>card.classList.toggle('active',Number(card.dataset.stepCard)===currentStep));
    $$('[data-wizard-step]',form).forEach(button=>{
      const number=Number(button.dataset.wizardStep);
      button.classList.toggle('active',number===currentStep);
      button.classList.toggle('done',number<currentStep);
    });
    if(currentStep===4) updateSaleReview(form);
    $('.modal',document)?.scrollTo({top:0,behavior:'smooth'});
  };

  const typeField=form.elements.person_type;
  const documentField=form.elements.cpf_cnpj;
  const applyDocumentMask=()=>{
    const type=typeField.value;
    $('#document-label').textContent=type;
    documentField.placeholder=type==='CNPJ'?'00.000.000/0000-00':'000.000.000-00';
    documentField.maxLength=type==='CNPJ'?18:14;
    documentField.value=formatDocument(documentField.value,type);
    documentField.setCustomValidity('');
  };
  typeField.addEventListener('change',applyDocumentMask);
  documentField.addEventListener('input',applyDocumentMask);
  for(const name of ['phone','contact_phone']){
    form.elements[name].addEventListener('input',event=>{event.target.value=formatPhone(event.target.value);event.target.setCustomValidity('');});
    form.elements[name].addEventListener('blur',event=>{if(event.target.value)event.target.value=normalizeMobileInput(event.target.value);});
  }
  form.elements.cep.addEventListener('input',event=>{
    event.target.value=formatCep(event.target.value);event.target.setCustomValidity('');
    clearTimeout(cepTimer);
    if(onlyNumbers(event.target.value,8).length===8) cepTimer=setTimeout(()=>lookupCep(false),350);
  });
  form.elements.uf.addEventListener('input',event=>event.target.value=event.target.value.replace(/[^A-Za-z]/g,'').toUpperCase().slice(0,2));

  let cepRequestId=0;
  async function lookupCep(force=true){
    const cep=onlyNumbers(form.elements.cep.value,8);
    const status=$('#cep-status');
    const button=$('#lookup-cep');
    if(cep.length!==8){if(force){form.elements.cep.setCustomValidity('Informe um CEP com 8 números.');form.elements.cep.reportValidity();}return;}
    if(!force && cep===lastCep) return;
    const requestId=++cepRequestId;
    status.className='field-hint loading';status.textContent='Consultando CEP em múltiplas fontes...';button.disabled=true;
    let address=null;
    try{
      try {
        const response=await api(`/api/cep/${cep}${force?'?refresh=1':''}`);
        address=response.address;
      } catch (serverError) {
        if(requestId!==cepRequestId) return;
        status.textContent='Servidor indisponível para CEP. Tentando consulta direta pelo navegador...';
        try { address=await lookupCepInBrowser(cep); }
        catch (_) { throw serverError; }
      }
      if(requestId!==cepRequestId || onlyNumbers(form.elements.cep.value,8)!==cep) return;
      const a=address||{};
      form.elements.address.value=a.street||'';
      if(a.complement && !form.elements.complement.value) form.elements.complement.value=a.complement;
      form.elements.neighborhood.value=a.neighborhood||'';
      form.elements.city.value=a.city||'';
      form.elements.uf.value=a.uf||'';
      lastCep=cep;
      status.className='field-hint success';
      status.textContent=a.warning||`Endereço encontrado por ${a.source}${a.browserFallback?' (consulta direta)':''}.`;
      (a.street?form.elements.address_number:form.elements.address).focus();
    }catch(error){
      if(requestId!==cepRequestId) return;
      lastCep='';
      status.className='field-hint error';status.textContent=error.message;
      if(force) toast(error.message,'error');
    }finally{if(requestId===cepRequestId)button.disabled=false;}
  }
  $('#lookup-cep').addEventListener('click',()=>lookupCep(true));

  $$('[data-wizard-next]',form).forEach(button=>button.addEventListener('click',()=>{if(validateSaleWizardStep(form,currentStep))showStep(currentStep+1);}));
  $$('[data-wizard-back]',form).forEach(button=>button.addEventListener('click',()=>showStep(currentStep-1)));
  $$('[data-wizard-step]',form).forEach(button=>button.addEventListener('click',()=>{
    const target=Number(button.dataset.wizardStep);
    if(target<currentStep) showStep(target);
    else if(target===currentStep+1 && validateSaleWizardStep(form,currentStep)) showStep(target);
  }));

  form.addEventListener('submit',async e=>{
    e.preventDefault();
    for(let step=1;step<=3;step++){if(!validateSaleWizardStep(form,step)){showStep(step);return;}}
    const button=$('button[type=submit]',form);button.disabled=true;
    try{
      const payload=formObject(form);
      payload.cpf_cnpj=onlyNumbers(payload.cpf_cnpj,payload.person_type==='CNPJ'?14:11);
      payload.phone=onlyNumbers(payload.phone,13);
      payload.contact_phone=onlyNumbers(payload.contact_phone,13);
      payload.cep=onlyNumbers(payload.cep,8);
      payload.uf=String(payload.uf||'').toUpperCase();
      const result=await api(sale?`/api/sales/${sale.id}`:'/api/sales',{method:sale?'PUT':'POST',body:payload});
      closeModal();toast(result.message||'Venda salva.');await renderRoute();
      if (!sale && result.id) setTimeout(()=>openSaleDetail(result.id),150);
    }catch(error){toast(error.message,'error');}
    finally{button.disabled=false;}
  });
  applyDocumentMask();showStep(1);
}

async function openSaleDetail(id) {
  try {
    await ensureReferenceData();
    const data = await api(`/api/sales/${id}`);
    state.currentSale = data.sale;
    const s = data.sale;
    const canGeneral = has('sales.edit_all') || (has('sales.edit_own') && s.seller_id===state.user.id);
    const canWorkflow = has('workflow.bko');
    drawer(`Venda #${s.id} · ${s.client_name}`, `
      <div class="grid-2">
        <section class="panel"><header class="panel-head"><h3>Cliente</h3></header><div class="panel-body">
          <div class="metric-row"><span>Nome</span><strong>${esc(s.client_name)}</strong></div>
          <div class="metric-row"><span>CPF/CNPJ</span><strong>${esc(formatDocument(s.cpf_cnpj||'',s.person_type||'CPF')||'-')}</strong></div>
          <div class="metric-row"><span>Telefone</span><strong>${esc(formatPhone(s.phone))}</strong></div>
          <div class="metric-row"><span>Endereço</span><strong>${esc([s.address,s.address_number,s.city,s.uf].filter(Boolean).join(', ')||'-')}</strong></div>
        </div></section>
        <section class="panel"><header class="panel-head"><h3>Venda</h3></header><div class="panel-body">
          <div class="metric-row"><span>Vendedor</span><strong>${esc(s.seller_name)}</strong></div>
          <div class="metric-row"><span>Equipe</span><strong>${esc(s.team_name||'-')}</strong></div>
          <div class="metric-row"><span>Plano</span><strong>${esc(s.plan_name_snapshot)}</strong></div>
          <div class="metric-row"><span>Valor</span><strong>${money(s.plan_price_snapshot)}</strong></div>
        </div></section>
      </div>
      <section class="panel"><header class="panel-head"><h3>Fluxo operacional</h3>${canWorkflow?'<button class="btn small primary" id="edit-workflow">Tratar venda</button>':''}</header><div class="panel-body grid-2">
        <div class="metric-row"><span>Status geral</span>${badge(s.status_label,s.status)}</div>
        <div class="metric-row"><span>Responsável BKO</span><strong>${esc(s.bko_name||'Não atribuído')}</strong></div>
        <div class="metric-row"><span>Ativação</span>${badge(s.activation_status_label,s.activation_status)}</div>
        <div class="metric-row"><span>Biometria</span>${badge(s.biometric_status_label,s.biometric_status)}</div>
        <div class="metric-row"><span>Instalação</span>${badge(s.installation_status_label,s.installation_status)}</div>
        <div class="metric-row"><span>Agendamento</span><strong>${s.appointment_date?`${fmtDate(s.appointment_date)} ${esc(s.appointment_period||'')}`:'-'}</strong></div>
        <div class="metric-row"><span>OS</span><strong>${esc(s.os_number||'-')}</strong></div>
        <div class="metric-row"><span>Criada em</span><strong>${fmtDateTime(s.created_at)}</strong></div>
      </div></section>
      ${s.notes?`<section class="panel"><header class="panel-head"><h3>Observações</h3></header><div class="panel-body">${esc(s.notes).replace(/\n/g,'<br>')}</div></section>`:''}
      <section class="panel"><header class="panel-head"><h3>Timeline</h3></header><div class="panel-body timeline">${data.history.length?data.history.map(h=>`<article class="timeline-item"><strong>${esc(historyTitle(h))}</strong><small>${esc(h.user_name||'Sistema')} · ${fmtDateTime(h.created_at)}</small>${h.old_value||h.new_value?`<p>${esc(h.old_value||'-')} → ${esc(h.new_value||'-')}</p>`:''}</article>`).join(''):'<div class="empty">Nenhum evento registrado.</div>'}</div></section>
      <div class="page-actions" style="justify-content:flex-end">${canGeneral?'<button class="btn" id="edit-general">Editar cadastro</button>':''}</div>
    `);
    $('#edit-general')?.addEventListener('click',()=>{closeModal();openSaleForm(s);});
    $('#edit-workflow')?.addEventListener('click',()=>openWorkflowForm(s));
  } catch(error) { toast(error.message,'error'); }
}

function historyTitle(h) {
  if (h.event_type==='created') return 'Venda criada';
  if (h.event_type==='workflow_update') return `Fluxo: ${h.field_name}`;
  if (h.event_type==='general_update') return `Cadastro: ${h.field_name}`;
  return h.event_type;
}

function openWorkflowForm(sale) {
  const bkos = state.users.filter(u=>u.active && ['bko','manager','owner'].includes(baseRole(u)));
  modal(`Tratamento da venda #${sale.id}`,`<form id="workflow-form" class="form-grid">
    <div class="form-section">Responsabilidade</div>
    ${has('workflow.assign')?`<label>Responsável BKO<select name="bko_user_id">${optionList(bkos,sale.bko_user_id,'Não atribuído')}</select></label>`:''}
    <label>Status geral<select name="status">${catalogOptions('sale_status',sale.status)}</select></label>
    <div class="form-section">Ativação</div>
    <label>Status da ativação<select name="activation_status">${catalogOptions('activation_status',sale.activation_status)}</select></label>
    <label class="switch-row">Bypass necessário?<input type="checkbox" name="bypass_required" ${sale.bypass_required?'checked':''}></label>
    <div class="form-section">Biometria</div>
    <label>Status da biometria<select name="biometric_status">${catalogOptions('biometric_status',sale.biometric_status)}</select></label>
    <label class="switch-row">Tratando biometria?<input type="checkbox" name="handling_biometric" ${sale.handling_biometric?'checked':''}></label>
    <div class="form-section">Instalação e agenda</div>
    <label>Status da instalação<select name="installation_status">${catalogOptions('installation_status',sale.installation_status)}</select></label>
    <label class="switch-row">Tratando eficácia?<input type="checkbox" name="handling_installation" ${sale.handling_installation?'checked':''}></label>
    <label>Status do agendamento<select name="appointment_status">${catalogOptions('appointment_status',sale.appointment_status)}</select></label>
    <label>Data do agendamento<input type="date" name="appointment_date" value="${esc(sale.appointment_date||'')}"></label>
    <label>Período<select name="appointment_period">${catalogOptions('period',sale.appointment_period)}</select></label>
    <label>Ordem de serviço<input name="os_number" value="${esc(sale.os_number||'')}"></label>
    <label>Motivo do cancelamento<select name="cancelled_reason">${catalogOptions('cancellation_reason',sale.cancelled_reason)}</select></label>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar tratamento</button></div>
  </form>`,{wide:true});
  $$('[data-close-modal]').forEach(el=>el.addEventListener('click',closeModal));
  $('#workflow-form').addEventListener('submit',async e=>{
    e.preventDefault();
    try{
      const result=await api(`/api/sales/${sale.id}/workflow`,{method:'PUT',body:formObject(e.currentTarget)});
      closeModal();toast(result.message);await renderRoute();setTimeout(()=>openSaleDetail(sale.id),120);
    }catch(error){toast(error.message,'error');}
  });
}

async function renderBko() {
  setPage('Gestão BKO','ATIVAÇÃO · BIOMETRIA · INSTALAÇÃO');
  await ensureReferenceData();
  const data = await api('/api/sales');
  const queue = data.sales.filter(s=>!['instalada','cancelada'].includes(s.status));
  $('#content').innerHTML = `
    <div class="page-head"><div><h1>Fila operacional</h1><p class="muted">Vendas disponíveis ou atribuídas ao seu tratamento.</p></div></div>
    <div class="cards">
      <article class="stat-card" style="--accent:var(--amber)"><div class="stat-top"><span>Na fila</span><span>◷</span></div><div class="stat-value">${queue.length}</div><div class="stat-note">Aguardando conclusão</div></article>
      <article class="stat-card" style="--accent:var(--violet)"><div class="stat-top"><span>Biometria pendente</span><span>◉</span></div><div class="stat-value">${queue.filter(s=>!['biometria_ok','biometria_bko'].includes(s.biometric_status)).length}</div><div class="stat-note">Exige acompanhamento</div></article>
      <article class="stat-card" style="--accent:var(--blue)"><div class="stat-top"><span>Agendadas</span><span>▦</span></div><div class="stat-value">${queue.filter(s=>s.appointment_date).length}</div><div class="stat-note">Com data definida</div></article>
      <article class="stat-card" style="--accent:var(--cyan)"><div class="stat-top"><span>Sem responsável</span><span>◎</span></div><div class="stat-value">${queue.filter(s=>!s.bko_user_id).length}</div><div class="stat-note">Podem ser assumidas</div></article>
    </div>
    <section class="panel"><header class="panel-head"><h3>Vendas em tratamento</h3><span class="muted">${queue.length} registro(s)</span></header>${salesTable(queue)}</section>`;
  bindSaleRows();
}

async function renderDaily(params=new URLSearchParams()) {
  setPage('Análise do dia','RESULTADO POR EQUIPE');
  const selected = params.get('date') || new Date().toISOString().slice(0,10);
  const data = await api('/api/daily-analysis?' + qs({date:selected}));
  const total = data.teams.reduce((sum,item)=>sum+Number(item.sales||0),0);
  $('#content').innerHTML = `
    <div class="page-head"><div><h1>Produção diária</h1><p class="muted">Cada venda é contada pela data de cadastro.</p></div>
      <form id="daily-date" class="filters"><input type="date" name="date" value="${esc(selected)}"><button class="btn primary">Atualizar</button></form></div>
    <div class="cards"><article class="stat-card"><div class="stat-top"><span>Total do dia</span><span>↗</span></div><div class="stat-value">${total}</div><div class="stat-note">${fmtDate(selected)}</div></article>
      <article class="stat-card"><div class="stat-top"><span>Equipes com venda</span><span>◫</span></div><div class="stat-value">${data.teams.length}</div><div class="stat-note">Produção registrada</div></article></div>
    <section class="panel"><header class="panel-head"><h3>Resultado por equipe</h3></header><div class="panel-body grid-3">${data.teams.length?data.teams.map(t=>`<article class="team-card"><h4>${esc(t.team_name)}</h4><div class="metric-row"><span>Vendas</span><strong>${t.sales}</strong></div><div class="metric-row"><span>Instaladas</span><strong>${t.installed||0}</strong></div><div class="metric-row"><span>Canceladas</span><strong>${t.cancelled||0}</strong></div><div class="progress"><span style="width:${total?Math.round(t.sales*100/total):0}%"></span></div></article>`).join(''):'<div class="empty">Nenhuma venda nesta data.</div>'}</div></section>
    <section class="panel"><header class="panel-head"><h3>Vendedores</h3></header><div class="table-wrap"><table class="data-table"><thead><tr><th>Vendedor</th><th>Equipe</th><th>Vendas</th><th>Instaladas</th></tr></thead><tbody>${data.sellers.map(s=>`<tr><td class="cell-main">${esc(s.seller_name)}</td><td>${esc(s.team_name)}</td><td>${s.sales}</td><td>${s.installed||0}</td></tr>`).join('')}</tbody></table></div></section>`;
  $('#daily-date').addEventListener('submit',e=>{e.preventDefault();navigate('daily',qs(formObject(e.currentTarget)));});
}

async function renderRanking(params=new URLSearchParams()) {
  setPage('Ranking','DESEMPENHO COMERCIAL');
  const period=params.get('period')||'month';
  const data=await api('/api/ranking?'+qs({period}));
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Ranking ${period==='month'?'do mês':'geral'}</h1><p class="muted">Pontuação: instaladas × 100 + vendas × 10 − canceladas × 5.</p></div>
      <div class="filters"><button class="btn ${period==='month'?'primary':''}" onclick="navigate('ranking','period=month')">Mês</button><button class="btn ${period==='all'?'primary':''}" onclick="navigate('ranking','period=all')">Geral</button></div></div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Posição</th><th>Vendedor</th><th>Equipe</th><th>Vendas</th><th>Instaladas</th><th>Canceladas</th><th>Conversão</th><th>Pontos</th></tr></thead><tbody>${data.ranking.map(r=>`<tr><td><span class="badge ${r.position<=3?'amber':'cyan'}">#${r.position}</span></td><td class="cell-main">${esc(r.name)}</td><td>${esc(r.team_name)}</td><td>${r.total}</td><td>${r.installed}</td><td>${r.cancelled}</td><td>${r.conversion}%</td><td class="cell-main">${r.points}</td></tr>`).join('')}</tbody></table></div>${!data.ranking.length?'<div class="empty">Nenhum vendedor encontrado.</div>':''}</section>`;
}

function aiText(value) {
  return esc(value).replace(/\n/g,'<br>');
}

function renderAIMessages() {
  const container=$('#ai-messages');
  if(!container) return;
  container.innerHTML=state.aiMessages.length?state.aiMessages.map(message=>`
    <article class="ai-message ${message.role}">
      <div class="ai-message-head"><strong>${message.role==='assistant'?'ONE Intelligence':'Você'}</strong>${message.meta?`<small>${esc(message.meta)}</small>`:''}</div>
      <div class="ai-message-body">${aiText(message.text)}</div>
    </article>`).join(''):'<div class="ai-empty">Faça uma pergunta operacional ou use uma das sugestões rápidas.</div>';
  container.scrollTop=container.scrollHeight;
}

async function sendAIQuestion(questionOverride='') {
  const form=$('#ai-form');
  const questionInput=$('#ai-question');
  const saleInput=$('#ai-sale-id');
  const button=$('#ai-send');
  const question=(questionOverride || questionInput?.value || '').trim();
  if(!question){toast('Digite uma pergunta.','error');return;}
  state.aiMessages.push({role:'user',text:question});
  renderAIMessages();
  if(questionInput) questionInput.value='';
  if(button){button.disabled=true;button.textContent='Analisando...';}
  try{
    const result=await api('/api/ai/ask',{method:'POST',body:{question,sale_id:saleInput?.value||null}});
    const usage=result.usage||{};
    const meta=[result.model,usage.total_tokens?`${usage.total_tokens} tokens`:null].filter(Boolean).join(' · ');
    state.aiMessages.push({role:'assistant',text:result.answer,meta});
    renderAIMessages();
  }catch(error){
    state.aiMessages.push({role:'assistant',text:`Não foi possível concluir a análise: ${error.message}`});
    renderAIMessages();
    toast(error.message,'error');
  }finally{
    if(button){button.disabled=false;button.textContent='Perguntar ao ONE';}
  }
}

async function renderIntelligence() {
  setPage('Inteligência','ONE INTELLIGENCE');
  const [local,statusResult]=await Promise.all([
    api('/api/intelligence'),
    api('/api/ai/status').catch(error=>({openai:{ready:false,configured:false,permission:false,error:error.message}})),
  ]);
  const ai=statusResult.openai||{};
  const aiAvailable=Boolean(ai.ready && ai.permission);
  const quickPrompts=[
    'Resuma as principais pendências da operação e indique prioridades.',
    'Quais riscos operacionais aparecem nos indicadores atuais?',
    'Sugira um plano de ação curto para melhorar a conversão.',
    'Liste os pontos que merecem acompanhamento hoje.',
  ];
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>ONE Intelligence</h1><p class="muted">Análise local e assistente OpenAI com acesso limitado ao escopo do seu cargo.</p></div><button class="btn" onclick="renderRoute()">Atualizar</button></div>
    <section class="panel ai-panel">
      <header class="panel-head"><div><h3>Assistente operacional</h3><small class="muted">${ai.ready?`Modelo ${esc(ai.model)}`:'Configuração da OpenAI pendente'}</small></div>${ai.ready?badge('OpenAI conectada','ok'):badge('OpenAI não configurada','aguard')}</header>
      <div class="panel-body">
        ${!ai.permission?'<div class="integration-notice warning"><strong>Seu cargo não possui a permissão “Utilizar o assistente ONE Intelligence com OpenAI”.</strong><span>O Dono pode liberar essa opção em Cargos e permissões.</span></div>':''}
        ${ai.permission&&!ai.ready?'<div class="integration-notice warning"><strong>A chave da OpenAI ainda não foi configurada no Railway.</strong><span>Adicione OPENAI_API_KEY nas Variables do serviço e publique novamente.</span></div>':''}
        <div class="ai-layout ${aiAvailable?'':'disabled'}">
          <div class="ai-chat">
            <div id="ai-messages" class="ai-messages" aria-live="polite"></div>
            <form id="ai-form" class="ai-form">
              <label class="ai-sale-field">Venda específica <span class="muted">(opcional)</span><input id="ai-sale-id" name="sale_id" type="number" min="1" placeholder="Ex.: 152" ${aiAvailable?'':'disabled'}></label>
              <label class="ai-question-field">Pergunta<textarea id="ai-question" name="question" maxlength="2000" rows="4" placeholder="Ex.: Quais vendas exigem prioridade hoje?" ${aiAvailable?'':'disabled'}></textarea></label>
              <div class="ai-form-actions"><small class="muted">A IA recebe indicadores e dados operacionais sem CPF, telefone, e-mail ou endereço completo.</small><button id="ai-send" class="btn primary" ${aiAvailable?'':'disabled'}>Perguntar ao ONE</button></div>
            </form>
          </div>
          <aside class="ai-suggestions"><strong>Sugestões rápidas</strong>${quickPrompts.map((prompt,index)=>`<button type="button" class="ai-quick" data-ai-quick="${index}" ${aiAvailable?'':'disabled'}>${esc(prompt)}</button>`).join('')}</aside>
        </div>
      </div>
    </section>
    <section class="panel"><header class="panel-head"><div><h3>Alertas operacionais locais</h3><small class="muted">Gerados sem consumo da API.</small></div><span class="badge cyan">${local.insights.length}</span></header><div class="panel-body">${local.insights.length?local.insights.map(i=>`<article class="insight ${i.severity}"><h4>${esc(i.title)}</h4><p>${esc(i.description)}</p>${i.sale_id?`<button class="btn small ghost" style="margin-top:10px" onclick="openSaleDetail(${i.sale_id})">Abrir venda</button>`:''}</article>`).join(''):'<div class="empty">Nenhum alerta relevante.</div>'}</div></section>`;
  renderAIMessages();
  $('#ai-form')?.addEventListener('submit',e=>{e.preventDefault();sendAIQuestion();});
  $$('[data-ai-quick]').forEach(button=>button.addEventListener('click',()=>sendAIQuestion(quickPrompts[Number(button.dataset.aiQuick)])));
}

async function renderPowerBI() {
  setPage('Power BI','RELATÓRIO INCORPORADO');
  const data=await api('/api/powerbi');
  if(!data.embed_url){
    $('#content').innerHTML=`<div class="page-head"><div><h1>Power BI</h1><p class="muted">Nenhuma URL de incorporação foi configurada.</p></div></div><section class="panel"><div class="empty">Peça ao Dono para configurar a URL em Administração → Integrações.</div></section>`;
    return;
  }
  $('#content').innerHTML=`<div class="page-head"><div><h1>Painel Power BI</h1><p class="muted">Conteúdo fornecido pelo endereço configurado pelo Dono.</p></div><a class="btn" href="${esc(data.embed_url)}" target="_blank" rel="noopener">Abrir em nova guia</a></div><section class="panel" style="height:calc(100vh - 170px);min-height:520px"><iframe title="Power BI" src="${esc(data.embed_url)}" style="width:100%;height:100%;border:0;background:#fff" allowfullscreen></iframe></section>`;
}

async function loadRoles() {
  const data = await api('/api/roles');
  state.roles = data.roles || [];
  state.roleData = data;
  return data;
}

async function renderUsers() {
  setPage('Funcionários','USUÁRIOS E ACESSOS');
  const [u,t,r]=await Promise.all([api('/api/users'),api('/api/teams'),loadRoles()]);
  state.users=u.users;state.teams=t.teams;state.roles=r.roles||[];
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Funcionários</h1><p class="muted">Cargos controlam o acesso no servidor, não apenas os botões.</p></div>${has('users.manage')?'<button class="btn primary" id="new-user">＋ Novo usuário</button>':''}</div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Usuário</th><th>Cargo</th><th>Equipe</th><th>Status</th><th>Último acesso</th><th></th></tr></thead><tbody>${state.users.map(u=>`<tr><td><div class="cell-main">${esc(u.name)}</div><div class="cell-sub">${esc(u.email)}</div></td><td>${badge(u.role_name||roleLabel(u.role_code),u.base_role||u.role_code)}</td><td>${esc(u.team_name||'-')}</td><td>${u.active?badge('Ativo','ok'):badge('Bloqueado','cancelada')}</td><td>${fmtDateTime(u.last_login_at)}</td><td>${has('users.manage')?`<button class="btn small" onclick="openUserForm(${u.id})">Editar</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
  $('#new-user')?.addEventListener('click',()=>openUserForm());
}

function openUserForm(id=null) {
  const user=id?state.users.find(x=>x.id===id):{};
  const roleOptions=state.roles
    .filter(role=>role.active || role.code===user?.role_code)
    .map(role=>`<option value="${esc(role.code)}" ${user?.role_code===role.code?'selected':''}>${esc(role.name)}${role.active?'':' (inativo)'}</option>`).join('');
  modal(id?'Editar usuário':'Novo usuário',`<form id="user-form" class="form-grid">
    <label>Nome<input name="name" required value="${esc(user?.name||'')}"></label>
    <label>E-mail<input type="email" name="email" required value="${esc(user?.email||'')}"></label>
    <label>Cargo<select name="role_code" required>${roleOptions}</select></label>
    <label>Equipe<select name="team_id">${optionList(state.teams,user?.team_id,'Sem equipe')}</select></label>
    <label>${id?'Nova senha (opcional)':'Senha inicial'}<input type="password" name="password" ${id?'':'required'} minlength="8"></label>
    <label class="switch-row">Exigir troca de senha<input type="checkbox" name="must_change_password" ${id?'':'checked'}></label>
    ${id?`<label class="switch-row full">Usuário ativo<input type="checkbox" name="active" ${user.active?'checked':''}></label>`:''}
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $$('[data-close-modal]').forEach(el=>el.addEventListener('click',closeModal));
  $('#user-form').addEventListener('submit',async e=>{e.preventDefault();try{const payload=formObject(e.currentTarget);if(id&&!payload.password)delete payload.password;await api(id?`/api/users/${id}`:'/api/users',{method:id?'PUT':'POST',body:payload});closeModal();state.users=[];toast('Usuário salvo.');renderUsers();}catch(error){toast(error.message,'error');}});
}

async function renderTeams() {
  setPage('Equipes','ESTRUTURA COMERCIAL');
  const [t,u]=await Promise.all([api('/api/teams'),api('/api/users').catch(()=>({users:[]}))]);
  state.teams=t.teams;if(u.users?.length)state.users=u.users;
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Equipes</h1><p class="muted">Metas e responsáveis configurados sem editar arquivos.</p></div>${has('teams.manage')?'<button class="btn primary" id="new-team">＋ Nova equipe</button>':''}</div>
    <div class="grid-3">${state.teams.map(t=>`<article class="team-card"><div style="display:flex;justify-content:space-between"><h4>${esc(t.name)}</h4>${t.active?badge('Ativa','ok'):badge('Inativa','cancelada')}</div><div class="metric-row"><span>Gerente</span><strong>${esc(t.manager_name||'-')}</strong></div><div class="metric-row"><span>Funcionários</span><strong>${t.members}</strong></div><div class="metric-row"><span>Meta mensal</span><strong>${t.monthly_target}</strong></div>${has('teams.manage')?`<button class="btn small" onclick="openTeamForm(${t.id})">Editar</button>`:''}</article>`).join('')}</div>`;
  $('#new-team')?.addEventListener('click',()=>openTeamForm());
}

function openTeamForm(id=null) {
  const team=id?state.teams.find(x=>x.id===id):{};
  const managers=state.users.filter(u=>u.active&&['manager','owner'].includes(baseRole(u)));
  modal(id?'Editar equipe':'Nova equipe',`<form id="team-form" class="form-grid">
    <label>Nome<input name="name" required value="${esc(team?.name||'')}"></label>
    <label>Gerente<select name="manager_id">${optionList(managers,team?.manager_id,'Sem gerente')}</select></label>
    <label>Meta mensal<input type="number" min="0" name="monthly_target" value="${team?.monthly_target||0}"></label>
    ${id?`<label class="switch-row">Equipe ativa<input type="checkbox" name="active" ${team.active?'checked':''}></label>`:''}
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $$('[data-close-modal]').forEach(el=>el.addEventListener('click',closeModal));
  $('#team-form').addEventListener('submit',async e=>{e.preventDefault();try{await api(id?`/api/teams/${id}`:'/api/teams',{method:id?'PUT':'POST',body:formObject(e.currentTarget)});closeModal();state.teams=[];toast('Equipe salva.');renderTeams();}catch(error){toast(error.message,'error');}});
}

async function renderPlans() {
  setPage('Planos','CATÁLOGO COMERCIAL');
  await ensureReferenceData();
  const data=await api('/api/plans?all=1');state.plans=data.plans;
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Planos e serviços</h1><p class="muted">O cadastro alimenta diretamente o formulário de venda.</p></div><button class="btn primary" id="new-plan">＋ Novo plano</button></div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Plano</th><th>Operadora</th><th>Serviço</th><th>Velocidade</th><th>Preço</th><th>UFs</th><th>Status</th><th></th></tr></thead><tbody>${state.plans.map(p=>`<tr><td><div class="cell-main">${esc(p.name)}</div><div class="cell-sub">${esc(p.benefits||'')}</div></td><td>${esc(p.provider)}</td><td>${esc(p.service)}</td><td>${esc(p.speed||'-')}</td><td>${money(p.price)}</td><td>${esc(p.uf_list||'Todas')}</td><td>${p.active?badge('Ativo','ok'):badge('Inativo','cancelada')}</td><td><button class="btn small" onclick="openPlanForm(${p.id})">Editar</button></td></tr>`).join('')}</tbody></table></div></section>`;
  $('#new-plan').addEventListener('click',()=>openPlanForm());
}

function openPlanForm(id=null) {
  const p=id?state.plans.find(x=>x.id===id):{};
  modal(id?'Editar plano':'Novo plano',`<form id="plan-form" class="form-grid">
    <label>Operadora<input name="provider" required value="${esc(p?.provider||'')}"></label>
    <label>Serviço<input name="service" required value="${esc(p?.service||'')}"></label>
    <label>Nome do plano<input name="name" required value="${esc(p?.name||'')}"></label>
    <label>Velocidade<input name="speed" value="${esc(p?.speed||'')}"></label>
    <label>Preço<input name="price" required inputmode="decimal" value="${esc(p?.price??'')}"></label>
    <label>Ordem<input type="number" name="sort_order" value="${p?.sort_order||0}"></label>
    <label class="full">Benefícios<textarea name="benefits">${esc(p?.benefits||'')}</textarea></label>
    <label class="full">UFs disponíveis <small class="muted">Separadas por vírgula; vazio significa todas.</small><input name="uf_list" value="${esc(p?.uf_list||'')}"></label>
    <label class="switch-row full">Plano ativo<input type="checkbox" name="active" ${p?.active!==0?'checked':''}></label>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $$('[data-close-modal]').forEach(el=>el.addEventListener('click',closeModal));
  $('#plan-form').addEventListener('submit',async e=>{e.preventDefault();try{await api(id?`/api/plans/${id}`:'/api/plans',{method:id?'PUT':'POST',body:formObject(e.currentTarget)});closeModal();state.plans=[];toast('Plano salvo.');renderPlans();}catch(error){toast(error.message,'error');}});
}

const categoryLabels={provider:'Operadoras',service:'Serviços',sale_status:'Status da venda',activation_status:'Ativação',biometric_status:'Biometria',installation_status:'Instalação',appointment_status:'Agendamento',payment_method:'Formas de pagamento',due_day:'Vencimentos',sales_channel:'Canais de venda',period:'Períodos',property_type:'Tipos de imóvel',cancellation_reason:'Motivos de cancelamento'};
async function renderCatalogs() {
  setPage('Catálogos','CONFIGURAÇÕES DO SISTEMA');
  const data=await api('/api/catalogs?all=1');state.catalogs=data.catalogs;
  const categories=Object.keys({...categoryLabels,...state.catalogs});
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Opções configuráveis</h1><p class="muted">Itens usados em vendas antigas são desativados, não apagados.</p></div><button class="btn primary" id="new-catalog">＋ Novo item</button></div>
    <div class="grid-2">${categories.map(cat=>`<section class="panel"><header class="panel-head"><h3>${esc(categoryLabels[cat]||cat)}</h3><span class="badge cyan">${(state.catalogs[cat]||[]).length}</span></header><div class="panel-body">${(state.catalogs[cat]||[]).map(i=>`<div class="team-card" style="margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;gap:10px"><div><strong>${esc(i.label)}</strong><div class="code">${esc(i.code)}</div></div><div class="actions">${i.active?badge('Ativo','ok'):badge('Inativo','cancelada')}<button class="btn small" onclick="openCatalogForm(${i.id},'${esc(cat)}')">Editar</button></div></div>`).join('')||'<div class="empty">Sem itens.</div>'}</div></section>`).join('')}</div>`;
  $('#new-catalog').addEventListener('click',()=>openCatalogForm());
}
function openCatalogForm(id=null,category='') {
  const all=Object.values(state.catalogs).flat();const item=id?all.find(x=>x.id===id):{};
  modal(id?'Editar item':'Novo item',`<form id="catalog-form" class="form-grid">
    <label>Categoria<input name="category" required ${id?'disabled':''} value="${esc(item?.category||category)}" list="categories-list"><datalist id="categories-list">${Object.keys(categoryLabels).map(x=>`<option value="${x}">`).join('')}</datalist></label>
    <label>Código<input name="code" required value="${esc(item?.code||'')}"></label>
    <label>Descrição<input name="label" required value="${esc(item?.label||'')}"></label>
    <label>Ordem<input type="number" name="sort_order" value="${item?.sort_order||0}"></label>
    ${id?`<label class="switch-row full">Item ativo<input type="checkbox" name="active" ${item.active?'checked':''}></label>`:''}
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $$('[data-close-modal]').forEach(el=>el.addEventListener('click',closeModal));
  $('#catalog-form').addEventListener('submit',async e=>{e.preventDefault();try{const payload=formObject(e.currentTarget);if(id)delete payload.category;await api(id?`/api/catalogs/${id}`:'/api/catalogs',{method:id?'PUT':'POST',body:payload});closeModal();state.catalogs={};toast('Catálogo salvo.');renderCatalogs();}catch(error){toast(error.message,'error');}});
}

function permissionModules(data=state.roleData) {
  const modules={};
  (data?.permissions||[]).forEach(permission=>(modules[permission.module]??=[]).push(permission));
  return modules;
}

function rolePermissionsMarkup(role, modules, prefix='role') {
  const selected=new Set(role?.permissions||[]);
  return Object.entries(modules).map(([module,permissions])=>`<div class="permission-module"><h4>${esc(module)}</h4><div class="check-list">${permissions.map(permission=>`<label class="check-item"><input type="checkbox" value="${esc(permission.code)}" ${selected.has(permission.code)?'checked':''}><span>${esc(permission.description)}</span></label>`).join('')}</div></div>`).join('');
}

async function renderRoles() {
  setPage('Cargos e permissões','CONTROLE DE ACESSO');
  const data=await loadRoles();
  const modules=permissionModules(data);
  const editableRoles=data.roles.filter(role=>role.code!=='owner');
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Cargos e permissões</h1><p class="muted">Crie cargos próprios e escolha exatamente o que cada grupo pode acessar. O Dono continua com acesso total.</p></div><button class="btn primary" id="new-role">＋ Novo cargo</button></div>
    <div class="grid-2">${editableRoles.map(role=>`<section class="panel"><header class="panel-head"><div><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><h3>${esc(role.name)}</h3>${role.is_system?badge('Nativo','cyan'):badge('Personalizado','green')}${role.active?badge('Ativo','ok'):badge('Inativo','cancelada')}</div><p class="muted" style="margin-top:6px">${esc(role.description||'Sem descrição')} · Base: ${esc(nativeRoleLabels[role.base_role]||role.base_role)} · ${role.users_count||0} usuário(s)</p></div><div class="actions">${!role.is_system?`<button class="btn small" onclick="openRoleForm('${esc(role.code)}')">Editar</button>`:''}<button class="btn small primary" onclick="saveRole('${esc(role.code)}')">Salvar permissões</button></div></header><div class="panel-body permission-grid" data-role-box="${esc(role.code)}">${rolePermissionsMarkup(role,modules)}</div></section>`).join('')}</div>`;
  $('#new-role').addEventListener('click',()=>openRoleForm());
}

async function saveRole(role){
  const permissions=$$(`[data-role-box="${role}"] input:checked`).map(x=>x.value);
  try{await api(`/api/roles/${encodeURIComponent(role)}`,{method:'PUT',body:{permissions}});toast(`Permissões de ${roleLabel(role)} atualizadas.`);await loadRoles();}catch(error){toast(error.message,'error');}
}

function slugRoleCode(value){
  return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,'_').replace(/^_+|_+$/g,'').slice(0,40);
}

function openRoleForm(code=null){
  const data=state.roleData;
  if(!data){toast('Carregue a página de cargos novamente.','error');return;}
  const role=code?state.roles.find(item=>item.code===code):null;
  if(role?.is_system){toast('Cargos nativos permitem alterar somente as permissões.','error');return;}
  const modules=permissionModules(data);
  const baseCode=role?.base_role||'seller';
  const baseTemplate=state.roles.find(item=>item.code===baseCode);
  const formRole=role||{permissions:baseTemplate?.permissions||[]};
  modal(role?'Editar cargo':'Novo cargo',`<form id="role-form" class="form-grid">
    <label>Nome do cargo<input name="name" required minlength="2" value="${esc(role?.name||'')}" placeholder="Ex.: Supervisor"></label>
    <label>Código interno<input name="code" required pattern="[a-z0-9_]+" value="${esc(role?.code||'')}" ${role?'readonly':''} placeholder="supervisor"></label>
    <label>Cargo-base<select name="base_role" required><option value="seller" ${baseCode==='seller'?'selected':''}>Vendedor</option><option value="bko" ${baseCode==='bko'?'selected':''}>BKO</option><option value="manager" ${baseCode==='manager'?'selected':''}>Gerente</option></select></label>
    ${role?`<label class="switch-row">Cargo ativo<input type="checkbox" name="active" ${role.active?'checked':''}></label>`:''}
    <label class="full">Descrição<textarea name="description" placeholder="Responsabilidade e objetivo do cargo">${esc(role?.description||'')}</textarea></label>
    <div class="form-section full">Permissões</div>
    <div class="full permission-grid" data-role-form-permissions>${rolePermissionsMarkup(formRole,modules,'form')}</div>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">${role?'Salvar cargo':'Criar cargo'}</button></div>
  </form>`,{wide:true});
  $$('[data-close-modal]').forEach(el=>el.addEventListener('click',closeModal));
  const form=$('#role-form');
  const nameInput=form.elements.name;
  const codeInput=form.elements.code;
  if(!role){
    nameInput.addEventListener('input',()=>{if(!codeInput.dataset.manual)codeInput.value=slugRoleCode(nameInput.value);});
    codeInput.addEventListener('input',()=>{codeInput.dataset.manual='1';codeInput.value=slugRoleCode(codeInput.value);});
    form.elements.base_role.addEventListener('change',()=>{
      const template=state.roles.find(item=>item.code===form.elements.base_role.value);
      const allowed=new Set(template?.permissions||[]);
      $$('[data-role-form-permissions] input[type=checkbox]').forEach(input=>input.checked=allowed.has(input.value));
    });
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const payload=formObject(form);
    payload.code=slugRoleCode(payload.code);
    payload.permissions=$$('[data-role-form-permissions] input:checked').map(input=>input.value);
    try{
      await api(role?`/api/roles/${encodeURIComponent(role.code)}`:'/api/roles',{method:role?'PUT':'POST',body:payload});
      closeModal();toast(role?'Cargo atualizado.':'Cargo criado.');await renderRoles();
    }catch(error){toast(error.message,'error');}
  });
}

async function renderAudit() {
  setPage('Auditoria','HISTÓRICO DE ALTERAÇÕES');
  const data=await api('/api/audit?limit=500');
  $('#content').innerHTML=`<div class="page-head"><div><h1>Logs do sistema</h1><p class="muted">Ações administrativas, autenticação e alterações relevantes.</p></div></div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Data</th><th>Usuário</th><th>Ação</th><th>Entidade</th><th>Detalhes</th><th>IP</th></tr></thead><tbody>${data.logs.map(l=>`<tr><td>${fmtDateTime(l.created_at)}</td><td>${esc(l.user_name||'Sistema')}</td><td class="code">${esc(l.action)}</td><td>${esc(l.entity_type||'-')} ${esc(l.entity_id||'')}</td><td><div class="cell-sub" style="max-width:420px;white-space:pre-wrap">${esc(l.details||'')}</div></td><td>${esc(l.ip_address||'-')}</td></tr>`).join('')}</tbody></table></div></section>`;
}

async function renderBackups() {
  setPage('Backups','PROTEÇÃO DO BANCO');
  const data=await api('/api/backups');
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Backups locais</h1><p class="muted">O sistema cria um backup diário ao iniciar e permite cópias manuais.</p></div><button class="btn primary" id="create-backup">Criar backup agora</button></div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Arquivo</th><th>Tamanho</th><th>Modificado em</th></tr></thead><tbody>${data.backups.map(b=>`<tr><td class="code">${esc(b.name)}</td><td>${(b.size/1024).toFixed(1)} KB</td><td>${fmtDateTime(b.modified_at)}</td></tr>`).join('')}</tbody></table></div>${!data.backups.length?'<div class="empty">Nenhum backup encontrado.</div>':''}</section>
    <section class="panel"><div class="panel-body"><strong>Local dos arquivos:</strong><p class="code">Windows: %LOCALAPPDATA%\ONE_CRM\backups (ou a pasta de dados da versão anterior)</p><p class="muted">A restauração é feita pelo utilitário RESTAURAR_BACKUP.bat com o servidor fechado, porque substituir um banco em uso é uma forma bastante eficiente de fabricar corrupção.</p></div></section>`;
  $('#create-backup').addEventListener('click',async()=>{try{const r=await api('/api/backups',{method:'POST',body:{}});toast(r.message);renderBackups();}catch(error){toast(error.message,'error');}});
}

async function renderIntegrations() {
  setPage('Integrações','CONEXÕES EXTERNAS');
  const data=await api('/api/integrations');const i=data.integrations;const openai=i.openai||{};
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Central de integrações</h1><p class="muted">Segredos ficam no servidor. O navegador recebe apenas o estado da configuração.</p></div></div>
    <section class="panel"><header class="panel-head"><h3>Configurações</h3></header><div class="panel-body"><form id="integrations-form" class="form-grid">
      <label class="full">Power BI Embed URL<input name="powerbi_embed_url" value="${esc(i.powerbi_embed_url.value)}" placeholder="https://app.powerbi.com/view?... "><small class="muted">URL incorporada pronta para uso em relatórios.</small></label>
      <label class="full">Webhook genérico<input name="generic_webhook_url" value="${esc(i.generic_webhook_url.value)}" placeholder="https://seu-n8n/webhook/one-crm"><small class="muted">Recebe eventos sale.created, sale.updated e sale.workflow_updated.</small></label>
      <label>Evolution API URL<input name="evolution_api_url" value="${esc(i.evolution_api_url.value)}"></label>
      <label>Evolution API Key<input name="evolution_api_key" type="password" value="${esc(i.evolution_api_key.value)}"><small class="muted">${i.evolution_api_key.configured?'Já configurada.':''}</small></label>
      <label class="full">Modelo OpenAI<input name="openai_model" value="${esc(i.openai_model.value||openai.model||'gpt-5.6-luna')}" ${openai.model_source==='environment'?'disabled':''}><small class="muted">${openai.model_source==='environment'?'Controlado pela variável OPENAI_MODEL no Railway.':'Pode ser salvo no ONE CRM quando OPENAI_MODEL não estiver definida.'}</small></label>
      <div class="full integration-secret-box"><div><strong>Chave OpenAI</strong><p>${openai.configured?'OPENAI_API_KEY foi encontrada no ambiente do Railway.':'OPENAI_API_KEY ainda não foi configurada no Railway.'}</p><small>A chave não é salva no SQLite e nunca volta para o navegador.</small></div>${openai.configured?badge('Configurada','ok'):badge('Ausente','cancelada')}</div>
      <div class="full page-actions integration-actions"><button type="button" class="btn" id="test-openai" ${openai.configured?'':'disabled'}>Testar OpenAI</button><button class="btn primary">Salvar integrações</button></div>
    </form></div></section>
    <section class="panel"><header class="panel-head"><h3>Estado dos conectores</h3></header><div class="panel-body grid-2"><div class="team-card"><h4>Power BI</h4><p>${esc(data.notes.powerbi)}</p>${i.powerbi_embed_url.configured?badge('Configurado','ok'):badge('Não configurado','aguard')}</div><div class="team-card"><h4>Webhook / N8N</h4><p>${esc(data.notes.webhook)}</p>${i.generic_webhook_url.configured?badge('Configurado','ok'):badge('Não configurado','aguard')}</div><div class="team-card"><h4>Evolution API</h4><p>${esc(data.notes.evolution)}</p>${i.evolution_api_key.configured?badge('Credencial salva','ok'):badge('Pendente','aguard')}</div><div class="team-card"><h4>OpenAI</h4><p>${esc(data.notes.openai)}</p>${openai.ready?badge(`Ativa · ${openai.model}`,'ok'):badge('Não configurada','aguard')}</div></div></section>`;
  $('#integrations-form').addEventListener('submit',async e=>{e.preventDefault();try{const payload=formObject(e.currentTarget);delete payload.openai_api_key;await api('/api/integrations',{method:'PUT',body:payload});toast('Integrações atualizadas.');renderIntegrations();}catch(error){toast(error.message,'error');}});
  $('#test-openai')?.addEventListener('click',async e=>{const button=e.currentTarget;button.disabled=true;button.textContent='Testando...';try{const result=await api('/api/ai/test',{method:'POST',body:{}});toast(`${result.message} Modelo: ${result.model}`);}catch(error){toast(error.message,'error');}finally{button.disabled=false;button.textContent='Testar OpenAI';}});
}

async function renderAccount() {
  setPage('Meu perfil','CONTA E PREFERÊNCIAS');
  const result = await api('/api/me');
  state.user = result.user;
  refreshUserUi();
  const u = state.user;
  $('#content').innerHTML=`
    <section class="profile-hero">
      <span class="profile-avatar">${esc(initials(u.display_name || u.name))}</span>
      <div><p class="eyebrow">PERFIL PESSOAL</p><h1>${esc(u.display_name || u.name)}</h1><p>${esc(u.email)} · ${esc(u.role_name||roleLabel(u.role_code))}${u.team_name?` · ${esc(u.team_name)}`:''}</p></div>
    </section>
    <div class="profile-grid">
      <section class="panel profile-main"><header class="panel-head"><div><h3>Informações pessoais</h3><small class="muted">Você pode manter seus dados atualizados sem depender do Dono.</small></div></header><div class="panel-body">
        <form id="profile-form" class="form-grid">
          <label>Nome completo<input name="name" required minlength="3" value="${esc(u.name)}" autocomplete="name"></label>
          <label>Nome de exibição<input name="display_name" minlength="2" value="${esc(u.display_name || '')}" placeholder="Como deseja aparecer no sistema"></label>
          <label>E-mail<input type="email" name="email" required value="${esc(u.email)}" autocomplete="email"><small class="muted">Para trocar o e-mail, confirme sua senha atual.</small></label>
          <label>Telefone<input name="phone" inputmode="numeric" value="${esc(formatPhone(u.phone || ''))}" placeholder="(61) 99111-1111" autocomplete="tel"></label>
          <label class="full">Sobre você<textarea name="bio" maxlength="300" placeholder="Função, especialidade ou uma observação curta.">${esc(u.bio || '')}</textarea><small class="muted"><span id="bio-count">${String(u.bio || '').length}</span>/300 caracteres</small></label>
          <label class="full">Senha atual <span class="muted">(somente se alterar o e-mail)</span><input type="password" name="current_password" autocomplete="current-password"></label>
          <div class="full page-actions profile-save"><button class="btn primary">Salvar perfil</button></div>
        </form>
      </div></section>
      <div class="profile-side">
        <section class="panel"><header class="panel-head"><h3>Aparência</h3></header><div class="panel-body"><p class="muted">Escolha como o ONE CRM será exibido nesta conta.</p><div class="theme-choice" role="group" aria-label="Tema">
          <button class="theme-card ${currentTheme()==='dark'?'active':''}" data-theme-choice="dark" type="button"><span>☾</span><strong>Escuro</strong><small>Menos brilho, mais foco</small></button>
          <button class="theme-card ${currentTheme()==='light'?'active':''}" data-theme-choice="light" type="button"><span>☀</span><strong>Claro</strong><small>Melhor em ambientes iluminados</small></button>
        </div></div></section>
        <section class="panel"><header class="panel-head"><h3>Dados de acesso</h3></header><div class="panel-body"><div class="metric-row"><span>Cargo</span><strong>${esc(u.role_name||roleLabel(u.role_code))}</strong></div><div class="metric-row"><span>Equipe</span><strong>${esc(u.team_name||'-')}</strong></div><div class="metric-row"><span>Permissões</span><strong>${u.permissions.length}</strong></div></div></section>
        <section class="panel"><header class="panel-head"><h3>Alterar senha</h3></header><div class="panel-body"><form id="password-form" class="form-stack"><label>Senha atual<input type="password" name="current_password" required autocomplete="current-password"></label><label>Nova senha<input type="password" name="new_password" required minlength="8" autocomplete="new-password"></label><button class="btn primary">Alterar senha</button></form></div></section>
      </div>
    </div>`;
  const phoneInput = $('#profile-form [name="phone"]');
  phoneInput.addEventListener('input',()=>{phoneInput.value=formatPhone(phoneInput.value);});
  const bio = $('#profile-form [name="bio"]');
  bio.addEventListener('input',()=>{$('#bio-count').textContent=bio.value.length;});
  $('#profile-form').addEventListener('submit',async e=>{
    e.preventDefault();
    try{
      const payload=formObject(e.currentTarget);
      payload.phone=onlyNumbers(payload.phone,11);
      const response=await api('/api/me/profile',{method:'PUT',body:payload});
      state.user=response.user;
      refreshUserUi();
      toast(response.message);
      renderAccount();
    }catch(error){toast(error.message,'error');}
  });
  $$('[data-theme-choice]').forEach(button=>button.addEventListener('click',async()=>{
    const theme=button.dataset.themeChoice;
    applyTheme(theme);
    state.user.theme_preference=theme;
    try{await api('/api/me/theme',{method:'PUT',body:{theme}});toast(`Tema ${theme==='light'?'claro':'escuro'} aplicado.`);renderAccount();}
    catch(error){toast(error.message,'error');}
  }));
  $('#password-form').addEventListener('submit',async e=>{e.preventDefault();try{const r=await api('/api/me/password',{method:'PUT',body:formObject(e.currentTarget)});toast(r.message);setTimeout(()=>location.reload(),1200);}catch(error){toast(error.message,'error');}});
}

Object.assign(window,{navigate,openSaleDetail,openUserForm,openTeamForm,openPlanForm,openCatalogForm,openRoleForm,saveRole,renderRoute});
boot();
