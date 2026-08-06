# Migração controlada para PostgreSQL

A versão 2.6 mantém SQLite em produção para evitar uma troca destrutiva. Ela inclui a fundação de dados das novas funções e um exportador verificável.

## Processo obrigatório

1. Criar um PostgreSQL separado no ambiente de homologação.
2. Executar `EXPORTAR_SQLITE_PARA_JSON.py` contra uma cópia do banco.
3. Validar contagens por tabela no arquivo `manifest.json`.
4. Importar com um migrador PostgreSQL revisado para o esquema real.
5. Testar permissões, perfis, anexos, tarefas e auditoria.
6. Fazer backup final do SQLite.
7. Trocar produção apenas após homologação e plano de retorno.

A aplicação ainda não deve receber `DATABASE_URL` em produção. O suporte PostgreSQL completo será ativado somente após a conversão de todas as consultas e testes de concorrência.
