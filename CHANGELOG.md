# Changelog

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
