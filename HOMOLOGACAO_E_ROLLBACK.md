# Ambiente de homologação e rollback

## Homologação no Railway

Crie um novo environment chamado `staging` a partir do projeto atual.

- Use outro Volume, montado em `/app/data`.
- Use outro `ONE_CRM_SETUP_TOKEN`.
- Use chaves SMTP/Groq separadas ou de teste.
- Defina `ONE_CRM_ENVIRONMENT=staging`.
- Não reutilize o banco ou o Volume da produção.

## Fluxo de publicação

1. Commit na branch `develop`.
2. Deploy automático em `staging`.
3. Executar testes funcionais e de migração.
4. Criar backup da produção.
5. Mesclar para `main`.
6. Verificar `/api/health` e logs.

## Rollback

- Para erro de código: use `Redeploy` no último deployment saudável.
- Para erro de banco: restaure o backup criado antes da publicação.
- Nunca restaure banco antigo sobre uma versão que já gravou estrutura incompatível sem conferir a versão da migração.
