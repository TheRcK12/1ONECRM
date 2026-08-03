# Configurar OpenAI no ONE CRM (opcional)

A OpenAI deixou de ser obrigatória na versão 1.9. O ONE CRM pode usar GroqCloud ou análise local sem esta integração.

## Variáveis no Railway

```text
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-5.6-luna
ONE_CRM_AI_ENABLED=1
```

Para usar somente OpenAI como provedor principal:

```text
ONE_CRM_AI_PROVIDER=openai
```

Para permitir Groq, OpenAI e fallback local, use:

```text
ONE_CRM_AI_PROVIDER=auto
ONE_CRM_AI_LOCAL_FALLBACK=1
```

A chave não deve ser enviada ao GitHub, ao navegador ou ao SQLite. O card em **Administrativo > Integrações** mostra apenas se ela foi encontrada no ambiente do Railway.
