# ONE CRM 2.0 · Perfis de negócio

O ONE CRM agora aceita ambientes de negócio isolados dentro da mesma instalação. O **Dono da Plataforma** administra todos os perfis; cada **Contratante** administra somente o próprio perfil.

## Perfis disponíveis

- **Venda de internet:** mantém o fluxo comercial, BKO, biometria, instalação, ranking e planos.
- **Controle de caixa:** adiciona entradas, saídas, saldo, categorias e histórico financeiro.
- **Prestação de serviços:** modelo inicial genérico usando clientes, equipes, acompanhamento e catálogos.

> O modelo de Prestação de serviços é uma base configurável. Ele ainda não possui um módulo dedicado de ordens de serviço, agenda técnica ou SLA.

## Isolamento

Vendas, usuários vinculados, equipes, cargos personalizados, planos, catálogos, auditoria, configurações, integrações e contexto da IA são filtrados pelo perfil ativo no backend. Esconder menu no navegador não foi aceito como segurança, por motivos que deveriam ser óbvios e ainda assim precisam ser escritos.

## Atualização do banco atual

Ao iniciar a versão 2.0, os dados existentes são associados automaticamente ao perfil **Operação principal**, do tipo Venda de internet. Não apague o Volume do Railway. Crie um backup antes do deploy.

Leia [MULTI_PERFIL_2_0.md](MULTI_PERFIL_2_0.md) para o processo de publicação e uso.

---

# ONE CRM 1.6 Online · Railway

Versão preparada para hospedagem online do ONE CRM, baseada na edição 1.5.

## Recursos desta edição

- Deploy por Dockerfile no Railway.
- Uso automático da variável `PORT` fornecida pela hospedagem.
- Bind em `0.0.0.0` no ambiente online.
- Healthcheck em `/api/health`.
- Banco SQLite persistente quando um Railway Volume é anexado.
- Detecção automática de `RAILWAY_VOLUME_MOUNT_PATH`.
- Cookies `HttpOnly`, `SameSite=Lax` e `Secure` no ambiente online.
- IP real do usuário obtido pelos cabeçalhos do proxy do Railway.
- Token opcional para proteger a criação do primeiro Dono.
- Encerramento limpo ao receber sinal de parada da hospedagem.
- Funcionamento local preservado pelo `INICIAR.bat`.

## Deploy

Leia [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md).

## Arquivos de hospedagem

| Arquivo | Função |
|---|---|
| `Dockerfile` | Cria a imagem do serviço |
| `railway.json` | Define build, start, healthcheck e reinício |
| `.dockerignore` | Evita enviar banco, logs e arquivos desnecessários à imagem |
| `.env.example` | Lista variáveis recomendadas |
| `DEPLOY_RAILWAY.md` | Tutorial de publicação |

## Persistência

Anexe um Volume em:

```text
/app/data
```

Sem Volume, o sistema funciona apenas como teste temporário e pode perder dados em um redeploy.

## Segurança da primeira configuração

Defina no Railway:

```text
ONE_CRM_SETUP_TOKEN=seu-token-secreto
```

A tela de criação do primeiro Dono solicitará esse valor.

## Execução local

O funcionamento local continua disponível:

```text
INICIAR.bat
```

A hospedagem online não usa os arquivos `.bat`.

## Banco

Esta versão usa SQLite e deve permanecer com uma única réplica. Para uso de produção com maior concorrência e escalabilidade horizontal, migre o banco para PostgreSQL.

## ONE Intelligence com OpenAI

A versão 1.8 adiciona um assistente operacional conectado à Responses API da OpenAI.

Configuração online no Railway:

```text
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-5.6-luna
ONE_CRM_AI_ENABLED=1
```

A chave não deve ser adicionada ao GitHub. Consulte `CONFIGURAR_OPENAI_RAILWAY.md` para o procedimento completo.

Principais proteções:

- permissão `ai.use` configurável por cargo;
- escopo de vendas respeitado no backend;
- remoção de CPF, telefone, e-mail e endereço completo do contexto;
- limite de requisições por usuário;
- auditoria e metadados de consumo sem salvar a conversa completa;
- IA somente de leitura, sem alteração automática de vendas ou usuários.


## ONE Intelligence com GroqCloud

A versão 1.9 aceita `GroqCloud`, `OpenAI` e análise local. Para testes sem cartão, configure `GROQ_API_KEY` no Railway e mantenha `ONE_CRM_AI_PROVIDER=auto`. Se a cota externa acabar, o sistema responde com os indicadores locais em vez de interromper o chat. Consulte `CONFIGURAR_GROQ_RAILWAY.md`.
