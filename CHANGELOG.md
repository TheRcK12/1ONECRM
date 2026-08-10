# ONE CRM 2.6.7-beta.1

- Substitui o seletor de cor nativo do sistema operacional por um editor próprio do ONE CRM.
- Adiciona painel visual de saturação e brilho, faixa de matiz, entrada HEX e leitura RGB.
- Adiciona cores rápidas, prévia dinâmica e brilho neon calculado em tempo real.
- Mantém a persistência de cor por usuário introduzida na 2.6.6.
- Melhora responsividade e navegação por teclado no editor de cor.

# Changelog

## 2.6.6-beta.1 — Aparência personalizável

- Mantém neon discreto somente em foco, navegação ativa e ações principais.
- Cor de destaque passa a ser preferência individual do usuário.
- Inclui presets Verde neon, Ciano, Azul elétrico, Roxo, Rosa e Âmbar.
- Permite escolher uma cor personalizada pelo seletor nativo de cor.
- Adiciona fundos escuros Grafite, Meia-noite, Obsidiana e Floresta escura.
- Preferências ficam persistidas no banco e reaplicadas em qualquer dispositivo após login.
- Mantém tema claro/escuro e todas as funções da 2.6.5.

## 2.6.5-beta.1 — Paleta executiva

- Troca o ciano neon dominante por uma paleta grafite + azul frio mais sóbria.
- Reduz saturação de navegação, botões, focos, builders e dashboards sem perder contraste.
- Mantém verde, âmbar e vermelho somente como cores semânticas de estado.
- Atualiza a identidade cromática do logo para azul aço e azul profundo.
- Refina também o tema claro para tons neutros azulados.
- Atualiza cache dos assets, versão do servidor e label Docker para 2.6.5-beta.1.

# 2.6.3-beta.1


## 2.6.4-beta.1 — Refinamento visual B2B

- Reorganiza a navegação superior em grupos mais claros: Vendas, Análises, Produtividade, Plataforma e Administrativo.
- Substitui símbolos Unicode de navegação por um conjunto consistente de ícones SVG internos.
- Redesenha a Dashboard principal com hierarquia assimétrica: desempenho comercial + acompanhamento operacional, evitando seis cards idênticos.
- Compacta cabeçalho, navegação, botões, painéis e modais para aumentar densidade útil sem prejudicar a legibilidade.
- Remove gradientes e sombras excessivos das áreas operacionais e reduz a aparência de template genérico.
- Mantém as dashboards personalizadas, produtividade, backups, permissões e demais funções da 2.6.3.
- Atualiza cache dos assets, versão do servidor e label da imagem Docker para 2.6.4-beta.1.

- Conecta dashboards personalizados à página Dashboard principal.
- Adiciona seletor entre Dashboard padrão e visões pessoais/compartilhadas.
- Visões marcadas como padrão passam a abrir automaticamente quando não existe preferência do usuário.
- Renderiza de verdade os widgets Resumo, Tarefas, Notificações, Automações, Formulários e Segurança.
- Usuários com `dashboard.view` podem consumir visões compartilhadas; somente `reports.manage` continua podendo criar ou editar.
- Corrige escopo de edição de dashboards pessoais e garante apenas um padrão por escopo.
- Formulários personalizados passam a informar quantidade de envios para uso nos widgets.
- Atualiza cache de frontend, Docker e versão para 2.6.3-beta.1.

# 2.6.2-beta.1

- Substitui os campos JSON das automações por um construtor visual com gatilho, condição e múltiplas ações.
- Substitui o JSON do construtor de formulários por campos adicionáveis e configuráveis pela interface.
- Substitui o JSON das visões de dashboard por seleção visual de widgets.
- Reorganiza a Central de Produtividade com cards, métricas, listas e tabelas responsivas.
- Permite escolher responsável ao criar tarefa e editar automações, formulários e visões já cadastrados.
- Corrige alinhamento e responsividade do cabeçalho, seletor de perfil, busca e controles da conta.
- Atualiza o cache-busting dos arquivos estáticos para 2.6.2.
- Corrige o Dockerfile para incluir `one_crm_productivity.py` na imagem Railway.

# 2.6.1-beta.1

- Restaura a aba **Backups** no menu Administrativo do Dono da Plataforma.
- Backups deixam de depender dos módulos habilitados no preset ativo.
- A rota `#/backups` redireciona usuários sem acesso global.
- As APIs de listar e criar backups agora exigem Dono da Plataforma no backend.
- A página passa a identificar o backup como recurso global da plataforma.

# 2.6.0-beta.1

- Convites e recuperação de senha por e-mail, com tokens expirados e uso único.
- Tarefas, notificações, prazos e central de produtividade.
- Motor inicial de automações por eventos.
- Formulários e campos personalizados por perfil.
- Anexos isolados no Volume com hash SHA-256 e limite de tamanho.
- Dashboards personalizados e alertas de segurança.
- Guias de homologação, rollback e migração controlada para PostgreSQL.
- Mantém SQLite em produção até a migração ser validada em homologação.

# 2.5.3-beta.1

- Corrige horários de acesso exibidos três horas no futuro.
- Datas e horas armazenadas em UTC passam a ser interpretadas corretamente no navegador.
- A apresentação é fixada no fuso `America/Sao_Paulo` (horário de Brasília).
- Registros históricos sem indicador de fuso permanecem compatíveis e passam a aparecer corretamente.
- A correção central também alcança auditoria e outras telas que utilizam `fmtDateTime`.

# 2.5.2-beta.1

- Corrige modais e gavetas que fechavam ao clicar em inputs, selects, checkboxes ou áreas internas.
- Remove manipuladores `onclick` inline incompatíveis com a Content Security Policy da versão de produção.
- Adiciona eventos delegados seguros para navegação, edição e ações dinâmicas.
- O fundo continua fechando a janela apenas quando clicado diretamente.

# 2.5.1-beta.1

- Corrige falha de build no Railway causada por `COPY data/.keep /app/data/.keep`.
- O diretório `/app/data` agora é criado diretamente no Dockerfile.
- Mantém o Volume persistente esperado em `/app/data`.

# ONE CRM 2.5.0-beta.1

## Railway Production

- Volume obrigatório em produção, com falha segura quando ausente.
- Token forte obrigatório antes da criação do primeiro Dono.
- Entrypoint corrige permissões do Volume e abandona privilégios.
- Cookies `SameSite=Strict` e cabeçalhos de segurança ampliados.
- Content Security Policy sem JavaScript inline.
- Validação de origem em requisições de escrita.
- Healthcheck ampliado para banco e armazenamento.
- GitHub Actions, Docker smoke test, CodeQL e Dependabot.
- Documentação e variáveis do Railway atualizadas.

---

# ONE CRM 2.4.0-beta.1

- Nova aba Acessos da Plataforma, visível somente para Donos.
- Criação de outros Donos, administradores e cargos globais personalizados.
- Funcionários globais podem ser vinculados a um ou vários perfis.
- Administradores acessam somente os perfis atribuídos e não conseguem criar Donos.
- Funcionários globais foram separados da lista de funcionários de cada perfil.
- Proteção do último Dono ativo e auditoria das alterações globais.

# ONE CRM 2.3.0-beta.1

- Revisão completa dos presets e formulários de cada segmento.
- Campos de prazo e valor aparecem somente quando fazem sentido.
- RH: candidatos selecionam vagas abertas já cadastradas; entrevistas selecionam candidato e vaga.
- Relações entre clientes, ordens, imóveis, propostas, projetos, devedores e demais registros agora usam seletores.
- Catálogos exibem somente categorias do perfil ativo.
- Cargos exibem somente cargos do perfil ativo e permissões relacionadas aos módulos habilitados.
- Validação no backend impede referências, planos e opções de catálogo de outro perfil.

# Changelog

## 2.0.1-beta.1 · Contratante somente leitura

- O Contratante passou a atuar como administrador de visualização do próprio perfil.
- Somente o Dono da Plataforma pode alterar identidade, tipo, módulos ou responsável de um perfil.
- Removidas do Contratante as permissões de criação, edição, tratamento e configuração.
- Adicionadas visualizações somente leitura de planos, catálogos, cargos, integrações, usuários, equipes, auditoria, vendas e caixa.
- O backend rejeita tentativas de alteração mesmo quando a chamada é feita diretamente pela API.
- O cargo exibido na conta do responsável passa a ser **Contratante**.
- A permissão legada `profile.configure` é removida automaticamente do banco.

## 2.0.0-beta.1 · Perfis de negócio isolados

- Adicionado painel **Perfis** exclusivo para o Dono da Plataforma.
- Dono pode criar, configurar, ativar, desativar e alternar entre perfis.
- Adicionado cargo operacional **Contratante**, limitado ao perfil pelo qual é responsável.
- Usuários, equipes, cargos, planos, catálogos, vendas, auditoria, integrações e IA agora são isolados por perfil.
- O banco existente é migrado automaticamente para o perfil inicial **Operação principal**.
- Adicionados modelos de perfil: Venda de internet, Controle de caixa e Prestação de serviços.
- Adicionado módulo inicial de Controle de Caixa com entradas, saídas, saldo, categorias e histórico.
- Inteligência artificial e webhooks passaram a respeitar o perfil ativo.
- Adicionado seletor de perfil no cabeçalho para o Dono.
- Adicionado teste automático de isolamento entre perfis e permissões do Contratante.
- Mantida compatibilidade com o Volume e o banco SQLite existente no Railway.

## 1.9.0-beta.1

- Adicionado GroqCloud como provedor principal de IA.
- Adicionada seleção Automático, Groq, OpenAI ou Local.
- Fallback local automático quando a cota externa acaba ou o provedor falha.
- Tela de integrações agora mostra e testa cada provedor separadamente.
- Contexto da IA inclui distribuição por UF e desempenho por equipe.
- Logs de uso registram provedor e uso de fallback.
- OpenAI permanece opcional.


## 1.7.0-beta.1 · Cargos dinâmicos

- Dono pode criar cargos personalizados dentro do ONE CRM.
- Cada cargo possui nome, código, descrição, cargo-base, status e permissões próprias.
- Cargos personalizados podem herdar o comportamento operacional de Gerente, BKO ou Vendedor.
- Usuários podem ser vinculados aos novos cargos pela tela Funcionários.
- Permissões são aplicadas no servidor e atualizadas sem alterar arquivos.
- Cargos nativos permanecem protegidos e o Dono continua com acesso total.
- Migração automática adiciona a coluna necessária ao banco já existente no Railway.
- Incluídos testes de criação, edição, vinculação e autenticação com cargo personalizado.

## 1.6.0-beta.1 · Online / Railway

- Adicionado Dockerfile e configuração `railway.json`.
- Servidor passa a usar automaticamente `PORT` e `0.0.0.0` no Railway.
- Healthcheck conectado ao banco em `/api/health`.
- Dados, backups e logs usam automaticamente o Railway Volume.
- Cookies seguros no HTTPS e identificação do IP real atrás do proxy.
- Token opcional protege a criação pública do primeiro Dono.
- Encerramento limpo ao receber SIGTERM da hospedagem.
- Rotação de logs e retenção dos 14 backups automáticos mais recentes.
- Criado teste específico do modo online.
- Funcionamento local e banco legado continuam compatíveis.

## 1.5.0-beta.1

- Página de login totalmente redesenhada em layout dividido, inspirada na organização do OMNI sem copiar sua identidade.
- Painel visual criado apenas com HTML, CSS e SVG, sem depender de imagens externas.
- Campos de e-mail e senha com ícones, foco aprimorado e melhor hierarquia visual.
- Botão para mostrar ou ocultar a senha.
- Opção local para lembrar somente o e-mail do usuário.
- Alternância de tema claro e escuro disponível também antes do login.
- Tela de criação do primeiro Dono adaptada ao mesmo padrão visual.
- Layout responsivo: a área ilustrativa é ocultada em telas menores para preservar espaço.


## 1.4.1-beta.1

- Corrigido o falso timeout do teste no Windows causado pelo buffer de saída do processo filho.
- O teste agora grava a saída do servidor em arquivo temporário, sem bloquear o servidor.
- Portas de teste agora são escolhidas dinamicamente para evitar conflito com processos existentes.
- Respostas HTTP passam a encerrar a conexão explicitamente.
- Servidor multithread reforçado com threads daemon, reutilização de endereço e fila ampliada.
- Todas as respostas do cliente de teste são fechadas corretamente.
- Timeout de comunicação aumentado e mensagens de falha ficaram mais claras.
- O `403` esperado para o BKO agora é identificado no progresso do teste, evitando confusão.
- Log multithread protegido contra linhas misturadas.

## 1.4.0-beta.1

### CEP

- Consulta em cascata por BrasilAPI, ViaCEP e OpenCEP.
- Duas tentativas curtas por provedor em falhas transitórias.
- Cache local preservado e usado como contingência quando a atualização externa falha.
- Botão Consultar força uma atualização, sem descartar um cache válido.
- Consulta direta pelo navegador como última contingência.
- Respostas antigas ou de outro CEP não sobrescrevem mais o formulário.
- Resultados inválidos não são gravados no cache.

### Identidade visual

- Removidas as referências visuais restantes ao nome anterior.
- Módulo renomeado para ONE Intelligence.
- Adicionada logo vetorial do ONE CRM e favicon.
- Tipografia revisada com pesos mais leves.

## 1.3.0-beta.1

- Menu lateral removido.
- Navegação totalmente movida para o topo.
- Botão Administrativo com sub-abas por permissão.
- Vendas agrupadas em sub-abas.
- Subnavegação persistente e responsiva.

## 1.2.1-beta.1

- Dashboard disponível como aba superior.
- Resumo de hoje removido para evitar duplicidade.
- Vendas recentes passam a ocupar toda a largura.

## 1.2.0-beta.1

- Sistema renomeado visualmente para ONE CRM.
- Dashboard reorganizada.
- Adicionado tema claro e escuro.
- Criada a área de perfil do usuário.
- Compatibilidade com o banco legado preservada.

## 1.8.0-beta.1

- Integração real com a OpenAI pela Responses API.
- Chave lida exclusivamente de `OPENAI_API_KEY` no servidor.
- Novo módulo `one_crm_ai.py`, sem dependências externas.
- Chat operacional na página ONE Intelligence.
- Sugestões rápidas e contexto opcional de uma venda específica.
- Contexto limitado pelas permissões e pelo escopo de vendas do usuário.
- Remoção de CPF, telefone, e-mail e endereço completo do contexto da IA.
- Nova permissão `ai.use` configurável por cargo.
- Teste de conexão na página Integrações.
- Limite de requisições por usuário e auditoria de uso.
- Registro somente de metadados técnicos em `ai_usage_logs`.

## 2.1.0-beta.1
- Adicionados presets de perfis para venda de internet, caixa, serviços, CRM geral, cobrança, pós-venda, imobiliária, varejo, consultoria, recrutamento e perfil personalizado.
- Cada preset possui categoria, descrição, indicação de uso e módulos recomendados.
- Criação de perfil ganhou pré-visualização do preset e atualização automática dos módulos.

## 2.2.0-beta.1

- Presets deixam de ser apenas combinações de checkboxes e passam a montar uma estrutura operacional completa.
- Cada segmento recebe somente as abas coerentes com seu negócio; módulos de venda de internet, como BKO e biometria, não aparecem em perfis imobiliários, financeiros ou de serviços.
- Adicionados cargos iniciais específicos por preset, com permissões próprias.
- Adicionados catálogos, status e listas iniciais de cada segmento.
- Adicionados planos, produtos ou serviços recomendados conforme o preset.
- Criado o cadastro genérico de registros por módulo para imóveis, visitas, propostas, ordens de serviço, chamados, projetos, vagas, candidatos, estoque e demais operações.
- A Dashboard passa a resumir os módulos específicos do perfil ativo.
- Perfis criados em versões anteriores recebem migração automática para a estrutura completa do preset escolhido.
