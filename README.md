# ONE CRM 2.5 · Railway Production

O ONE CRM é uma plataforma multi-perfil para operações comerciais e administrativas. O Dono da Plataforma administra os perfis; Contratantes e demais cargos acessam apenas o escopo autorizado.

## Destaques da versão 2.5

- Deploy por Dockerfile no Railway.
- Banco SQLite persistido obrigatoriamente em Railway Volume.
- Container inicia como root apenas para ajustar o Volume e executa o CRM como UID sem privilégios.
- Primeiro Dono protegido por token forte de configuração.
- Cookies `HttpOnly`, `Secure`, `SameSite=Strict` e prioridade alta.
- Token CSRF e validação adicional da origem das requisições de escrita.
- Content Security Policy e cabeçalhos de segurança.
- Healthcheck em `/api/health`, incluindo banco e armazenamento.
- Encerramento limpo por `SIGTERM`.
- Backups automáticos no Volume.
- GitHub Actions para testes, Docker smoke test e CodeQL.
- Dependabot para manter as Actions atualizadas.

## Arquivos de produção

| Arquivo | Função |
|---|---|
| `Dockerfile` | Cria a imagem do serviço |
| `railway_entrypoint.py` | Ajusta a permissão do Volume e abandona privilégios |
| `railway.json` | Build, healthcheck, reinício e encerramento gradual |
| `.env.example` | Variáveis disponíveis |
| `RAILWAY_VARIAVEIS.env.example` | Modelo para o Raw Editor do Railway |
| `DEPLOY_RAILWAY.md` | Tutorial completo de publicação |
| `.github/workflows/ci.yml` | Testes automáticos |
| `.github/workflows/codeql.yml` | Análise de segurança |

## Persistência

O Volume deve ser montado em:

```text
/app/data
```

O serviço recusa a inicialização em produção quando nenhum Volume é detectado. Isso evita que o sistema aparentemente funcione enquanto grava dados em armazenamento descartável.

## Banco de dados

Esta versão mantém SQLite para preservar compatibilidade com o banco atual. Use apenas uma réplica e uma região. PostgreSQL permanece como evolução futura para maior concorrência e escalabilidade horizontal.

## Publicação

Consulte [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md).

## Testes locais

```bash
python -m compileall -q .
python tests/smoke_test.py
python tests/multi_profile_test.py
python tests/preset_integrity_test.py
python tests/preset_assets_test.py
python tests/platform_access_test.py
python tests/ai_providers_test.py
python tests/online_mode_test.py
python tests/railway_production_test.py
```
