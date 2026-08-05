# Política de segurança

## Relato responsável

Falhas de segurança não devem ser publicadas em issues abertas. Use um GitHub Security Advisory privado no repositório ou encaminhe o relato diretamente ao responsável pela instalação.

Inclua:

- versão afetada;
- perfil e cargo utilizados;
- rota ou tela envolvida;
- passos mínimos para reprodução;
- impacto observado;
- evidências sem dados pessoais reais.

## Segredos

Nunca envie ao GitHub:

- `.env` real;
- `ONE_CRM_SETUP_TOKEN`;
- `GROQ_API_KEY`;
- `OPENAI_API_KEY`;
- banco `.db`;
- backups;
- logs de produção.

## Produção

- Use HTTPS.
- Mantenha cookies seguros e cabeçalhos de proxy habilitados.
- Use um Railway Volume em `/app/data`.
- Use somente uma réplica enquanto o banco for SQLite.
- Revise cargos e permissões após criar ou alterar um preset.
- Faça backups e teste a restauração periodicamente.
