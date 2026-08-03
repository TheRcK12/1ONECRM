# Configurar OpenAI no ONE CRM

## 1. Criar a chave

Crie uma chave de API específica para o projeto ONE CRM. Não coloque a chave em arquivos do GitHub, JavaScript, banco SQLite ou capturas de tela.

## 2. Adicionar no Railway

No serviço do ONE CRM, abra **Variables** e crie:

```text
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-5.6-luna
ONE_CRM_AI_ENABLED=1
```

Variáveis opcionais:

```text
ONE_CRM_AI_RATE_LIMIT=10
ONE_CRM_AI_RATE_WINDOW_SECONDS=60
ONE_CRM_AI_TIMEOUT=35
```

O Railway iniciará um novo deploy depois de aplicar as variáveis.

## 3. Liberar permissões

Entre como Dono e abra:

```text
Administrativo → Cargos e permissões
```

Marque a permissão:

```text
Inteligência → Utilizar o assistente ONE Intelligence com OpenAI
```

O cargo Gerente recebe essa permissão por padrão. O Dono sempre possui acesso total.

## 4. Testar

Abra:

```text
Administrativo → Integrações
```

O card OpenAI deve mostrar **Configurada**. Clique em **Testar OpenAI**.

Depois abra:

```text
Inteligência
```

Faça uma pergunta ou use uma sugestão rápida.

## Segurança e privacidade

- A chave é lida somente da variável `OPENAI_API_KEY` no backend.
- A chave não é enviada ao navegador e não é gravada no SQLite.
- CPF, telefone, e-mail e endereço completo não são incluídos no contexto enviado.
- O histórico completo das perguntas não é salvo. Apenas metadados técnicos de uso são registrados.
- A IA somente analisa e sugere. Ela não altera vendas, usuários ou configurações.
