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
