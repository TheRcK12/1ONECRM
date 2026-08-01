# Publicar o ONE CRM no Railway

Esta pasta já está preparada para deploy com Dockerfile, porta dinâmica, healthcheck e armazenamento persistente em Volume.

## 1. Colocar no GitHub

1. Crie um repositório vazio no GitHub, por exemplo `one-crm-online`.
2. Envie **o conteúdo desta pasta** para a raiz do repositório.
3. Confirme que `Dockerfile`, `railway.json` e `one_crm_server.py` aparecem na raiz.

## 2. Criar o projeto no Railway

1. Entre no Railway.
2. Clique em **New Project**.
3. Escolha **Deploy from GitHub repo**.
4. Selecione o repositório do ONE CRM.
5. Aguarde o primeiro build.

O aplicativo detecta automaticamente a variável `PORT` do Railway e escuta em `0.0.0.0`.

## 3. Criar um Volume antes de cadastrar usuários

Sem Volume, o site abre, mas o banco pode desaparecer em um novo deploy.

1. Abra o serviço do ONE CRM no projeto.
2. Adicione um **Volume**.
3. Use o caminho de montagem:

```text
/app/data
```

O ONE CRM detecta automaticamente `RAILWAY_VOLUME_MOUNT_PATH` e grava no Volume:

- `one_crm.db`
- backups
- logs

Depois de anexar o Volume, faça um novo deploy se o Railway não reiniciar o serviço automaticamente.

## 4. Proteger a configuração inicial

Na aba **Variables** do serviço, crie:

```text
ONE_CRM_SETUP_TOKEN=um-token-longo-que-so-voce-conhece
```

Exemplo de token adequado:

```text
onecrm-setup-7f9c4a21-2026-seguro
```

Na primeira abertura, a tela solicitará esse token antes de criar o primeiro Dono. Depois que o Dono existir, o token deixa de ser usado pelo fluxo normal.

Variáveis recomendadas:

```text
ONE_CRM_SECURE_COOKIES=1
ONE_CRM_TRUST_PROXY_HEADERS=1
```

O Railway já define `PORT`; não crie essa variável manualmente.

## 5. Gerar o domínio público

1. Abra **Settings** do serviço.
2. Vá até **Networking** ou **Public Networking**.
3. Clique em **Generate Domain**.
4. Abra o endereço fornecido pelo Railway.

Teste também:

```text
https://SEU-DOMINIO/api/health
```

A resposta esperada contém:

```json
{
  "ok": true,
  "database": "ok",
  "persistent_storage": true
}
```

Se `persistent_storage` vier como `false`, o Volume não foi reconhecido.

## 6. Criar o primeiro Dono

Abra o domínio público, informe:

- Nome completo
- E-mail
- Token de configuração
- Senha

Crie a conta imediatamente após o deploy. Não compartilhe o token.

## Atualizações futuras

Cada `push` no repositório dispara um novo deploy. O código muda, mas o banco continua no Volume.

Não coloque estes arquivos no GitHub:

- bancos `.db`
- backups reais
- logs
- tokens e chaves de API

## Importar um banco local já existente

O arquivo local normalmente está em:

```text
%LOCALAPPDATA%\ONE_CRM\one_crm.db
```

Pare o serviço antes de substituir o banco. Depois, envie o arquivo para o Volume como:

```text
/app/data/one_crm.db
```

Você pode usar a navegação de arquivos do Volume pelo Railway CLI. Mantenha uma cópia do banco local antes de substituir qualquer arquivo.

## Limitação desta versão

Esta edição usa SQLite e deve operar com **uma única réplica** do serviço. Não habilite várias réplicas ou várias regiões usando o mesmo banco. Para produção maior, o próximo passo correto é migrar o banco para PostgreSQL.
