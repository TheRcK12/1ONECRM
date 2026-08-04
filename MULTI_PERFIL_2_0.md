# ONE CRM 2.0 - Perfis de negócio

## Hierarquia

### Dono da Plataforma

- vê todos os perfis;
- cria e configura perfis;
- alterna entre ambientes;
- escolhe o Contratante responsável;
- acessa a visão e os dados de qualquer perfil;
- mantém a administração global de Donos.

### Contratante

- entra diretamente no próprio perfil;
- não vê a existência dos demais perfis;
- atua como administrador de visualização do ambiente;
- visualiza vendas, caixa, usuários, equipes, planos, catálogos, cargos, auditoria e integrações liberadas;
- não cria, edita, exclui, trata ou configura registros;
- não altera nome, tipo, módulos ou responsável do perfil;
- não cria Donos nem acessa a administração global;
- não consegue trocar o `profile_id` pela API.

### Demais cargos

Continuam usando as permissões configuradas em **Cargos e permissões**, sempre dentro do perfil atual.

## Migração automática

Na primeira inicialização, a versão cria as tabelas e colunas necessárias e vincula o conteúdo existente ao perfil **Operação principal**. A migração preserva contas, vendas, equipes, planos, catálogos, configurações e histórico.

Antes de publicar:

1. Crie um backup em **Administrativo > Backups**.
2. Confirme que o Railway Volume continua montado em `/app/data`.
3. Substitua os arquivos do pacote na raiz do repositório.
4. Faça `Commit to main` e `Push origin`.
5. Aguarde o deploy mais recente ficar `Success`.
6. Atualize o navegador com `Ctrl + F5`.

## Primeiro uso

1. Entre como Dono.
2. Abra **Perfis** no menu superior.
3. Crie o perfil e escolha o modelo de negócio.
4. Escolha ou crie o usuário que será o Contratante.
5. Defina os módulos ativos.
6. Entre no perfil para criar equipes, cargos e demais usuários.

## Controle de caixa

O perfil Controle de caixa possui um módulo inicial com:

- entradas;
- saídas;
- saldo;
- categorias;
- forma de pagamento;
- histórico de lançamentos;
- contexto financeiro para o ONE Intelligence.

Ainda não estão incluídos nesta versão: contas bancárias, conciliação, contas a pagar/receber recorrentes, centro de custos e fechamento com aprovação.

## Limite de infraestrutura

A versão permanece em SQLite e deve usar uma única réplica no Railway. O isolamento por perfil está implementado na aplicação e no banco, mas para muitos contratantes simultâneos a próxima evolução recomendada é PostgreSQL.
