# Deploy do ONE CRM 2.5 no Railway

Este pacote foi preparado para o serviço existente do ONE CRM e preserva o banco SQLite armazenado no Volume.

## 1. Antes do commit

1. Crie um backup pelo ONE CRM.
2. Não remova, recrie nem limpe o Volume atual.
3. Confirme que o Volume está montado em `/app/data`.
4. Copie os arquivos do pacote para a raiz do repositório e faça o commit.

Os arquivos `Dockerfile`, `railway.json`, `one_crm_server.py` e `railway_entrypoint.py` precisam ficar na raiz.

## 2. Volume obrigatório

No serviço do ONE CRM, abra **Settings → Volumes** e use:

```text
/app/data
```

O Railway cria automaticamente `RAILWAY_VOLUME_MOUNT_PATH`. Não cadastre essa variável manualmente.

O ONE CRM grava no Volume:

```text
/app/data/one_crm.db
/app/data/backups/
/app/data/logs/
```

A versão 2.5 recusa a inicialização sem Volume, evitando perda silenciosa dos dados.

## 3. Variáveis obrigatórias

Abra **Variables → Raw Editor** no serviço do ONE CRM e confira:

```env
ONE_CRM_SETUP_TOKEN=COLOQUE_UM_TOKEN_ALEATORIO_COM_PELO_MENOS_32_CARACTERES
ONE_CRM_REQUIRE_SETUP_TOKEN=1
ONE_CRM_REQUIRE_PERSISTENT_STORAGE=1
ONE_CRM_SECURE_COOKIES=1
ONE_CRM_TRUST_PROXY_HEADERS=1
ONE_CRM_SESSION_HOURS=12
ONE_CRM_AUTOMATIC_DAILY_BACKUP=1
ONE_CRM_BACKUP_RETENTION=14
```

Para gerar o token localmente:

```bash
python GERAR_TOKEN_RAILWAY.py
```

Não adicione `PORT`. O Railway fornece essa variável automaticamente.

Não adicione `RAILWAY_VOLUME_MOUNT_PATH`. Ela é fornecida quando o Volume está anexado.

## 4. ONE Intelligence

Para GroqCloud:

```env
ONE_CRM_AI_PROVIDER=groq
ONE_CRM_AI_ENABLED=1
ONE_CRM_AI_LOCAL_FALLBACK=1
GROQ_API_KEY=SUA_CHAVE_REAL
GROQ_MODEL=llama-3.1-8b-instant
ONE_CRM_AI_RATE_LIMIT=10
ONE_CRM_AI_RATE_WINDOW_SECONDS=60
ONE_CRM_AI_TIMEOUT=35
```

Não coloque a chave no GitHub.

## 5. Configurações do serviço

O arquivo `railway.json` já define:

- builder por Dockerfile;
- healthcheck `/api/health`;
- timeout de 180 segundos;
- reinício em falha;
- até 10 tentativas;
- 20 segundos para encerramento gradual;
- nenhuma sobreposição entre deploys, pois o serviço usa Volume.

Em **Settings → Deploy**, remova um Custom Start Command antigo caso esteja preenchido. A imagem deve iniciar pelo `ENTRYPOINT` e `CMD` do Dockerfile.

Se existir uma variável `RAILWAY_RUN_UID`, remova-a ou mantenha `0`. O entrypoint precisa iniciar brevemente como root para ajustar a permissão do Volume e, logo depois, reduz o processo para o UID 10001. Não defina `RAILWAY_RUN_UID=10001`.

Mantenha:

```text
Replicas: 1
Regiões: 1
```

SQLite em Volume não deve ser compartilhado entre réplicas.

## 6. Domínio e healthcheck

Em **Settings → Networking**, mantenha ou gere o domínio público.

Depois do deploy, abra:

```text
https://SEU-DOMINIO/api/health
```

A resposta esperada contém:

```json
{
  "ok": true,
  "database": "ok",
  "persistent_storage": true,
  "storage": {
    "persistent": true,
    "writable": true
  }
}
```

Se retornar `503`, verifique primeiro o Volume e as variáveis obrigatórias.

## 7. Domínio personalizado

O frontend e o backend normalmente usam o mesmo domínio, portanto nenhuma variável adicional é necessária.

Use `ONE_CRM_ALLOWED_ORIGINS` apenas se uma interface separada, hospedada em outro domínio, precisar enviar requisições ao CRM:

```env
ONE_CRM_ALLOWED_ORIGINS=https://painel.exemplo.com.br
```

Separe múltiplos domínios por vírgula.

## 8. Backups do Railway

Além dos backups internos do ONE CRM, habilite backups do Volume no Railway. O banco e os backups internos ficam no mesmo Volume; uma cópia gerenciada pelo Railway protege contra exclusão ou corrupção do próprio Volume.

## 9. GitHub Actions

Após o commit, a aba **Actions** executará:

- compilação Python;
- testes funcionais em Python 3.11, 3.12 e 3.13;
- construção da imagem Docker;
- inicialização com Volume simulado;
- verificação do healthcheck;
- CodeQL.

A publicação em produção deve ocorrer somente depois de os testes ficarem verdes.

## 10. Atualização de um serviço já existente

1. Copie os arquivos para o repositório.
2. Faça `Commit to main` e `Push origin`.
3. Confira as variáveis.
4. Confirme o Volume em `/app/data`.
5. Aguarde o build e o healthcheck.
6. Abra `/api/health`.
7. Atualize o navegador com `Ctrl + F5`.

## Diagnóstico rápido

### Erro: nenhum Volume foi detectado

Anexe o Volume ao serviço em `/app/data`. Não contorne com `ONE_CRM_ALLOW_EPHEMERAL_STORAGE=1` em produção.

### Erro: `ONE_CRM_SETUP_TOKEN`

Defina um token com pelo menos 32 caracteres. Ele protege a criação do primeiro Dono quando o banco estiver vazio.

### Erro de permissão em `/app/data`

A versão 2.5 corrige automaticamente a propriedade do Volume e executa o servidor como UID 10001. Remova qualquer Custom Start Command antigo que esteja ignorando o entrypoint.

### Healthcheck 503

Verifique os logs do deploy. O endpoint testa o banco e a capacidade de escrita no Volume.
