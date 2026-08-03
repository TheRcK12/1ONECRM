# Configurar o GroqCloud no Railway

1. Crie uma conta no GroqCloud.
2. Gere uma chave em `https://console.groq.com/keys`.
3. No serviço do ONE CRM no Railway, abra **Variables** e adicione:

```text
ONE_CRM_AI_PROVIDER=auto
ONE_CRM_AI_ENABLED=1
ONE_CRM_AI_LOCAL_FALLBACK=1
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.1-8b-instant
```

4. Não coloque a chave no GitHub nem nos campos da Evolution API.
5. Aplique as mudanças e aguarde o novo deploy.
6. No ONE CRM, abra **Administrativo > Integrações** e clique em **Testar Groq**.

## Comportamento do modo automático

1. Usa GroqCloud quando `GROQ_API_KEY` estiver disponível.
2. Tenta OpenAI se a Groq falhar e `OPENAI_API_KEY` estiver configurada.
3. Usa a análise local quando nenhum provedor externo responder.

A análise local não consome tokens e permanece disponível mesmo após o limite gratuito da Groq.
