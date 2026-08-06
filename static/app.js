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
  baseRoles: [],
  roleData: null,
  currentSales: [],
  currentSale: null,
  aiMessages: [],
  profiles: [],
  platformAccess: null,
  profileTemplates: [],
  cashTransactions: [],
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const nativeRoleLabels = {owner:'Dono',manager:'Gerente',bko:'BKO',seller:'Vendedor'};
const baseRoleTypeLabels = {manager:'Gestão',bko:'Suporte / apoio',seller:'Operação principal'};
const roleLabel = role => state.roles.find(item=>item.code===role)?.name || nativeRoleLabels[role] || role;
const baseRole = user => user?.base_role || state.roles.find(item=>item.code===user?.role_code)?.base_role || user?.role_code || 'seller';
const money = value => Number(value || 0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
const fmtDate = value => {
  if (!value) return '-';
  const raw = String(value).slice(0,10);
  const [y,m,d] = raw.split('-');
  return y && m && d ? `${d}/${m}/${y}` : value;
};
const BRASILIA_TIME_ZONE = 'America/Sao_Paulo';
const fmtDateTime = value => {
  if (!value) return '-';
  const raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) return fmtDate(raw);

  // O Railway grava os horários históricos em UTC sem informar o fuso.
  // Valores novos que já tragam Z ou offset continuam sendo respeitados.
  const isoLike = raw.replace(/^(\d{4}-\d{2}-\d{2})\s+/, '$1T');
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(isoLike)
    ? isoLike
    : `${isoLike}Z`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;

  return new Intl.DateTimeFormat('pt-BR', {
    timeZone: BRASILIA_TIME_ZONE,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
};
const initials = name => String(name || 'OC').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
const has = permission => state.user?.is_platform_owner || baseRole(state.user) === 'owner' || state.user?.permissions?.includes(permission);
const isPlatformOwner = () => Boolean(state.user?.is_platform_owner);
const isPlatformStaff = () => Boolean(state.user?.is_platform_staff);
const isReadOnlyContractor = () => Boolean(state.user?.is_contractor && !state.user?.is_platform_owner);
const activeProfile = () => state.user?.profile || {};
const activePreset = () => activeProfile().preset || {};
const activeModules = () => new Set(activeProfile().modules || []);
const routeModuleMap = {dashboard:'dashboard',sales:'sales','new-sale':'sales',bko:'bko',daily:'daily',powerbi:'powerbi',ranking:'ranking',intelligence:'intelligence',users:'users',teams:'teams',plans:'plans',catalogs:'catalogs',roles:'roles',audit:'audit',backups:'backups',integrations:'integrations',cash:'cash','profile-settings':'users'};
const moduleEnabled = route => {
  if (route === 'profiles' || route === 'platform-access') return isPlatformOwner();
  if (route === 'work-center') return true;
  if (route === 'plans') return activeModules().has('plans') || activeModules().has('services_catalog');
  return activeModules().has(routeModuleMap[route] || route);
};
const presetLabel = (key, fallback='') => activePreset().navigation_labels?.[key] || fallback || key;
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

function bindOverlayClose(backdropSelector) {
  const root = $('#modal-root');
  const backdrop = $(backdropSelector, root);
  if (!backdrop) return;

  // Fecha somente quando o clique ocorrer no fundo, nunca quando vier de um
  // campo, select, botão ou qualquer elemento dentro do painel.
  backdrop.addEventListener('click', event => {
    if (event.target === backdrop) closeModal();
  });
  $$('[data-close-modal]', root).forEach(el => el.addEventListener('click', event => {
    event.preventDefault();
    event.stopPropagation();
    closeModal();
  }));
}

function modal(title, body, {wide=false, footer=''}={}) {
  $('#modal-root').innerHTML = `
    <div class="modal-backdrop">
      <section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <header class="modal-head"><h3>${esc(title)}</h3><button type="button" class="icon-btn" data-close-modal aria-label="Fechar">×</button></header>
        <div class="modal-body">${body}</div>
        ${footer ? `<footer class="modal-foot">${footer}</footer>` : ''}
      </section>
    </div>`;
  bindOverlayClose('.modal-backdrop');
}
function closeModal(){ $('#modal-root').innerHTML=''; }

function drawer(title, body) {
  $('#modal-root').innerHTML = `
    <div class="drawer-backdrop">
      <section class="drawer" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <header class="drawer-head"><h3>${esc(title)}</h3><button type="button" class="icon-btn" data-close-modal aria-label="Fechar">×</button></header>
        <div class="drawer-body">${body}</div>
      </section>
    </div>`;
  bindOverlayClose('.drawer-backdrop');
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

const genericOperationIds = [
  'clients','service_orders','schedule','leads','opportunities','tasks','debtors','negotiations','agreements',
  'customers','tickets','followups','properties','real_estate_leads','visits','proposals','products','orders','stock',
  'projects','deliverables','vacancies','candidates','interviews'
];
const genericOperationItems = genericOperationIds.map(id=>({
  id,label:id.replaceAll('_',' '),icon:'◇',test:()=>has(`${id}.view`)||has(`${id}.manage`)
}));
const financeNavigationItems = [
  {id:'cash',label:'Caixa',icon:'¤',permission:'cash.view'},
  {id:'accounts_payable',label:'Contas a pagar',icon:'↓',test:()=>has('accounts_payable.view')||has('accounts_payable.manage')},
  {id:'accounts_receivable',label:'Contas a receber',icon:'↑',test:()=>has('accounts_receivable.view')||has('accounts_receivable.manage')},
];

const productivityNavigationItems = [
  {id:'work-center',label:'Central de produtividade',icon:'✓',test:()=>has('tasks.view')||has('tasks.manage')||has('reports.manage')},
];

const administrativeNavigationItems = [
  {id:'profile-settings',label:'Perfil atual',icon:'◈',test:()=>isPlatformOwner()||has('profile.view')},
  {id:'users',label:'Funcionários',icon:'♙',permission:'users.view'},
  {id:'teams',label:'Equipes',icon:'◫',test:()=>has('teams.view')||has('teams.manage')},
  {id:'plans',label:'Planos e serviços',icon:'▱',test:()=>has('plans.view')||has('plans.manage')},
  {id:'catalogs',label:'Catálogos',icon:'⚙',test:()=>has('catalogs.view')||has('catalogs.manage')},
  {id:'roles',label:'Cargos e permissões',icon:'⌘',test:()=>has('roles.view')||has('roles.manage')},
  {id:'audit',label:'Auditoria',icon:'◷',permission:'audit.view'},
  {id:'backups',label:'Backups',icon:'⇩',permission:'backups.manage'},
  {id:'integrations',label:'Integrações',icon:'⌁',test:()=>has('integrations.view')||has('integrations.manage')},
];

const navigationItems = [
  {id:'profiles',label:'Perfis',icon:'▦',test:()=>isPlatformOwner()},
  {id:'platform-access',label:'Acessos da Plataforma',icon:'♛',test:()=>isPlatformOwner()},
  {id:'dashboard',label:'Dashboard',icon:'⌂',permission:'dashboard.view'},
  {id:'sales-group',label:'Vendas',icon:'▤',children:salesNavigationItems},
  {id:'operation-group',label:'Operação',icon:'◆',children:genericOperationItems},
  {id:'finance-group',label:'Financeiro',icon:'¤',children:financeNavigationItems},
  {id:'daily',label:'Análise do dia',icon:'↗',permission:'daily.view'},
  {id:'powerbi',label:'Power BI',icon:'▥',permission:'powerbi.view'},
  {id:'ranking',label:'Ranking',icon:'◇',test:()=>has('ranking.own')||has('ranking.all')},
  {id:'intelligence',label:'Inteligência',icon:'✦',permission:'intelligence.view'},
  {id:'productivity-group',label:'Produtividade',icon:'✓',children:productivityNavigationItems},
  {id:'administrative-group',label:'Administrativo',icon:'⚙',children:administrativeNavigationItems},
];

function navigationItemLabel(item) {
  if (item.id === 'operation-group') return activePreset().operation_group_label || 'Operação';
  if (item.id === 'finance-group') return activePreset().operation_group_label === 'Financeiro' ? 'Financeiro' : item.label;
  return presetLabel(item.id, item.label);
}

function menuAllowed(item) {
  const allowed = item.test ? item.test() : item.permission ? has(item.permission) : true;
  return allowed && moduleEnabled(item.id);
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
    backups:'Proteção do banco de dados',integrations:'Power BI, webhook, WhatsApp e IA',
    profiles:'Ambientes isolados da plataforma','platform-access':'Donos, administradores e equipe interna',cash:'Entradas, saídas e saldo',
    'profile-settings':'Identidade e módulos do perfil atual'
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
    <div class="nav-popover-head"><span>${esc(navigationItemLabel(group))}</span><small>${children.length} opção(ões)</small></div>
    <div class="nav-popover-grid">${children.map(item => `
      <button class="nav-popover-item" type="button" data-popover-route="${item.id}" role="menuitem">
        <span class="nav-popover-icon">${item.icon}</span>
        <span><strong>${esc(navigationItemLabel(item))}</strong><small>${esc(navigationDescription(item))}</small></span>
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
  container.innerHTML = `<span class="context-subnav-label">${esc(navigationItemLabel(group))}</span>${children.map(item => `
    <button class="context-subnav-item ${active===item.id?'active':''}" type="button" data-context-route="${item.id}" ${active===item.id?'aria-current="page"':''}>
      <span>${item.icon}</span>${esc(navigationItemLabel(item))}
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
      <span class="top-nav-icon">${item.icon}</span><span>${esc(navigationItemLabel(item))}</span>${grouped?'<span class="nav-chevron">⌄</span>':''}
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
      profiles: renderProfiles,
      'platform-access': renderPlatformAccess,
      dashboard: renderDashboard,
      sales: () => renderSales(params),
      'new-sale': () => openSaleForm(null, true),
      bko: renderBko,
      daily: () => renderDaily(params),
      ranking: () => renderRanking(params),
      cash: renderCash,
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
      'profile-settings': renderProfileSettings,
      account: renderAccount,
      'work-center': renderWorkCenter,
    };
    if (genericOperationIds.includes(route) || ['accounts_payable','accounts_receivable'].includes(route)) {
      return renderProfileRecords(route, params);
    }
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
  state.profiles = state.user.profiles || [];
  const switcher = $('#profile-switcher');
  if (switcher) {
    const profile = activeProfile();
    switcher.classList.remove('hidden');
    if (state.profiles.length > 1) {
      switcher.innerHTML = `<label><span>Perfil</span><select id="profile-select">${state.profiles.map(item=>`<option value="${item.id}" ${String(item.id)===String(profile.id)?'selected':''}>${esc(item.name)}</option>`).join('')}</select></label>`;
      $('#profile-select').addEventListener('change', async event => {
        const select = event.currentTarget;
        select.disabled = true;
        try {
          await api('/api/profiles/switch',{method:'POST',body:{profile_id:Number(select.value)}});
          const bootData = await api('/api/bootstrap');
          state.user = bootData.user; state.csrf = bootData.csrf_token;
          state.catalogs={};state.plans=[];state.users=[];state.teams=[];state.roles=[];state.baseRoles=[];state.cashTransactions=[];
          state.profiles = state.user.profiles || [];
  refreshUserUi();
          navigate('dashboard');
          await renderRoute();
          toast(`Perfil alterado para ${state.user.profile.name}.`);
        } catch(error) { toast(error.message,'error'); select.disabled=false; }
      });
    } else {
      switcher.innerHTML = `<button type="button" class="profile-chip" ${isPlatformOwner()?'data-route="profiles"':''}><small>PERFIL ATUAL</small><strong>${esc(profile.name||'Sem perfil')}</strong></button>`;
    }
  }
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
    state.catalogs={};state.plans=[];state.users=[];state.teams=[];state.roles=[];state.baseRoles=[];state.cashTransactions=[];state.profiles=state.user.profiles||[];
    showApp();
  } catch(error) { toast(error.message,'error'); }
  finally { button.disabled = false; }
});

$('#forgot-password-btn')?.addEventListener('click',()=>{
  modal('Recuperar senha',`<form id="password-request-form" class="form-grid"><label class="full">E-mail<input name="email" type="email" required></label><div class="full form-actions"><button class="btn" type="button" data-close-modal>Cancelar</button><button class="btn primary" type="submit">Enviar instruções</button></div></form>`);
  $('#password-request-form').addEventListener('submit',async e=>{e.preventDefault();try{const r=await api('/api/password/request',{method:'POST',body:formObject(e.currentTarget)});closeModal();toast(r.message);}catch(error){toast(error.message,'error');}});
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
document.addEventListener('click',event=>{
  if(!event.target.closest('#nav-popover')&&!event.target.closest('[data-nav-group]')) closeNavigationPopover();

  const target = event.target.closest('[data-route],[data-render-route],[data-sale-detail],[data-user-edit],[data-team-edit],[data-plan-edit],[data-catalog-edit],[data-role-edit],[data-role-save]');
  if (!target || target.disabled) return;

  if (target.dataset.route) {
    event.preventDefault();
    navigate(target.dataset.route, target.dataset.routeQuery || '');
  } else if (target.hasAttribute('data-render-route')) {
    event.preventDefault();
    renderRoute();
  } else if (target.dataset.saleDetail) {
    event.preventDefault();
    openSaleDetail(Number(target.dataset.saleDetail));
  } else if (target.dataset.userEdit) {
    event.preventDefault();
    openUserForm(Number(target.dataset.userEdit));
  } else if (target.dataset.teamEdit) {
    event.preventDefault();
    openTeamForm(Number(target.dataset.teamEdit));
  } else if (target.dataset.planEdit) {
    event.preventDefault();
    openPlanForm(Number(target.dataset.planEdit));
  } else if (target.dataset.catalogEdit) {
    event.preventDefault();
    openCatalogForm(Number(target.dataset.catalogEdit), target.dataset.catalogCategory || '');
  } else if (target.dataset.roleEdit) {
    event.preventDefault();
    openRoleForm(target.dataset.roleEdit);
  } else if (target.dataset.roleSave) {
    event.preventDefault();
    saveRole(target.dataset.roleSave);
  }
});
window.addEventListener('resize',closeNavigationPopover);
window.addEventListener('scroll',closeNavigationPopover,true);

function openGlobalSearch() {
  modal('Pesquisa global', `<form id="global-search-form" class="form-stack"><label>Cliente, CPF, telefone ou OS<input name="search" autofocus placeholder="Digite para pesquisar"></label><button class="btn primary">Pesquisar vendas</button></form>`);
  setTimeout(()=>$('#global-search-form input')?.focus(),50);
  $('#global-search-form').addEventListener('submit',e=>{e.preventDefault();const value=new FormData(e.currentTarget).get('search');closeModal();navigate('sales',qs({search:value}));});
}

async function renderDashboard() {
  setPage('Dashboard', activeProfile().name ? activeProfile().name.toUpperCase() : 'CENTRAL DE OPERAÇÃO');
  const data = await api('/api/dashboard');
  const visibleName = state.user.display_name || state.user.name;
  if (data.profile_type === 'cash_control') {
    const c = data.cash;
    $('#content').innerHTML = `
      <section class="dashboard-hero"><div><p class="eyebrow">CONTROLE FINANCEIRO</p><h1>Olá, ${esc(visibleName)}</h1><p>Saldo e movimentações do perfil ${esc(activeProfile().name||'')}.</p></div><div class="dashboard-hero-actions"><button class="btn primary" id="dashboard-new-cash">＋ Novo lançamento</button><button class="btn" id="dashboard-view-cash">Abrir caixa</button></div></section>
      <section class="dashboard-metrics">
        <article class="stat-card compact" style="--accent:var(--green)"><div class="stat-top"><span>Entradas totais</span><span class="stat-icon">＋</span></div><div class="stat-value">${money(c.entries)}</div><div class="stat-note">${money(c.month_entries)} neste mês</div></article>
        <article class="stat-card compact" style="--accent:var(--red)"><div class="stat-top"><span>Saídas totais</span><span class="stat-icon">−</span></div><div class="stat-value">${money(c.exits)}</div><div class="stat-note">${money(c.month_exits)} neste mês</div></article>
        <article class="stat-card compact" style="--accent:var(--cyan)"><div class="stat-top"><span>Saldo atual</span><span class="stat-icon">¤</span></div><div class="stat-value">${money(c.balance)}</div><div class="stat-note">Entradas menos saídas</div></article>
      </section>
      <section class="panel"><header class="panel-head"><div><h3>Movimentações recentes</h3><small class="muted">Últimos lançamentos do perfil</small></div><button class="btn small" id="cash-open-all">Ver caixa</button></header>${cashTable(data.recent_transactions||[])}</section>`;
    $('#dashboard-new-cash')?.addEventListener('click',()=>openCashForm());
    $('#dashboard-view-cash')?.addEventListener('click',()=>navigate('cash'));
    $('#cash-open-all')?.addEventListener('click',()=>navigate('cash'));
    return;
  }
  if (data.generic) {
    const cards = data.cards || [];
    const recent = data.recent || [];
    const operationLabel = data.preset?.operation_group_label || 'Operação';
    $('#content').innerHTML = `
      <section class="dashboard-hero"><div><p class="eyebrow">${esc(String(operationLabel).toUpperCase())}</p><h1>Olá, ${esc(visibleName)}</h1><p>Resumo do perfil ${esc(activeProfile().name||'')} sem indicadores de outros segmentos.</p></div></section>
      <section class="dashboard-metrics">${cards.length ? cards.map(card=>`<article class="stat-card compact" style="--accent:var(--cyan)"><div class="stat-top"><span>${esc(card.label)}</span><span class="stat-icon">◇</span></div><div class="stat-value">${card.total}</div><div class="stat-note">${card.overdue?`${card.overdue} prazo(s) vencido(s)`:card.amount?money(card.amount):'Registros ativos'}</div><button type="button" class="metric-link" data-route="${esc(card.module)}">Abrir módulo</button></article>`).join('') : '<article class="stat-card compact"><div class="stat-note">Este perfil ainda não possui registros operacionais.</div></article>'}</section>
      <section class="panel"><header class="panel-head"><div><h3>Atualizações recentes</h3><small class="muted">Movimentações dos módulos deste preset</small></div></header>${genericRecordTable(recent,{compact:true})}</section>`;
    return;
  }
  const c = data.cards;
  const conversion = c.total ? Math.round(c.installed * 100 / c.total) : 0;
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
      <div><p class="eyebrow">PAINEL PRINCIPAL</p><h1>Olá, ${esc(visibleName)}</h1><p>Indicadores do perfil ${esc(activeProfile().name||'')}.</p></div>
      <div class="dashboard-hero-actions">${has('sales.create')?'<button class="btn primary" id="dashboard-new-sale">＋ Nova venda</button>':''}<button class="btn" id="dashboard-view-sales">Ver vendas</button></div>
    </section>
    <section class="dashboard-metrics" aria-label="Indicadores principais">${cards.map(([title,value,note,icon,color])=>`<article class="stat-card compact" style="--accent:var(${color})"><div class="stat-top"><span>${title}</span><span class="stat-icon">${icon}</span></div><div class="stat-value">${value}</div><div class="stat-note">${note}</div></article>`).join('')}</section>
    <section class="panel dashboard-recent"><header class="panel-head"><div><h3>Vendas recentes</h3><small class="muted">Últimas movimentações do perfil atual</small></div><button type="button" class="btn small" data-route="sales">Ver todas</button></header>${salesTable(data.recent)}</section>
    ${data.teams?.length ? `<section class="panel"><header class="panel-head"><div><h3>Desempenho das equipes</h3><small class="muted">Comparação rápida do dia</small></div><button type="button" class="btn small ghost" data-route="daily">Análise completa</button></header><div class="panel-body dashboard-teams">${data.teams.map(t=>`<article class="team-card"><h4>${esc(t.team_name)}</h4><div class="metric-row"><span>Hoje</span><strong>${t.today}</strong></div><div class="metric-row"><span>Total</span><strong>${t.total}</strong></div><div class="metric-row"><span>Instaladas</span><strong>${t.installed}</strong></div></article>`).join('')}</div></section>`:''}`;
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
      <div class="filters"><button type="button" class="btn ${period==='month'?'primary':''}" data-route="ranking" data-route-query="period=month">Mês</button><button type="button" class="btn ${period==='all'?'primary':''}" data-route="ranking" data-route-query="period=all">Geral</button></div></div>
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
    const provider=result.provider_label||result.provider||'ONE Intelligence';
    const meta=[provider,result.model,usage.total_tokens?`${usage.total_tokens} tokens`:null,result.fallback_used?'fallback local':null].filter(Boolean).join(' · ');
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
    api('/api/ai/status').catch(error=>({ai:{ready:false,permission:false,error:error.message,providers:{}}})),
  ]);
  const ai=statusResult.ai||{};
  const providers=ai.providers||{};
  const activeLabel=ai.provider_label||'Análise local';
  const aiAvailable=Boolean(ai.ready && ai.permission);
  const externalConfigured=Boolean(ai.external_configured);
  const quickPrompts=[
    'Resuma as principais pendências da operação e indique prioridades.',
    'Quais estados podemos focar nas vendas hoje?',
    'Quais riscos operacionais aparecem nos indicadores atuais?',
    'Sugira um plano de ação curto para melhorar a conversão.',
    'Liste os pontos que merecem acompanhamento hoje.',
  ];
  const providerStatus=ai.active_provider==='local'
    ? badge('Modo local ativo','cyan')
    : badge(`${activeLabel} conectado`,'ok');
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>ONE Intelligence</h1><p class="muted">Assistente operacional com GroqCloud, OpenAI opcional e fallback local automático.</p></div><button type="button" class="btn" data-render-route>Atualizar</button></div>
    <section class="panel ai-panel">
      <header class="panel-head"><div><h3>Assistente operacional</h3><small class="muted">${esc(activeLabel)} · ${esc(ai.model||'motor-local')}</small></div>${providerStatus}</header>
      <div class="panel-body">
        ${!ai.permission?'<div class="integration-notice warning"><strong>Seu cargo não possui a permissão “Utilizar o assistente ONE Intelligence”.</strong><span>O Dono pode liberar essa opção em Cargos e permissões.</span></div>':''}
        ${ai.permission&&!externalConfigured?'<div class="integration-notice info"><strong>Nenhuma IA externa está configurada.</strong><span>O chat continua funcionando no modo local. Para respostas mais elaboradas, configure GROQ_API_KEY gratuitamente no Railway.</span></div>':''}
        ${ai.permission&&ai.active_provider==='local'&&externalConfigured?'<div class="integration-notice info"><strong>O fallback local está ativo.</strong><span>O provedor externo pode estar sem cota, indisponível ou ter sido desativado.</span></div>':''}
        <div class="ai-layout ${aiAvailable?'':'disabled'}">
          <div class="ai-chat">
            <div id="ai-messages" class="ai-messages" aria-live="polite"></div>
            <form id="ai-form" class="ai-form">
              <label class="ai-sale-field">Venda específica <span class="muted">(opcional)</span><input id="ai-sale-id" name="sale_id" type="number" min="1" placeholder="Ex.: 152" ${aiAvailable?'':'disabled'}></label>
              <label class="ai-question-field">Pergunta<textarea id="ai-question" name="question" maxlength="2000" rows="4" placeholder="Ex.: Quais vendas exigem prioridade hoje?" ${aiAvailable?'':'disabled'}></textarea></label>
              <div class="ai-form-actions"><small class="muted">O contexto externo não inclui CPF, telefone, e-mail nem endereço completo. Se a cota externa acabar, a análise local assume.</small><button id="ai-send" class="btn primary" ${aiAvailable?'':'disabled'}>Perguntar ao ONE</button></div>
            </form>
          </div>
          <aside class="ai-suggestions"><strong>Sugestões rápidas</strong>${quickPrompts.map((prompt,index)=>`<button type="button" class="ai-quick" data-ai-quick="${index}" ${aiAvailable?'':'disabled'}>${esc(prompt)}</button>`).join('')}</aside>
        </div>
      </div>
    </section>
    <section class="panel"><header class="panel-head"><div><h3>Provedores disponíveis</h3><small class="muted">Seleção atual: ${esc(ai.requested_provider||'auto')}</small></div></header><div class="panel-body grid-3">
      <div class="team-card"><h4>GroqCloud</h4><p>${providers.groq?.configured?'Chave detectada no Railway.':'GROQ_API_KEY não configurada.'}</p>${providers.groq?.configured?badge(`Pronto · ${providers.groq.model}`,'ok'):badge('Não configurado','aguard')}</div>
      <div class="team-card"><h4>OpenAI</h4><p>${providers.openai?.configured?'Chave detectada no Railway.':'Opcional; pode permanecer sem saldo.'}</p>${providers.openai?.configured?badge(`Pronto · ${providers.openai.model}`,'ok'):badge('Opcional','aguard')}</div>
      <div class="team-card"><h4>Análise local</h4><p>Indicadores e regras do próprio CRM, sem consumo externo.</p>${badge('Sempre disponível','cyan')}</div>
    </div></section>
    <section class="panel"><header class="panel-head"><div><h3>Alertas operacionais locais</h3><small class="muted">Gerados sem consumo de API.</small></div><span class="badge cyan">${local.insights.length}</span></header><div class="panel-body">${local.insights.length?local.insights.map(i=>`<article class="insight ${i.severity}"><h4>${esc(i.title)}</h4><p>${esc(i.description)}</p>${i.sale_id?`<button type="button" class="btn small ghost" style="margin-top:10px" data-sale-detail="${i.sale_id}">Abrir venda</button>`:''}</article>`).join(''):'<div class="empty">Nenhum alerta relevante.</div>'}</div></section>`;
  renderAIMessages();
  $('#ai-form')?.addEventListener('submit',e=>{e.preventDefault();sendAIQuestion();});
  $$('[data-ai-quick]').forEach(button=>button.addEventListener('click',()=>sendAIQuestion(quickPrompts[Number(button.dataset.aiQuick)])));
}


function profileTypeLabel(code) {
  const template = state.profileTemplates?.find(item => item.code === code);
  if (template?.name) return template.name;
  return ({
    internet_sales:'Venda de internet', cash_control:'Controle de caixa', services:'Prestação de serviços',
    general_crm:'CRM comercial geral', collections:'Cobrança e recuperação', after_sales:'Atendimento e pós-venda',
    real_estate:'Imobiliária e corretores', retail:'Loja e varejo', consulting:'Consultoria e projetos',
    recruitment:'Recrutamento e seleção', custom:'Perfil personalizado'
  })[code] || code;
}

function templateModuleLabel(template,module) {
  const direct=template?.navigation_labels?.[module];
  if(direct)return direct;
  const record=template?.records?.[module];
  if(record?.label)return record.label;
  if(module==='services_catalog')return template?.admin_labels?.plans_title||'Serviços';
  return ({dashboard:'Dashboard',sales:'Vendas',bko:'Gestão BKO',daily:'Análise do dia',ranking:'Ranking',intelligence:'Inteligência',powerbi:'Power BI',users:'Funcionários',teams:'Equipes',plans:'Planos',catalogs:'Catálogos',roles:'Cargos e permissões',audit:'Auditoria',integrations:'Integrações',cash:'Controle de caixa'})[module] || String(module).replaceAll('_',' ');
}
function profileTemplatePreview(template) {
  if (!template) return '';
  const modules = template.modules || [];
  return `<div class="preset-preview-card">
    <div class="preset-preview-head"><div><small>Categoria</small><strong>${esc(template.category || 'Perfil')}</strong></div><span class="badge cyan">Preset completo</span></div>
    <p>${esc(template.description || '')}</p>
    <div class="preset-recommended"><small>Indicado para</small><span>${esc(template.recommended_for || 'Operações personalizadas.')}</span></div>
    <div class="preset-assets-grid">
      <section><small>Abas incluídas</small><div>${modules.map(module=>`<span class="preset-chip">${esc(templateModuleLabel(template,module))}</span>`).join('')}</div></section>
      <section><small>Cargos iniciais</small><div>${(template.roles||[]).length?(template.roles||[]).map(role=>`<span class="preset-chip">${esc(role.name)}</span>`).join(''):'<span class="muted">Definidos manualmente</span>'}</div></section>
      <section><small>Catálogos e status</small><div>${(template.catalogs||[]).length?(template.catalogs||[]).map(cat=>`<span class="preset-chip">${esc(cat.label)}</span>`).join(''):'<span class="muted">Sem catálogo inicial</span>'}</div></section>
      <section><small>Planos/serviços sugeridos</small><div>${(template.offerings||[]).length?(template.offerings||[]).map(item=>`<span class="preset-chip">${esc(item.name)}</span>`).join(''):'<span class="muted">Cadastro livre</span>'}</div></section>
    </div>
  </div>`;
}
function moduleLabel(module) { return templateModuleLabel(activePreset(),module); }

function platformPermissionModules(data=state.platformAccess) {
  const modules={};
  (data?.permissions||[]).forEach(permission=>(modules[permission.module]??=[]).push(permission));
  return modules;
}

function platformPermissionsMarkup(role, modules, readOnly=false) {
  const selected=new Set(role?.permissions||[]);
  return Object.entries(modules).map(([module,permissions])=>`<div class="permission-module"><h4>${esc(module)}</h4><div class="check-list">${permissions.map(permission=>`<label class="check-item"><input type="checkbox" value="${esc(permission.code)}" ${selected.has(permission.code)?'checked':''} ${readOnly?'disabled':''}><span>${esc(permission.description)}</span></label>`).join('')}</div></div>`).join('');
}

async function renderPlatformAccess() {
  if(!isPlatformOwner()) return navigate('dashboard');
  setPage('Acessos da Plataforma','SEGURANÇA GLOBAL');
  const data=await api('/api/platform-access');
  state.platformAccess=data;
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Equipe e acessos da plataforma</h1><p class="muted">Área exclusiva dos Donos. Crie outros Donos, administradores e funcionários internos sem misturá-los aos cargos de cada perfil.</p></div><div class="actions"><button class="btn" id="new-platform-role">＋ Novo cargo</button><button class="btn primary" id="new-platform-user">＋ Novo funcionário</button></div></div>
    <section class="panel"><header class="panel-head"><div><h3>Funcionários da plataforma</h3><small class="muted">Contas globais criadas e administradas somente por Donos.</small></div></header><div class="table-wrap"><table class="data-table"><thead><tr><th>Funcionário</th><th>Cargo global</th><th>Perfis atribuídos</th><th>Status</th><th>Último acesso</th><th></th></tr></thead><tbody>${(data.users||[]).map(user=>`<tr><td><div class="cell-main">${esc(user.name)}</div><div class="cell-sub">${esc(user.email)}</div></td><td>${badge(user.platform_role_name||user.platform_role_code,user.is_owner?'violet':'cyan')}</td><td>${user.is_owner?'<span class="badge violet">Todos os perfis</span>':(user.profiles||[]).map(profile=>`<span class="badge cyan">${esc(profile.name)}</span>`).join(' ')||'<span class="muted">Nenhum</span>'}</td><td>${user.active?badge('Ativo','ok'):badge('Bloqueado','cancelada')}</td><td>${fmtDateTime(user.last_login_at)}</td><td><button class="btn small" data-platform-user-edit="${user.id}">Editar</button></td></tr>`).join('')}</tbody></table></div></section>
    <div class="page-head compact-head"><div><h2>Cargos da plataforma</h2><p class="muted">Esses cargos atuam somente nos perfis atribuídos. O cargo Dono continua sendo o único com acesso global irrestrito.</p></div></div>
    <div class="grid-2">${(data.roles||[]).map(role=>`<section class="panel"><header class="panel-head"><div><div class="role-title-row"><h3>${esc(role.name)}</h3>${role.is_owner?badge('Protegido','violet'):role.is_system?badge('Nativo','cyan'):badge('Personalizado','green')}${role.active?badge('Ativo','ok'):badge('Inativo','cancelada')}</div><p class="muted">${esc(role.description||'Sem descrição')}</p></div>${role.is_owner?'':`<button class="btn small" data-platform-role-edit="${esc(role.code)}">Editar</button>`}</header><div class="panel-body permission-grid">${role.is_owner?'<div class="read-only-value">Acesso total a todos os perfis, configurações e à equipe da plataforma.</div>':platformPermissionsMarkup(role,platformPermissionModules(data),true)}</div></section>`).join('')}</div>`;
  $('#new-platform-role')?.addEventListener('click',()=>openPlatformRoleForm());
  $('#new-platform-user')?.addEventListener('click',()=>openPlatformUserForm());
  $$('[data-platform-role-edit]').forEach(button=>button.addEventListener('click',()=>openPlatformRoleForm(button.dataset.platformRoleEdit)));
  $$('[data-platform-user-edit]').forEach(button=>button.addEventListener('click',()=>openPlatformUserForm(Number(button.dataset.platformUserEdit))));
}

function openPlatformRoleForm(code=null){
  const data=state.platformAccess;
  const role=code?(data.roles||[]).find(item=>item.code===code):null;
  if(role?.is_owner){toast('O cargo Dono da Plataforma é protegido.','error');return;}
  const modules=platformPermissionModules(data);
  modal(role?'Editar cargo da plataforma':'Novo cargo da plataforma',`<form id="platform-role-form" class="form-grid">
    <label>Nome do cargo<input name="name" required minlength="2" value="${esc(role?.name||'')}" placeholder="Ex.: Administrador"></label>
    <label>Código interno<input name="code" required pattern="[a-z0-9_]+" value="${esc(role?.code||'')}" ${role?'readonly':''} placeholder="administrador"></label>
    ${role?`<label class="switch-row full">Cargo ativo<input type="checkbox" name="active" ${role.active?'checked':''}></label>`:''}
    <label class="full">Descrição<textarea name="description">${esc(role?.description||'')}</textarea></label>
    <div class="form-section full">Permissões nos perfis atribuídos</div>
    <div class="full permission-grid" data-platform-role-permissions>${platformPermissionsMarkup(role||{permissions:[]},modules)}</div>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">${role?'Salvar cargo':'Criar cargo'}</button></div>
  </form>`,{wide:true});
  const form=$('#platform-role-form');
  if(!role){
    const nameInput=form.elements.name,codeInput=form.elements.code;
    nameInput.addEventListener('input',()=>{if(!codeInput.dataset.manual)codeInput.value=slugRoleCode(nameInput.value);});
    codeInput.addEventListener('input',()=>{codeInput.dataset.manual='1';codeInput.value=slugRoleCode(codeInput.value);});
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const payload=formObject(form);
    payload.code=slugRoleCode(payload.code);
    payload.permissions=$$('[data-platform-role-permissions] input:checked').map(input=>input.value);
    try{
      await api(role?`/api/platform-roles/${encodeURIComponent(role.code)}`:'/api/platform-roles',{method:role?'PUT':'POST',body:payload});
      closeModal();toast(role?'Cargo atualizado.':'Cargo criado.');await renderPlatformAccess();
    }catch(error){toast(error.message,'error');}
  });
}

function openPlatformUserForm(id=null){
  const data=state.platformAccess;
  const user=id?(data.users||[]).find(item=>item.id===id):null;
  const activeRoles=(data.roles||[]).filter(role=>role.active||role.code===user?.platform_role_code);
  const assigned=new Set((user?.profiles||[]).map(profile=>String(profile.id)));
  modal(user?'Editar funcionário da plataforma':'Novo funcionário da plataforma',`<form id="platform-user-form" class="form-grid">
    <label>Nome<input name="name" required minlength="3" value="${esc(user?.name||'')}"></label>
    <label>E-mail<input type="email" name="email" required value="${esc(user?.email||'')}"></label>
    <label>Cargo da plataforma<select name="platform_role_code" required>${activeRoles.map(role=>`<option value="${esc(role.code)}" ${role.code===user?.platform_role_code?'selected':''}>${esc(role.name)}</option>`).join('')}</select></label>
    <label>${user?'Nova senha (opcional)':'Senha inicial'}<input type="password" name="password" ${user?'':'required'} minlength="8"></label>
    <label class="switch-row">Exigir troca de senha<input type="checkbox" name="must_change_password" ${user?(user.must_change_password?'checked':''):'checked'}></label>
    ${user?`<label class="switch-row">Funcionário ativo<input type="checkbox" name="active" ${user.active?'checked':''}></label>`:''}
    <fieldset class="full permission-group" id="platform-profile-assignment"><legend>Perfis atribuídos</legend><p class="muted">Administradores e funcionários enxergam somente os perfis selecionados. Donos possuem acesso automático a todos.</p><div class="platform-profile-options">${(data.profiles||[]).map(profile=>`<label class="module-toggle-item"><span class="module-toggle-info"><strong>${esc(profile.name)}</strong><small>${esc(profile.business_type)}${profile.active?'':' · inativo'}</small></span><span class="module-toggle-control"><input type="checkbox" name="profile_ids" value="${profile.id}" ${assigned.has(String(profile.id))?'checked':''} ${profile.active?'':'disabled'}></span></label>`).join('')}</div></fieldset>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar funcionário</button></div>
  </form>`,{wide:true});
  const form=$('#platform-user-form');
  const updateAssignmentVisibility=()=>{
    const role=(data.roles||[]).find(item=>item.code===form.elements.platform_role_code.value);
    $('#platform-profile-assignment').classList.toggle('hidden',Boolean(role?.is_owner));
  };
  form.elements.platform_role_code.addEventListener('change',updateAssignmentVisibility);
  updateAssignmentVisibility();
  form.addEventListener('submit',async event=>{
    event.preventDefault();
    const payload=formObject(form);
    payload.profile_ids=$$('input[name="profile_ids"]:checked',form).map(input=>Number(input.value));
    if(user&&!payload.password) delete payload.password;
    try{
      await api(user?`/api/platform-users/${user.id}`:'/api/platform-users',{method:user?'PUT':'POST',body:payload});
      closeModal();toast(user?'Funcionário atualizado.':'Funcionário criado.');await renderPlatformAccess();
    }catch(error){toast(error.message,'error');}
  });
}

async function renderProfiles() {
  if (!isPlatformOwner()) return navigate('dashboard');
  setPage('Perfis da plataforma','ADMINISTRAÇÃO GLOBAL');
  const data = await api('/api/profiles');
  state.profiles = data.profiles || [];
  state.profileTemplates = data.templates || [];
  state.availableContractors = data.available_contractors || [];
  $('#content').innerHTML = `
    <div class="page-head"><div><h1>Perfis de negócio</h1><p class="muted">Cada perfil possui dados, usuários, cargos e configurações isolados.</p></div><button class="btn primary" id="new-profile">＋ Novo perfil</button></div>
    <div class="profile-grid">${state.profiles.map(profile=>`<article class="profile-card ${profile.active?'':'inactive'}">
      <header><div><span class="profile-type">${esc(profileTypeLabel(profile.business_type))}</span><h3>${esc(profile.name)}</h3></div>${profile.active?badge('Ativo','ok'):badge('Bloqueado','cancelada')}</header>
      <p>${esc(profile.description||'Sem descrição.')}</p>
      <div class="profile-metrics"><span><b>${profile.users_count||0}</b> usuários</span><span><b>${profile.modules?.length||0}</b> módulos</span></div>
      <div class="profile-contractor"><small>Contratante</small><strong>${esc(profile.contractor_name||'Não definido')}</strong></div>
      <footer><button class="btn small" data-profile-enter="${profile.id}">Entrar</button><button class="btn small ghost" data-profile-edit="${profile.id}">Configurar</button></footer>
    </article>`).join('')}</div>`;
  $('#new-profile').addEventListener('click',()=>openProfileForm());
  $$('[data-profile-enter]').forEach(button=>button.addEventListener('click',()=>switchProfile(Number(button.dataset.profileEnter))));
  $$('[data-profile-edit]').forEach(button=>button.addEventListener('click',()=>openProfileForm(Number(button.dataset.profileEdit))));
}

async function switchProfile(profileId) {
  await api('/api/profiles/switch',{method:'POST',body:{profile_id:profileId}});
  const data = await api('/api/bootstrap');
  state.user=data.user;state.csrf=data.csrf_token;state.catalogs={};state.plans=[];state.users=[];state.teams=[];state.roles=[];state.baseRoles=[];
  refreshUserUi(); navigate('dashboard'); await renderRoute();
}

function profileModuleOptions(selected=[],template=activePreset()) {
  const modules=template?.modules?.length?template.modules:selected;
  const descriptions={dashboard:'Visão geral dos indicadores do perfil.',daily:'Análises e consolidação do período.',ranking:'Comparativo de desempenho da equipe.',intelligence:'Assistente e análise operacional.',users:'Usuários vinculados ao perfil.',teams:'Equipes e responsáveis.',catalogs:'Status e listas usadas pelo preset.',roles:'Cargos e permissões iniciais.',audit:'Histórico de alterações.',integrations:'Conectores e automações externas.',powerbi:'Painel incorporado.',cash:'Entradas, saídas e saldo.',plans:'Produtos, planos e serviços.',services_catalog:'Serviços e ofertas do segmento.'};
  const set=new Set(selected);
  return modules.map(code=>{
    const record=template?.records?.[code];
    const label=templateModuleLabel(template,code);
    const description=record?.description||descriptions[code]||`Módulo específico de ${String(label).toLowerCase()}.`;
    return `<label class="module-toggle-item"><span class="module-toggle-info"><strong>${esc(label)}</strong><small>${esc(description)}</small></span><span class="module-toggle-control"><input type="checkbox" name="modules" value="${esc(code)}" ${set.has(code)?'checked':''}></span></label>`;
  }).join('');
}

function openProfileForm(id=null) {
  const profile=id?state.profiles.find(item=>item.id===id):null;
  const template=state.profileTemplates.find(item=>item.code===(profile?.business_type||'internet_sales')) || state.profileTemplates[0] || {modules:[]};
  const contractors=state.availableContractors||[];
  modal(id?'Configurar perfil':'Novo perfil',`<form id="profile-form" class="form-grid">
    <label>Nome do perfil<input name="name" required minlength="3" value="${esc(profile?.name||'')}"></label>
    <label>Preset do perfil<select name="business_type" ${id?'disabled':''}>${state.profileTemplates.map(item=>`<option value="${item.code}" ${(profile?.business_type||'internet_sales')===item.code?'selected':''}>${esc(item.name)}</option>`).join('')}</select></label>
    <div class="full" id="profile-preset-preview">${profileTemplatePreview(template)}</div>
    <label class="full">Descrição<textarea name="description" placeholder="Você pode manter a descrição do preset ou escrever uma descrição própria.">${esc(profile?.description||'')}</textarea></label>
    <label>Contratante<select name="contractor_user_id">${optionList(contractors,profile?.contractor_user_id,'Sem contratante')}</select></label>
    ${id?`<label class="switch-row">Perfil ativo<input type="checkbox" name="active" ${profile.active?'checked':''}></label>`:''}
    <fieldset class="full permission-group"><legend>Módulos habilitados</legend><div class="permission-grid" id="profile-module-grid">${profileModuleOptions(profile?.modules||template.modules,template)}</div></fieldset>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar perfil</button></div>
  </form>`,{wide:true});
  const typeSelect=$('#profile-form [name="business_type"]');
  typeSelect?.addEventListener('change',()=>{
    const t=state.profileTemplates.find(item=>item.code===typeSelect.value);
    $('#profile-module-grid').innerHTML=profileModuleOptions(t?.modules||[],t);
    $('#profile-preset-preview').innerHTML=profileTemplatePreview(t);
  });
  $('#profile-form').addEventListener('submit',async event=>{
    event.preventDefault();
    const payload=formObject(event.currentTarget);
    payload.modules=$$('input[name="modules"]:checked',event.currentTarget).map(input=>input.value);
    payload.contractor_user_id=payload.contractor_user_id?Number(payload.contractor_user_id):null;
    if(id) payload.business_type=profile.business_type;
    try {
      await api(id?`/api/profiles/${id}`:'/api/profiles',{method:id?'PUT':'POST',body:payload});
      closeModal();toast(id?'Perfil atualizado.':'Perfil criado.');renderProfiles();
    } catch(error){toast(error.message,'error');}
  });
}

async function renderProfileSettings() {
  const profile=activeProfile();
  if(!isPlatformOwner()){
    setPage('Perfil atual','VISUALIZAÇÃO DO AMBIENTE');
    const modules=profile.modules||[];
    $('#content').innerHTML=`
      <div class="page-head"><div><h1>${esc(profile.name||'Perfil')}</h1><p class="muted">O Contratante possui acesso administrativo de visualização. Somente o Dono da Plataforma altera identidade, modelo e módulos.</p></div>${badge('Somente leitura','cyan')}</div>
      <section class="panel"><div class="panel-body form-grid">
        <div><small class="muted">Nome do perfil</small><div class="read-only-value">${esc(profile.name||'-')}</div></div>
        <div><small class="muted">Tipo de negócio</small><div class="read-only-value">${esc(profileTypeLabel(profile.business_type))}</div></div>
        <div class="full"><small class="muted">Descrição</small><div class="read-only-value">${esc(profile.description||'Sem descrição cadastrada.')}</div></div>
        <div class="full"><small class="muted">Módulos habilitados</small><div class="profile-module-summary">${modules.length?modules.map(module=>`<span class="badge cyan">${esc(moduleLabel(module))}</span>`).join(''):'<span class="muted">Nenhum módulo informado.</span>'}</div></div>
      </div></section>`;
    return;
  }
  setPage('Configurar perfil','AMBIENTE ATUAL');
  $('#content').innerHTML=`<div class="page-head"><div><h1>${esc(profile.name||'Perfil')}</h1><p class="muted">Somente o Dono da Plataforma pode alterar a identidade e os módulos deste ambiente.</p></div></div>
    <section class="panel"><form id="profile-settings-form" class="form-grid panel-body">
      <label>Nome do perfil<input name="name" required value="${esc(profile.name||'')}"></label>
      <label>Tipo<input value="${esc(profileTypeLabel(profile.business_type))}" disabled></label>
      <label class="full">Descrição<textarea name="description">${esc(profile.description||'')}</textarea></label>
      <fieldset class="full permission-group"><legend>Módulos do perfil</legend><div class="permission-grid">${profileModuleOptions(profile.modules||[],activePreset())}</div></fieldset>
      <div class="full page-actions" style="justify-content:flex-end"><button class="btn primary">Salvar configurações</button></div>
    </form></section>`;
  $('#profile-settings-form').addEventListener('submit',async event=>{
    event.preventDefault();const payload=formObject(event.currentTarget);payload.modules=$$('input[name="modules"]:checked',event.currentTarget).map(input=>input.value);
    try{await api(`/api/profiles/${profile.id}`,{method:'PUT',body:payload});const data=await api('/api/bootstrap');state.user=data.user;state.csrf=data.csrf_token;refreshUserUi();toast('Perfil atualizado.');renderRoute();}catch(error){toast(error.message,'error');}
  });
}

function activeRecordConfig(module) {
  return activePreset().records?.[module] || null;
}
function recordStatusLabel(config, value) {
  if (!value) return 'Sem status';
  const direct = (config?.status_options || []).find(item => String(item[0]) === String(value));
  if (direct) return direct[1];
  const category = config?.status_category;
  const item = (state.catalogs?.[category] || []).find(item => String(item.code) === String(value));
  return item?.label || String(value).replace(/^p\d+_/,'').replaceAll('_',' ');
}
function recordUsesDue(config){return Boolean(config&&config.due_label!==false&&config.due_label);}
function recordUsesAmount(config){return Boolean(config&&config.amount_label!==false&&config.amount_label);}
function recordAmountText(config,value){
  const number=Number(value||0);
  if(!number)return '-';
  if(config?.amount_format==='number')return number.toLocaleString('pt-BR',{maximumFractionDigits:2});
  return money(number);
}
function genericRecordTable(rows,{compact=false,module=null,config=null,canManage=false}={}) {
  if(!rows?.length)return '<div class="empty">Nenhum registro encontrado.</div>';
  const configs=module?[config||activeRecordConfig(module)||{}]:rows.map(item=>activeRecordConfig(item.module_code)||{});
  const showDue=config?recordUsesDue(config):configs.some(recordUsesDue);
  const showAmount=config?recordUsesAmount(config):configs.some(recordUsesAmount);
  const dueHeader=config?.due_label||'Prazo';
  const amountHeader=config?.amount_label||'Valor';
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Registro</th><th>Status</th><th>Responsável</th>${showDue?`<th>${esc(dueHeader)}</th>`:''}${showAmount?`<th>${esc(amountHeader)}</th>`:''}${compact?'':'<th></th>'}</tr></thead><tbody>${rows.map(item=>{
    const cfg=config||activeRecordConfig(item.module_code)||{};
    return `<tr><td><div class="cell-main">${esc(item.title)}</div><div class="cell-sub">${esc(item.subtitle||cfg.singular||item.module_code||'')}</div></td><td>${badge(recordStatusLabel(cfg,item.status),item.status)}</td><td>${esc(item.assigned_user_name||'Não definido')}</td>${showDue?`<td>${recordUsesDue(cfg)&&item.due_date?fmtDate(item.due_date):'-'}</td>`:''}${showAmount?`<td>${recordUsesAmount(cfg)?recordAmountText(cfg,item.amount):'-'}</td>`:''}${compact?'':`<td>${canManage?`<button class="btn small" data-record-edit="${item.id}">Editar</button>`:''}</td>`}</tr>`;
  }).join('')}</tbody></table></div>`;
}
function recordStatusOptions(config, selected='') {
  if (config?.status_category) return catalogOptions(config.status_category,selected,'Selecione o status');
  return `<option value="">Selecione o status</option>${(config?.status_options||[]).map(item=>`<option value="${esc(item[0])}" ${String(item[0])===String(selected)?'selected':''}>${esc(item[1])}</option>`).join('')}`;
}
function normalizedStatus(value){return String(value||'').replace(/^p\d+_/,'');}
function referenceOptionLabel(item){
  const parts=[item.title];
  if(item.subtitle)parts.push(item.subtitle);
  return parts.filter(Boolean).join(' · ');
}
function selectValue(value){return value==null?'':String(value);}
function recordCustomField(field,value='',references={}) {
  const required=field.required?'required':'';
  const placeholder=esc(field.placeholder||'');
  const current=selectValue(value);
  if(field.type==='catalog') return `<label>${esc(field.label)}<select data-record-field="${esc(field.key)}" ${required}>${catalogOptions(field.category,current,'Selecione...')}</select></label>`;
  if(field.type==='record'){
    let rows=references[field.module]||[];
    if(Array.isArray(field.status_in)&&field.status_in.length){const allowed=new Set(field.status_in.map(String));rows=rows.filter(item=>allowed.has(normalizedStatus(item.status)));}
    const hasCurrent=rows.some(item=>String(item.id)===current);
    const legacy=current&&!hasCurrent?`<option value="${esc(current)}" selected>Referência anterior: ${esc(current)}</option>`:'';
    return `<label>${esc(field.label)}<select data-record-field="${esc(field.key)}" ${required}><option value="">Selecione...</option>${legacy}${rows.map(item=>`<option value="${item.id}" ${String(item.id)===current?'selected':''}>${esc(referenceOptionLabel(item))}</option>`).join('')}</select></label>`;
  }
  if(field.type==='plan'){
    const rows=state.plans||[];const hasCurrent=rows.some(item=>String(item.id)===current);
    const legacy=current&&!hasCurrent?`<option value="${esc(current)}" selected>Referência anterior: ${esc(current)}</option>`:'';
    return `<label>${esc(field.label)}<select data-record-field="${esc(field.key)}" ${required}><option value="">Selecione...</option>${legacy}${rows.map(item=>`<option value="${item.id}" ${String(item.id)===current?'selected':''}>${esc(item.name)}${item.service?` · ${esc(item.service)}`:''}</option>`).join('')}</select></label>`;
  }
  if(field.type==='textarea') return `<label class="full">${esc(field.label)}<textarea data-record-field="${esc(field.key)}" placeholder="${placeholder}" ${required}>${esc(value||'')}</textarea></label>`;
  if(field.type==='number') return `<label>${esc(field.label)}<input type="number" step="${esc(field.step??'0.01')}" ${field.min!=null?`min="${esc(field.min)}"`:''} ${field.max!=null?`max="${esc(field.max)}"`:''} data-record-field="${esc(field.key)}" value="${esc(value??'')}" ${required}></label>`;
  if(field.type==='date') return `<label>${esc(field.label)}<input type="date" data-record-field="${esc(field.key)}" value="${esc(value||'')}" ${required}></label>`;
  if(field.type==='email') return `<label>${esc(field.label)}<input type="email" data-record-field="${esc(field.key)}" placeholder="${placeholder}" value="${esc(value||'')}" ${required}></label>`;
  if(field.type==='tel') return `<label>${esc(field.label)}<input type="tel" data-record-field="${esc(field.key)}" placeholder="${placeholder||'(DDD) 90000-0000'}" value="${esc(value||'')}" ${required}></label>`;
  if(field.type==='url') return `<label>${esc(field.label)}<input type="url" data-record-field="${esc(field.key)}" placeholder="${placeholder||'https://'}" value="${esc(value||'')}" ${required}></label>`;
  return `<label>${esc(field.label)}<input data-record-field="${esc(field.key)}" placeholder="${placeholder}" value="${esc(value||'')}" ${required}></label>`;
}
async function loadRecordReferences(config){
  const modules=[...new Set((config?.fields||[]).filter(field=>field.type==='record'&&field.module).map(field=>field.module))];
  const entries=await Promise.all(modules.map(async module=>{
    try{const data=await api(`/api/profile-records?${qs({module,all:1})}`);return [module,data.records||[]];}
    catch{return [module,[]];}
  }));
  return Object.fromEntries(entries);
}
async function renderProfileRecords(module,params=new URLSearchParams()) {
  const config=activeRecordConfig(module);
  if(!config)return navigate('dashboard');
  setPage(config.label,activePreset().operation_group_label||'OPERAÇÃO');
  await ensureReferenceData();
  const search=params.get('search')||'';
  const data=await api(`/api/profile-records?${qs({module,all:1,search})}`);
  const records=data.records||[];
  const canManage=Boolean(data.can_manage);
  const summary=data.summary||{total:records.length,by_status:[]};
  $('#content').innerHTML=`<div class="page-head"><div><h1>${esc(config.label)}</h1><p class="muted">${esc(config.description||'Registros exclusivos deste perfil.')}</p></div>${canManage?`<button class="btn primary" id="new-profile-record">＋ Novo ${esc(String(config.singular||'registro').toLowerCase())}</button>`:badge('Somente leitura','cyan')}</div>
    <section class="record-summary-strip"><article><small>Total</small><strong>${summary.total||0}</strong></article>${(summary.by_status||[]).slice(0,4).map(item=>`<article><small>${esc(recordStatusLabel(config,item.status))}</small><strong>${item.total}</strong></article>`).join('')}</section>
    <section class="panel"><header class="panel-head"><form id="record-search" class="inline-form"><input name="search" value="${esc(search)}" placeholder="Buscar em ${esc(String(config.label).toLowerCase())}"><button class="btn small">Buscar</button></form></header>${genericRecordTable(records,{module,config,canManage})}</section>`;
  $('#new-profile-record')?.addEventListener('click',()=>openProfileRecordForm(module,null,records));
  $$('[data-record-edit]').forEach(button=>button.addEventListener('click',()=>openProfileRecordForm(module,Number(button.dataset.recordEdit),records)));
  $('#record-search')?.addEventListener('submit',event=>{event.preventDefault();navigate(module,qs({search:new FormData(event.currentTarget).get('search')}));});
}
async function openProfileRecordForm(module,id=null,records=[]) {
  await ensureReferenceData();
  const config=activeRecordConfig(module);
  const item=id?records.find(row=>row.id===id):{};
  const assigned=state.users||[];
  const references=await loadRecordReferences(config);
  const showAssigned=config.assigned_label!==false;
  const showDue=recordUsesDue(config);
  const showAmount=recordUsesAmount(config);
  const showSubtitle=config.subtitle_label!==false;
  const amountType=config.amount_format==='number'?'number':'number';
  modal(id?`Editar ${config.singular}`:`Novo ${config.singular}`,`<form id="profile-record-form" class="form-grid">
    <label class="full">${esc(config.title_label||`Nome/Identificação de ${String(config.singular).toLowerCase()}`)}<input name="title" required value="${esc(item?.title||'')}"></label>
    <label>Status<select name="status">${recordStatusOptions(config,item?.status||'')}</select></label>
    ${showAssigned?`<label>${esc(config.assigned_label||'Responsável')}<select name="assigned_user_id">${optionList(assigned,item?.assigned_user_id,'Sem responsável')}</select></label>`:''}
    ${showDue?`<label>${esc(config.due_label)}<input type="date" name="due_date" value="${esc(item?.due_date||'')}"></label>`:''}
    ${showAmount?`<label>${esc(config.amount_label)}<input type="${amountType}" min="0" step="${esc(config.amount_step??'0.01')}" name="amount" value="${esc(item?.amount??'')}"></label>`:''}
    ${(config.fields||[]).map(field=>recordCustomField(field,item?.data?.[field.key],references)).join('')}
    ${showSubtitle?`<label class="full">${esc(config.subtitle_label||'Resumo complementar')}<input name="subtitle" value="${esc(item?.subtitle||'')}"></label>`:''}
    <label class="full">${esc(config.notes_label||'Observações')}<textarea name="notes">${esc(item?.notes||'')}</textarea></label>
    ${id?`<label class="switch-row full">Registro ativo<input type="checkbox" name="active" ${item.active?'checked':''}></label>`:''}
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`,{wide:true});
  $('#profile-record-form').addEventListener('submit',async event=>{
    event.preventDefault();const payload=formObject(event.currentTarget);payload.module=module;payload.data={};
    $$('[data-record-field]',event.currentTarget).forEach(input=>payload.data[input.dataset.recordField]=input.value);
    payload.assigned_user_id=showAssigned&&payload.assigned_user_id?Number(payload.assigned_user_id):null;
    payload.amount=showAmount?Number(payload.amount||0):0;
    if(!showDue)payload.due_date='';
    if(!showSubtitle)payload.subtitle='';
    try{await api(id?`/api/profile-records/${id}`:'/api/profile-records',{method:id?'PUT':'POST',body:payload});closeModal();toast(`${config.singular} salvo.`);renderProfileRecords(module);}catch(error){toast(error.message,'error');}
  });
}

function cashTable(rows) {
  if(!rows?.length)return '<div class="empty">Nenhum lançamento encontrado.</div>';
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Data</th><th>Tipo</th><th>Categoria</th><th>Descrição</th><th>Valor</th><th></th></tr></thead><tbody>${rows.map(item=>`<tr><td>${fmtDate(item.transaction_date)}</td><td>${item.transaction_type==='entry'?badge('Entrada','ok'):badge('Saída','cancelada')}</td><td>${esc(item.category)}</td><td><div class="cell-main">${esc(item.description)}</div><div class="cell-sub">${esc(item.payment_method||'')}</div></td><td class="money-cell ${item.transaction_type==='entry'?'positive':'negative'}">${item.transaction_type==='entry'?'+':'−'} ${money(item.amount)}</td><td>${has('cash.manage')?`<button class="btn small" data-cash-edit="${item.id}">Editar</button>`:''}</td></tr>`).join('')}</tbody></table></div>`;
}

async function renderCash() {
  setPage('Controle de caixa','FINANCEIRO');
  const data=await api('/api/cash');state.cashTransactions=data.transactions||[];
  const c=data.summary;
  $('#content').innerHTML=`<div class="page-head"><div><h1>Caixa</h1><p class="muted">Movimentações exclusivas do perfil ${esc(activeProfile().name||'')}.</p></div>${has('cash.manage')?'<button class="btn primary" id="new-cash">＋ Novo lançamento</button>':''}</div>
    <section class="dashboard-metrics"><article class="stat-card compact" style="--accent:var(--green)"><div class="stat-top"><span>Entradas</span></div><div class="stat-value">${money(c.entries)}</div></article><article class="stat-card compact" style="--accent:var(--red)"><div class="stat-top"><span>Saídas</span></div><div class="stat-value">${money(c.exits)}</div></article><article class="stat-card compact" style="--accent:var(--cyan)"><div class="stat-top"><span>Saldo</span></div><div class="stat-value">${money(c.balance)}</div></article></section>
    <section class="panel"><header class="panel-head"><h3>Lançamentos</h3><span class="muted">${state.cashTransactions.length} registro(s)</span></header>${cashTable(state.cashTransactions)}</section>`;
  $('#new-cash')?.addEventListener('click',()=>openCashForm());
  $$('[data-cash-edit]').forEach(button=>button.addEventListener('click',()=>openCashForm(Number(button.dataset.cashEdit))));
}

function openCashForm(id=null) {
  const item=id?state.cashTransactions.find(row=>row.id===id):{};
  modal(id?'Editar lançamento':'Novo lançamento',`<form id="cash-form" class="form-grid">
    <label>Tipo<select name="transaction_type"><option value="entry" ${item?.transaction_type==='entry'?'selected':''}>Entrada</option><option value="exit" ${item?.transaction_type==='exit'?'selected':''}>Saída</option></select></label>
    <label>Data<input type="date" name="transaction_date" required value="${esc(item?.transaction_date||new Date().toISOString().slice(0,10))}"></label>
    <label>Categoria<input name="category" required value="${esc(item?.category||'')}"></label>
    <label>Valor<input name="amount" type="number" min="0.01" step="0.01" required value="${esc(item?.amount||'')}"></label>
    <label class="full">Descrição<input name="description" required value="${esc(item?.description||'')}"></label>
    <label>Forma de pagamento<input name="payment_method" value="${esc(item?.payment_method||'')}"></label>
    ${id?`<label class="switch-row">Lançamento ativo<input type="checkbox" name="active" ${item.active?'checked':''}></label>`:''}
    <label class="full">Observações<textarea name="notes">${esc(item?.notes||'')}</textarea></label>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $('#cash-form').addEventListener('submit',async event=>{event.preventDefault();try{await api(id?`/api/cash/${id}`:'/api/cash',{method:id?'PUT':'POST',body:formObject(event.currentTarget)});closeModal();toast('Lançamento salvo.');renderCash();}catch(error){toast(error.message,'error');}});
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
  state.baseRoles = data.base_roles || [];
  state.roleData = data;
  return data;
}

async function renderUsers() {
  setPage('Funcionários','USUÁRIOS E ACESSOS');
  const [u,t,r]=await Promise.all([api('/api/users'),api('/api/teams'),loadRoles()]);
  state.users=u.users;state.teams=t.teams;state.roles=r.roles||[];
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Funcionários</h1><p class="muted">Cargos controlam o acesso no servidor, não apenas os botões.</p></div>${has('users.manage')?'<button class="btn primary" id="new-user">＋ Novo usuário</button>':''}</div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>Usuário</th><th>Cargo</th><th>Equipe</th><th>Status</th><th>Último acesso</th><th></th></tr></thead><tbody>${state.users.map(u=>`<tr><td><div class="cell-main">${esc(u.name)}</div><div class="cell-sub">${esc(u.email)}</div></td><td>${badge(u.role_name||roleLabel(u.role_code),u.base_role||u.role_code)}${u.is_contractor?' <span class="badge violet">Contratante</span>':''}${u.platform_role_code?' <span class="badge cyan">Equipe da Plataforma</span>':''}</td><td>${esc(u.team_name||'-')}</td><td>${u.active?badge('Ativo','ok'):badge('Bloqueado','cancelada')}</td><td>${fmtDateTime(u.last_login_at)}</td><td>${has('users.manage')?`<button type="button" class="btn small" data-user-edit="${u.id}">Editar</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
  $('#new-user')?.addEventListener('click',()=>openUserForm());
}

function openUserForm(id=null) {
  const user=id?state.users.find(x=>x.id===id):{};
  const availableRoles=state.roles.filter(role=>role.active || role.code===user?.role_code);
  const hasCurrentRole=availableRoles.some(role=>role.code===user?.role_code);
  const legacyCurrent=user?.role_code&&!hasCurrentRole?`<option value="${esc(user.role_code)}" selected>${esc(user.role_name||roleLabel(user.role_code))} (legado)</option>`:'';
  const roleOptions=legacyCurrent+availableRoles
    .map(role=>`<option value="${esc(role.code)}" ${user?.role_code===role.code?'selected':''}>${esc(role.name)}${role.active?'':' (inativo)'}</option>`).join('');
  modal(id?'Editar usuário':'Novo usuário',`<form id="user-form" class="form-grid">
    <label>Nome<input name="name" required value="${esc(user?.name||'')}"></label>
    <label>E-mail<input type="email" name="email" required value="${esc(user?.email||'')}"></label>
    <label>Cargo<select name="role_code" required>${roleOptions}</select></label>
    <label>Equipe<select name="team_id">${optionList(state.teams,user?.team_id,'Sem equipe')}</select></label>
    <label>${id?'Nova senha (opcional)':'Senha inicial'}<input type="password" name="password" ${id?'':'required'} minlength="8"></label>
    <label class="switch-row">Exigir troca de senha<input type="checkbox" name="must_change_password" ${id?'':'checked'}></label>
    ${id?`<label class="switch-row full">Usuário ativo<input type="checkbox" name="active" ${user.active?'checked':''}></label>`:''}
    ${isPlatformOwner()?`<label class="switch-row full">Responsável Contratante deste perfil<input type="checkbox" name="is_contractor" ${user?.is_contractor?'checked':''}></label>`:''}
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $('#user-form').addEventListener('submit',async e=>{e.preventDefault();try{const payload=formObject(e.currentTarget);if(id&&!payload.password)delete payload.password;await api(id?`/api/users/${id}`:'/api/users',{method:id?'PUT':'POST',body:payload});closeModal();state.users=[];toast('Usuário salvo.');renderUsers();}catch(error){toast(error.message,'error');}});
}

async function renderTeams() {
  setPage('Equipes','ESTRUTURA COMERCIAL');
  const [t,u]=await Promise.all([api('/api/teams'),api('/api/users').catch(()=>({users:[]}))]);
  state.teams=t.teams;if(u.users?.length)state.users=u.users;
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Equipes</h1><p class="muted">Metas e responsáveis configurados sem editar arquivos.</p></div>${has('teams.manage')?'<button class="btn primary" id="new-team">＋ Nova equipe</button>':''}</div>
    <div class="grid-3">${state.teams.map(t=>`<article class="team-card"><div style="display:flex;justify-content:space-between"><h4>${esc(t.name)}</h4>${t.active?badge('Ativa','ok'):badge('Inativa','cancelada')}</div><div class="metric-row"><span>Gerente</span><strong>${esc(t.manager_name||'-')}</strong></div><div class="metric-row"><span>Funcionários</span><strong>${t.members}</strong></div><div class="metric-row"><span>Meta mensal</span><strong>${t.monthly_target}</strong></div>${has('teams.manage')?`<button type="button" class="btn small" data-team-edit="${t.id}">Editar</button>`:''}</article>`).join('')}</div>`;
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
  $('#team-form').addEventListener('submit',async e=>{e.preventDefault();try{await api(id?`/api/teams/${id}`:'/api/teams',{method:id?'PUT':'POST',body:formObject(e.currentTarget)});closeModal();state.teams=[];toast('Equipe salva.');renderTeams();}catch(error){toast(error.message,'error');}});
}

function offeringsUi() {
  return {plans_title:'Planos e serviços',plans_singular:'plano',provider:'Operadora',service:'Serviço',attribute:'Velocidade',coverage:'UFs disponíveis',...(activePreset().admin_labels||{})};
}
async function renderPlans() {
  const ui=offeringsUi();
  setPage(ui.plans_title,'CATÁLOGO DO PERFIL');
  await ensureReferenceData();
  const data=await api('/api/plans?all=1');state.plans=data.plans;
  const canManage=has('plans.manage');
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>${esc(ui.plans_title)}</h1><p class="muted">${canManage?`Cadastros recomendados para o preset ${esc(activePreset().name||'atual')}.`:`Visualização dos itens cadastrados no perfil atual.`}</p></div>${canManage?`<button class="btn primary" id="new-plan">＋ Novo ${esc(ui.plans_singular)}</button>`:badge('Somente leitura','cyan')}</div>
    <section class="panel"><div class="table-wrap"><table class="data-table"><thead><tr><th>${esc(String(ui.plans_singular).replace(/^./,c=>c.toUpperCase()))}</th><th>${esc(ui.provider)}</th><th>${esc(ui.service)}</th><th>${esc(ui.attribute)}</th><th>Preço</th><th>${esc(ui.coverage)}</th><th>Status</th>${canManage?'<th></th>':''}</tr></thead><tbody>${state.plans.map(p=>`<tr><td><div class="cell-main">${esc(p.name)}</div><div class="cell-sub">${esc(p.benefits||'')}</div></td><td>${esc(p.provider)}</td><td>${esc(p.service)}</td><td>${esc(p.speed||'-')}</td><td>${money(p.price)}</td><td>${esc(p.uf_list||'Todas')}</td><td>${p.active?badge('Ativo','ok'):badge('Inativo','cancelada')}</td>${canManage?`<td><button type="button" class="btn small" data-plan-edit="${p.id}">Editar</button></td>`:''}</tr>`).join('')}</tbody></table></div></section>`;
  $('#new-plan')?.addEventListener('click',()=>openPlanForm());
}
function openPlanForm(id=null) {
  const p=id?state.plans.find(x=>x.id===id):{};const ui=offeringsUi();
  modal(id?`Editar ${ui.plans_singular}`:`Novo ${ui.plans_singular}`,`<form id="plan-form" class="form-grid">
    <label>${esc(ui.provider)}<input name="provider" required value="${esc(p?.provider||'')}"></label>
    <label>${esc(ui.service)}<input name="service" required value="${esc(p?.service||'')}"></label>
    <label>Nome<input name="name" required value="${esc(p?.name||'')}"></label>
    <label>${esc(ui.attribute)}<input name="speed" value="${esc(p?.speed||'')}"></label>
    <label>Preço<input name="price" required inputmode="decimal" value="${esc(p?.price??'')}"></label>
    <label>Ordem<input type="number" name="sort_order" value="${p?.sort_order||0}"></label>
    <label class="full">Descrição/Benefícios<textarea name="benefits">${esc(p?.benefits||'')}</textarea></label>
    <label class="full">${esc(ui.coverage)}<input name="uf_list" value="${esc(p?.uf_list||'')}"></label>
    <label class="switch-row full">Item ativo<input type="checkbox" name="active" ${p?.active!==0?'checked':''}></label>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $('#plan-form').addEventListener('submit',async e=>{e.preventDefault();try{await api(id?`/api/plans/${id}`:'/api/plans',{method:id?'PUT':'POST',body:formObject(e.currentTarget)});closeModal();state.plans=[];toast('Cadastro salvo.');renderPlans();}catch(error){toast(error.message,'error');}});
}

const baseCategoryLabels={provider:'Operadoras',service:'Serviços',sale_status:'Status da venda',activation_status:'Ativação',biometric_status:'Biometria',installation_status:'Instalação',appointment_status:'Agendamento',payment_method:'Formas de pagamento',due_day:'Vencimentos',sales_channel:'Canais de venda',period:'Períodos',property_type:'Tipos de imóvel',cancellation_reason:'Motivos de cancelamento'};
function humanizeCode(value){return String(value||'').replace(/^p\d+_/,'').replaceAll('_',' ').replace(/\b\w/g,char=>char.toUpperCase());}
function currentCategoryLabels(){
  const labels={...(activePreset().catalog_labels||{})};
  if(activeProfile()?.business_type==='internet_sales')Object.assign(labels,baseCategoryLabels);
  Object.keys(state.catalogs||{}).forEach(category=>{if(!labels[category])labels[category]=humanizeCode(category);});
  return labels;
}
async function renderCatalogs() {
  setPage('Catálogos','CONFIGURAÇÕES DO SISTEMA');
  const data=await api('/api/catalogs?all=1');state.catalogs=data.catalogs;
  const categoryLabels=currentCategoryLabels();
  const categories=Object.keys({...categoryLabels,...state.catalogs});
  const canManage=has('catalogs.manage');
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Opções configuráveis</h1><p class="muted">${canManage?'Itens usados em vendas antigas são desativados, não apagados.':'Visualização dos catálogos e status do perfil atual.'}</p></div>${canManage?'<button class="btn primary" id="new-catalog">＋ Novo item</button>':badge('Somente leitura','cyan')}</div>
    <div class="grid-2">${categories.map(cat=>`<section class="panel"><header class="panel-head"><h3>${esc(categoryLabels[cat]||cat)}</h3><span class="badge cyan">${(state.catalogs[cat]||[]).length}</span></header><div class="panel-body">${(state.catalogs[cat]||[]).map(i=>`<div class="team-card" style="margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;gap:10px"><div><strong>${esc(i.label)}</strong><div class="code">${esc(i.code)}</div></div><div class="actions">${i.active?badge('Ativo','ok'):badge('Inativo','cancelada')}${canManage?`<button type="button" class="btn small" data-catalog-edit="${i.id}" data-catalog-category="${esc(cat)}">Editar</button>`:''}</div></div>`).join('')||'<div class="empty">Sem itens.</div>'}</div></section>`).join('')}</div>`;
  $('#new-catalog')?.addEventListener('click',()=>openCatalogForm());
}
function openCatalogForm(id=null,category='') {
  const categoryLabels=currentCategoryLabels();
  const all=Object.values(state.catalogs).flat();const item=id?all.find(x=>x.id===id):{};
  modal(id?'Editar item':'Novo item',`<form id="catalog-form" class="form-grid">
    <label>Categoria<input name="category" required ${id?'disabled':''} value="${esc(item?.category||category)}" list="categories-list"><datalist id="categories-list">${Object.keys(categoryLabels).map(x=>`<option value="${x}">`).join('')}</datalist></label>
    <label>Código<input name="code" required value="${esc(item?.code||'')}"></label>
    <label>Descrição<input name="label" required value="${esc(item?.label||'')}"></label>
    <label>Ordem<input type="number" name="sort_order" value="${item?.sort_order||0}"></label>
    ${id?`<label class="switch-row full">Item ativo<input type="checkbox" name="active" ${item.active?'checked':''}></label>`:''}
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">Salvar</button></div>
  </form>`);
  $('#catalog-form').addEventListener('submit',async e=>{e.preventDefault();try{const payload=formObject(e.currentTarget);if(id)delete payload.category;await api(id?`/api/catalogs/${id}`:'/api/catalogs',{method:id?'PUT':'POST',body:payload});closeModal();state.catalogs={};toast('Catálogo salvo.');renderCatalogs();}catch(error){toast(error.message,'error');}});
}

function permissionModules(data=state.roleData) {
  const modules={};
  (data?.permissions||[]).forEach(permission=>(modules[permission.module]??=[]).push(permission));
  return modules;
}

function rolePermissionsMarkup(role, modules, prefix='role', readOnly=false) {
  const selected=new Set(role?.permissions||[]);
  return Object.entries(modules).map(([module,permissions])=>`<div class="permission-module"><h4>${esc(module)}</h4><div class="check-list">${permissions.map(permission=>`<label class="check-item"><input type="checkbox" value="${esc(permission.code)}" ${selected.has(permission.code)?'checked':''} ${readOnly?'disabled':''}><span>${esc(permission.description)}</span></label>`).join('')}</div></div>`).join('');
}

async function renderRoles() {
  setPage('Cargos e permissões','CONTROLE DE ACESSO');
  const data=await loadRoles();
  const modules=permissionModules(data);
  const editableRoles=data.roles.filter(role=>role.code!=='owner');
  const canManage=has('roles.manage');
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Cargos e permissões</h1><p class="muted">${canManage?'Crie cargos próprios e escolha exatamente o que cada grupo pode acessar. O Dono continua com acesso total.':'Visualização dos cargos e permissões do perfil atual.'}</p></div>${canManage?'<button class="btn primary" id="new-role">＋ Novo cargo</button>':badge('Somente leitura','cyan')}</div>
    <div class="grid-2">${editableRoles.map(role=>`<section class="panel"><header class="panel-head"><div><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><h3>${esc(role.name)}</h3>${role.is_system?badge('Nativo','cyan'):badge('Personalizado','green')}${role.active?badge('Ativo','ok'):badge('Inativo','cancelada')}</div><p class="muted" style="margin-top:6px">${esc(role.description||'Sem descrição')} · Base: ${esc(baseRoleTypeLabels[role.base_role]||role.base_role)} · ${role.users_count||0} usuário(s)</p></div>${canManage?`<div class="actions">${!role.is_system?`<button type="button" class="btn small" data-role-edit="${esc(role.code)}">Editar</button>`:''}<button type="button" class="btn small primary" data-role-save="${esc(role.code)}">Salvar permissões</button></div>`:''}</header><div class="panel-body permission-grid" data-role-box="${esc(role.code)}">${rolePermissionsMarkup(role,modules,'role',!canManage)}</div></section>`).join('')}</div>`;
  $('#new-role')?.addEventListener('click',()=>openRoleForm());
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
  const baseTemplate=(state.baseRoles||[]).find(item=>item.code===baseCode);
  const formRole=role||{permissions:baseTemplate?.permissions||[]};
  modal(role?'Editar cargo':'Novo cargo',`<form id="role-form" class="form-grid">
    <label>Nome do cargo<input name="name" required minlength="2" value="${esc(role?.name||'')}" placeholder="Ex.: Supervisor"></label>
    <label>Código interno<input name="code" required pattern="[a-z0-9_]+" value="${esc(role?.code||'')}" ${role?'readonly':''} placeholder="supervisor"></label>
    <label>Cargo-base<select name="base_role" required><option value="seller" ${baseCode==='seller'?'selected':''}>Operação principal</option><option value="bko" ${baseCode==='bko'?'selected':''}>Suporte / apoio</option><option value="manager" ${baseCode==='manager'?'selected':''}>Gestão</option></select></label>
    ${role?`<label class="switch-row">Cargo ativo<input type="checkbox" name="active" ${role.active?'checked':''}></label>`:''}
    <label class="full">Descrição<textarea name="description" placeholder="Responsabilidade e objetivo do cargo">${esc(role?.description||'')}</textarea></label>
    <div class="form-section full">Permissões</div>
    <div class="full permission-grid" data-role-form-permissions>${rolePermissionsMarkup(formRole,modules,'form')}</div>
    <div class="full page-actions" style="justify-content:flex-end"><button type="button" class="btn ghost" data-close-modal>Cancelar</button><button class="btn primary">${role?'Salvar cargo':'Criar cargo'}</button></div>
  </form>`,{wide:true});
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
  const data=await api('/api/integrations');
  const i=data.integrations;
  const ai=i.ai||{};
  const groq=i.groq||{};
  const openai=i.openai||{};
  const providerEnvironment=Boolean((window.ONE_CRM_AI_PROVIDER_SOURCE||'')==='environment');
  const savedProvider=i.ai_provider?.value||ai.requested_provider||'auto';
  const canManage=has('integrations.manage');
  const readOnly=canManage?'':'disabled';
  $('#content').innerHTML=`
    <div class="page-head"><div><h1>Central de integrações</h1><p class="muted">${canManage?'As chaves ficam apenas no Railway. O navegador recebe somente o estado da configuração.':'Visualização do estado das conexões do perfil atual.'}</p></div>${canManage?'':badge('Somente leitura','cyan')}</div>
    <section class="panel"><header class="panel-head"><h3>Configurações gerais</h3></header><div class="panel-body"><form id="integrations-form" class="form-grid">
      <label class="full">Power BI Embed URL<input name="powerbi_embed_url" value="${esc(i.powerbi_embed_url.value)}" ${readOnly} placeholder="https://app.powerbi.com/view?... "><small class="muted">URL incorporada pronta para uso em relatórios.</small></label>
      <label class="full">Webhook genérico<input name="generic_webhook_url" value="${esc(i.generic_webhook_url.value)}" ${readOnly} placeholder="https://seu-n8n/webhook/one-crm"><small class="muted">Recebe eventos sale.created, sale.updated e sale.workflow_updated.</small></label>
      <label>Evolution API URL<input name="evolution_api_url" value="${esc(i.evolution_api_url.value)}" ${readOnly}></label>
      <label>Evolution API Key<input name="evolution_api_key" type="password" value="${esc(i.evolution_api_key.value)}" ${readOnly}><small class="muted">${i.evolution_api_key.configured?'Já configurada.':''}</small></label>
      <label class="full">Provedor do ONE Intelligence<select name="ai_provider" ${readOnly}>
        <option value="auto" ${savedProvider==='auto'?'selected':''}>Automático: Groq → OpenAI → Local</option>
        <option value="groq" ${savedProvider==='groq'?'selected':''}>GroqCloud</option>
        <option value="openai" ${savedProvider==='openai'?'selected':''}>OpenAI</option>
        <option value="local" ${savedProvider==='local'?'selected':''}>Somente análise local</option>
      </select><small class="muted">A variável ONE_CRM_AI_PROVIDER no Railway, quando definida, tem prioridade sobre esta seleção.</small></label>
      <label>Modelo Groq<input name="groq_model" value="${esc(i.groq_model.value||groq.model||'llama-3.1-8b-instant')}" ${(groq.model_source==='environment'||!canManage)?'disabled':''}><small class="muted">${groq.model_source==='environment'?'Controlado por GROQ_MODEL no Railway.':'Recomendado para o plano gratuito: llama-3.1-8b-instant.'}</small></label>
      <label>Modelo OpenAI<input name="openai_model" value="${esc(i.openai_model.value||openai.model||'gpt-5.6-luna')}" ${(openai.model_source==='environment'||!canManage)?'disabled':''}><small class="muted">Opcional; usado somente quando houver chave e saldo.</small></label>
      <div class="integration-secret-box"><div><strong>Chave GroqCloud</strong><p>${groq.configured?'GROQ_API_KEY foi encontrada no Railway.':'GROQ_API_KEY ainda não foi configurada no Railway.'}</p><small>A chave nunca é salva no SQLite nem volta ao navegador.</small></div>${groq.configured?badge('Configurada','ok'):badge('Ausente','cancelada')}</div>
      <div class="integration-secret-box"><div><strong>Chave OpenAI</strong><p>${openai.configured?'OPENAI_API_KEY foi encontrada no Railway.':'OPENAI_API_KEY é opcional e está ausente.'}</p><small>Pode permanecer desativada enquanto não houver faturamento.</small></div>${openai.configured?badge('Configurada','ok'):badge('Opcional','aguard')}</div>
      ${canManage?`<div class="full page-actions integration-actions"><button type="button" class="btn" id="test-groq" ${groq.configured?'':'disabled'}>Testar Groq</button><button type="button" class="btn" id="test-openai" ${openai.configured?'':'disabled'}>Testar OpenAI</button><button type="button" class="btn" id="test-local">Testar modo local</button><button class="btn primary">Salvar integrações</button></div>`:''}
    </form></div></section>
    <section class="panel"><header class="panel-head"><h3>Estado dos conectores</h3></header><div class="panel-body grid-2">
      <div class="team-card"><h4>Power BI</h4><p>${esc(data.notes.powerbi)}</p>${i.powerbi_embed_url.configured?badge('Configurado','ok'):badge('Não configurado','aguard')}</div>
      <div class="team-card"><h4>Webhook / N8N</h4><p>${esc(data.notes.webhook)}</p>${i.generic_webhook_url.configured?badge('Configurado','ok'):badge('Não configurado','aguard')}</div>
      <div class="team-card"><h4>Evolution API</h4><p>${esc(data.notes.evolution)}</p>${i.evolution_api_key.configured?badge('Credencial salva','ok'):badge('Pendente','aguard')}</div>
      <div class="team-card"><h4>ONE Intelligence</h4><p>${esc(data.notes.ai)}</p>${ai.ready?badge(`${ai.provider_label} · ${ai.model}`,'ok'):badge('Desativado','aguard')}</div>
      <div class="team-card"><h4>GroqCloud</h4><p>${esc(data.notes.groq)}</p>${groq.configured?badge(`Ativo · ${groq.model}`,'ok'):badge('Não configurado','aguard')}</div>
      <div class="team-card"><h4>OpenAI</h4><p>${esc(data.notes.openai)}</p>${openai.configured?badge(`Disponível · ${openai.model}`,'ok'):badge('Opcional','aguard')}</div>
    </div></section>`;
  if(canManage) $('#integrations-form').addEventListener('submit',async e=>{e.preventDefault();try{const payload=formObject(e.currentTarget);delete payload.openai_api_key;delete payload.groq_api_key;await api('/api/integrations',{method:'PUT',body:payload});toast('Integrações atualizadas.');renderIntegrations();}catch(error){toast(error.message,'error');}});
  const testProvider=async(button,provider)=>{button.disabled=true;const original=button.textContent;button.textContent='Testando...';try{const result=await api('/api/ai/test',{method:'POST',body:{provider}});toast(`${result.message} Modelo: ${result.model}`);}catch(error){toast(error.message,'error');}finally{button.disabled=false;button.textContent=original;}};
  $('#test-groq')?.addEventListener('click',e=>testProvider(e.currentTarget,'groq'));
  $('#test-openai')?.addEventListener('click',e=>testProvider(e.currentTarget,'openai'));
  $('#test-local')?.addEventListener('click',e=>testProvider(e.currentTarget,'local'));
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

// ------------------------- ONE CRM 2.6 · produtividade -------------------------
async function renderWorkCenter() {
  setPage('Central de produtividade','OPERAÇÃO');
  const [taskData,notificationData,automationData,formData,dashboardData,alertData] = await Promise.all([
    api('/api/tasks').catch(()=>({tasks:[]})),
    api('/api/notifications').catch(()=>({notifications:[],unread:0})),
    has('automations.manage') ? api('/api/automations').catch(()=>({rules:[]})) : Promise.resolve({rules:[]}),
    has('forms.manage') ? api('/api/custom-forms').catch(()=>({forms:[]})) : Promise.resolve({forms:[]}),
    has('reports.manage') ? api('/api/custom-dashboards').catch(()=>({dashboards:[]})) : Promise.resolve({dashboards:[]}),
    has('security.alerts') ? api('/api/security-alerts').catch(()=>({alerts:[]})) : Promise.resolve({alerts:[]}),
  ]);
  $('#content').innerHTML = `
    <div class="page-actions"><div><h2>Trabalho, automações e alertas</h2><p class="muted">Tarefas, notificações, formulários e relatórios do perfil atual.</p></div>${has('tasks.manage')?'<button class="btn primary" id="new-productivity-task">+ Nova tarefa</button>':''}</div>
    <div class="metric-grid"><article class="metric"><span>Tarefas abertas</span><strong>${taskData.tasks.filter(x=>x.status!=='done').length}</strong></article><article class="metric"><span>Notificações não lidas</span><strong>${notificationData.unread||0}</strong></article><article class="metric"><span>Automações ativas</span><strong>${automationData.rules.filter(x=>x.active).length}</strong></article><article class="metric"><span>Alertas de segurança</span><strong>${alertData.alerts.filter(x=>!x.resolved_at).length}</strong></article></div>
    <div class="profile-grid">
      <section class="panel"><div class="panel-head"><h3>Tarefas</h3></div><div class="table-wrap"><table><thead><tr><th>Tarefa</th><th>Responsável</th><th>Prazo</th><th>Status</th></tr></thead><tbody>${taskData.tasks.map(t=>`<tr><td><strong>${esc(t.title)}</strong><small class="block muted">${esc(t.description||'')}</small></td><td>${esc(t.assigned_name||'-')}</td><td>${fmtDateTime(t.due_at)}</td><td>${badge(t.overdue?'Atrasada':t.status,t.overdue?'vencida':t.status)}</td></tr>`).join('')||'<tr><td colspan="4" class="muted">Nenhuma tarefa cadastrada.</td></tr>'}</tbody></table></div></section>
      <section class="panel"><div class="panel-head"><h3>Notificações</h3></div><div class="stack-list">${notificationData.notifications.slice(0,15).map(n=>`<article class="list-card"><strong>${esc(n.title)}</strong><p>${esc(n.message)}</p><small>${fmtDateTime(n.created_at)} ${n.read_at?'· lida':'· não lida'}</small></article>`).join('')||'<div class="empty">Nenhuma notificação.</div>'}</div></section>
    </div>
    <div class="profile-grid">
      <section class="panel"><div class="panel-head"><h3>Automações</h3>${has('automations.manage')?'<button class="btn" id="new-automation">Nova regra</button>':''}</div><div class="stack-list">${automationData.rules.map(r=>`<article class="list-card"><strong>${esc(r.name)}</strong><p>Gatilho: ${esc(r.trigger_event)}</p><small>${r.active?'Ativa':'Inativa'}${r.last_run_at?' · última execução '+fmtDateTime(r.last_run_at):''}</small></article>`).join('')||'<div class="empty">Nenhuma automação.</div>'}</div></section>
      <section class="panel"><div class="panel-head"><h3>Formulários personalizados</h3>${has('forms.manage')?'<button class="btn" id="new-custom-form">Novo formulário</button>':''}</div><div class="stack-list">${formData.forms.map(f=>`<article class="list-card"><strong>${esc(f.name)}</strong><p>${esc(f.description||'Sem descrição')}</p><small>${f.schema.length} campo(s)</small></article>`).join('')||'<div class="empty">Nenhum formulário personalizado.</div>'}</div></section>
    </div>
    <div class="profile-grid">
      <section class="panel"><div class="panel-head"><h3>Dashboards personalizados</h3>${has('reports.manage')?'<button class="btn" id="new-dashboard-view">Nova visão</button>':''}</div><div class="stack-list">${dashboardData.dashboards.map(d=>`<article class="list-card"><strong>${esc(d.name)}</strong><p>${d.is_default?'Visão padrão':'Visão personalizada'}</p></article>`).join('')||'<div class="empty">Nenhuma visão personalizada.</div>'}</div></section>
      <section class="panel"><div class="panel-head"><h3>Alertas de segurança</h3></div><div class="stack-list">${alertData.alerts.slice(0,15).map(a=>`<article class="list-card"><strong>${esc(a.title)}</strong><p>${esc(a.alert_type)} · ${esc(a.severity)}</p><small>${fmtDateTime(a.created_at)}</small></article>`).join('')||'<div class="empty">Nenhum alerta de segurança.</div>'}</div></section>
    </div>`;
  $('#new-productivity-task')?.addEventListener('click',openProductivityTaskForm);
  $('#new-automation')?.addEventListener('click',openAutomationForm);
  $('#new-custom-form')?.addEventListener('click',openCustomFormBuilder);
  $('#new-dashboard-view')?.addEventListener('click',openDashboardViewForm);
}

function openProductivityTaskForm(){
  modal('Nova tarefa',`<form id="productivity-task-form" class="form-grid"><label class="full">Título<input name="title" required></label><label class="full">Descrição<textarea name="description"></textarea></label><label>Prioridade<select name="priority"><option value="low">Baixa</option><option value="normal" selected>Normal</option><option value="high">Alta</option><option value="urgent">Urgente</option></select></label><label>Prazo<input name="due_at" type="datetime-local"></label><div class="full form-actions"><button class="btn" type="button" data-close-modal>Cancelar</button><button class="btn primary" type="submit">Criar tarefa</button></div></form>`,{wide:true});
  $('#productivity-task-form').addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/tasks',{method:'POST',body:formObject(e.currentTarget)});closeModal();toast('Tarefa criada.');renderWorkCenter();}catch(error){toast(error.message,'error');}});
}
function openAutomationForm(){
  modal('Nova automação',`<form id="automation-form" class="form-grid"><label>Nome<input name="name" required></label><label>Gatilho<select name="trigger_event"><option value="task.created">Tarefa criada</option><option value="task.updated">Tarefa atualizada</option><option value="form.submitted">Formulário enviado</option></select></label><label class="full">Condições (JSON)<textarea name="conditions">{}</textarea></label><label class="full">Ações (JSON)<textarea name="actions">[{"type":"notify","user_id":1,"title":"Automação","message":"Uma condição foi atendida."}]</textarea></label><div class="full form-actions"><button class="btn" type="button" data-close-modal>Cancelar</button><button class="btn primary" type="submit">Salvar</button></div></form>`,{wide:true});
  $('#automation-form').addEventListener('submit',async e=>{e.preventDefault();const d=formObject(e.currentTarget);try{d.conditions=JSON.parse(d.conditions||'{}');d.actions=JSON.parse(d.actions||'[]');d.active=true;await api('/api/automations',{method:'POST',body:d});closeModal();toast('Automação salva.');renderWorkCenter();}catch(error){toast(error.message,'error');}});
}
function openCustomFormBuilder(){
  modal('Novo formulário',`<form id="custom-form-builder" class="form-grid"><label>Nome<input name="name" required></label><label>Código<input name="code" placeholder="ex.: vistoria_tecnica"></label><label class="full">Descrição<textarea name="description"></textarea></label><label class="full">Campos (JSON)<textarea name="schema">[{"key":"nome","label":"Nome","type":"text","required":true}]</textarea></label><div class="full form-actions"><button class="btn" type="button" data-close-modal>Cancelar</button><button class="btn primary" type="submit">Criar formulário</button></div></form>`,{wide:true});
  $('#custom-form-builder').addEventListener('submit',async e=>{e.preventDefault();const d=formObject(e.currentTarget);try{d.schema=JSON.parse(d.schema||'[]');await api('/api/custom-forms',{method:'POST',body:d});closeModal();toast('Formulário criado.');renderWorkCenter();}catch(error){toast(error.message,'error');}});
}
function openDashboardViewForm(){
  modal('Nova visão de dashboard',`<form id="dashboard-view-form" class="form-grid"><label class="full">Nome<input name="name" required></label><label class="full">Configuração dos widgets (JSON)<textarea name="config">{"widgets":["summary","tasks","notifications"]}</textarea></label><label class="check-item full"><input name="shared" type="checkbox"><span>Compartilhar com o perfil</span></label><label class="check-item full"><input name="is_default" type="checkbox"><span>Usar como padrão</span></label><div class="full form-actions"><button class="btn" type="button" data-close-modal>Cancelar</button><button class="btn primary" type="submit">Salvar visão</button></div></form>`,{wide:true});
  $('#dashboard-view-form').addEventListener('submit',async e=>{e.preventDefault();const d=formObject(e.currentTarget);try{d.config=JSON.parse(d.config||'{}');await api('/api/custom-dashboards',{method:'POST',body:d});closeModal();toast('Visão salva.');renderWorkCenter();}catch(error){toast(error.message,'error');}});
}
