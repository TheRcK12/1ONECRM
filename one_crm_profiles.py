from __future__ import annotations

"""Camada multi-perfil do ONE CRM.

Esta extensão mantém a aplicação monolítica atual compatível, mas adiciona:
- perfis de negócio isolados;
- Dono da plataforma com visão global;
- Contratante limitado ao próprio perfil;
- módulos por perfil;
- separação de vendas, equipes, planos, catálogos, cargos e integrações;
- módulo inicial de controle de caixa.

O arquivo é instalado em tempo de importação por ``install_profiles(globals())``.
"""

import json
import re
import secrets
import sqlite3
import threading
from datetime import date
from typing import Any, Callable


PLATFORM_PERMISSIONS: list[tuple[str, str, str]] = [
    ("platform.profile.read", "Perfis atribuídos", "Visualizar os dados e indicadores dos perfis atribuídos"),
    ("platform.profile.manage", "Operação", "Criar e alterar registros operacionais nos perfis atribuídos"),
    ("platform.people.manage", "Pessoas", "Administrar funcionários e equipes dos perfis atribuídos"),
    ("platform.security.manage", "Segurança", "Administrar cargos e permissões dos perfis atribuídos"),
    ("platform.integrations.manage", "Integrações", "Administrar integrações dos perfis atribuídos"),
    ("platform.audit.view", "Auditoria", "Visualizar a auditoria dos perfis atribuídos"),
    ("platform.backups.manage", "Backups", "Criar e consultar backups da aplicação"),
]

PLATFORM_ROLE_DEFAULTS: dict[str, set[str]] = {
    "platform_admin": {code for code, _, _ in PLATFORM_PERMISSIONS},
}


PROFILE_TEMPLATES: dict[str, dict[str, Any]] = {'internet_sales': {'name': 'Venda de internet',
                    'category': 'Telecom',
                    'description': 'Operação comercial de internet com planos, BKO, biometria e instalação.',
                    'recommended_for': 'Provedores, representantes de fibra, telecom e equipes de vendas externas.',
                    'operation_group_label': 'Vendas',
                    'modules': ['dashboard',
                                'sales',
                                'bko',
                                'daily',
                                'ranking',
                                'intelligence',
                                'powerbi',
                                'users',
                                'teams',
                                'plans',
                                'catalogs',
                                'roles',
                                'audit',
                                'integrations'],
                    'navigation_labels': {'sales-group': 'Vendas',
                                          'sales': 'Todas as vendas',
                                          'new-sale': 'Nova venda',
                                          'bko': 'Gestão BKO',
                                          'plans': 'Planos'},
                    'admin_labels': {'plans_title': 'Planos e serviços',
                                     'plans_singular': 'plano',
                                     'provider': 'Operadora',
                                     'service': 'Serviço',
                                     'attribute': 'Velocidade',
                                     'coverage': 'UFs disponíveis'},
                    'roles': [{'code': 'supervisor_comercial',
                               'name': 'Supervisor comercial',
                               'base_role': 'manager',
                               'description': 'Acompanha equipes, vendas e indicadores.',
                               'permissions': ['dashboard.view',
                                               'sales.all',
                                               'sales.create',
                                               'sales.edit_all',
                                               'workflow.assign',
                                               'ranking.all',
                                               'daily.view',
                                               'users.view',
                                               'teams.view',
                                               'intelligence.view',
                                               'ai.use',
                                               'plans.view',
                                               'catalogs.view']},
                              {'code': 'consultor_vendas',
                               'name': 'Consultor de vendas',
                               'base_role': 'seller',
                               'description': 'Cadastra e acompanha as próprias vendas.',
                               'permissions': ['dashboard.view',
                                               'sales.own',
                                               'sales.create',
                                               'sales.edit_own',
                                               'ranking.own']},
                              {'code': 'analista_bko',
                               'name': 'Analista BKO',
                               'base_role': 'bko',
                               'description': 'Trata ativação, biometria e instalação.',
                               'permissions': ['dashboard.view', 'sales.all', 'workflow.bko', 'teams.view']}],
                    'catalog_labels': {'provider': 'Operadoras',
                                       'service': 'Serviços',
                                       'sale_status': 'Status da venda',
                                       'activation_status': 'Ativação',
                                       'biometric_status': 'Biometria',
                                       'installation_status': 'Instalação',
                                       'appointment_status': 'Agendamento',
                                       'payment_method': 'Formas de pagamento',
                                       'due_day': 'Vencimentos',
                                       'sales_channel': 'Canais de venda',
                                       'period': 'Períodos',
                                       'property_type': 'Tipos de imóvel',
                                       'cancellation_reason': 'Motivos de cancelamento'},
                    'catalogs': {},
                    'offerings': [],
                    'records': {}},
 'cash_control': {'name': 'Controle de caixa',
                  'category': 'Financeiro',
                  'description': 'Entradas, saídas, contas a pagar, contas a receber e acompanhamento financeiro.',
                  'recommended_for': 'Pequenos negócios, departamentos financeiros, condomínios e operações internas.',
                  'operation_group_label': 'Financeiro',
                  'modules': ['dashboard',
                              'cash',
                              'accounts_payable',
                              'accounts_receivable',
                              'intelligence',
                              'users',
                              'roles',
                              'audit',
                              'integrations'],
                  'navigation_labels': {'cash': 'Caixa',
                                        'accounts_payable': 'Contas a pagar',
                                        'accounts_receivable': 'Contas a receber'},
                  'admin_labels': {'plans_title': 'Serviços financeiros',
                                   'plans_singular': 'serviço',
                                   'provider': 'Responsável',
                                   'service': 'Categoria',
                                   'attribute': 'Referência',
                                   'coverage': 'Abrangência'},
                  'roles': [{'code': 'gestor_financeiro',
                             'name': 'Gestor financeiro',
                             'base_role': 'manager',
                             'description': 'Visualiza e administra a operação financeira.',
                             'permissions': ['dashboard.view',
                                             'cash.view',
                                             'cash.manage',
                                             'accounts_payable.view',
                                             'accounts_payable.manage',
                                             'accounts_receivable.view',
                                             'accounts_receivable.manage',
                                             'intelligence.view',
                                             'ai.use',
                                             'users.view',
                                             'audit.view']},
                            {'code': 'operador_caixa',
                             'name': 'Operador de caixa',
                             'base_role': 'seller',
                             'description': 'Registra entradas e saídas do caixa.',
                             'permissions': ['dashboard.view', 'cash.view', 'cash.manage']},
                            {'code': 'auditor_financeiro',
                             'name': 'Auditor financeiro',
                             'base_role': 'bko',
                             'description': 'Consulta movimentações e documentos sem alterar.',
                             'permissions': ['dashboard.view',
                                             'cash.view',
                                             'accounts_payable.view',
                                             'accounts_receivable.view',
                                             'audit.view']}],
                  'catalog_labels': {'financial_category': 'Categorias financeiras',
                                     'payment_method': 'Formas de pagamento',
                                     'account_status': 'Status financeiro'},
                  'catalogs': {'financial_category': [('vendas', 'Vendas'),
                                                      ('fornecedores', 'Fornecedores'),
                                                      ('folha', 'Folha de pagamento'),
                                                      ('impostos', 'Impostos'),
                                                      ('operacional', 'Despesas operacionais')],
                               'payment_method': [('pix', 'PIX'),
                                                  ('dinheiro', 'Dinheiro'),
                                                  ('boleto', 'Boleto'),
                                                  ('transferencia', 'Transferência'),
                                                  ('cartao', 'Cartão')],
                               'account_status': [('pendente', 'Pendente'),
                                                  ('agendado', 'Agendado'),
                                                  ('pago', 'Pago'),
                                                  ('vencido', 'Vencido'),
                                                  ('cancelado', 'Cancelado')]},
                  'offerings': [],
                  'records': {'accounts_payable': {'label': 'Contas a pagar',
                                                   'singular': 'Conta a pagar',
                                                   'description': 'Obrigações financeiras e vencimentos.',
                                                   'status_category': 'account_status',
                                                   'amount_label': 'Valor',
                                                   'due_label': 'Vencimento',
                                                   'fields': [{'key': 'category',
                                                               'label': 'Categoria',
                                                               'type': 'catalog',
                                                               'category': 'financial_category',
                                                               'required': True},
                                                              {'key': 'payment_method',
                                                               'label': 'Forma de pagamento',
                                                               'type': 'catalog',
                                                               'category': 'payment_method'},
                                                              {'key': 'document',
                                                               'label': 'Documento / referência',
                                                               'type': 'text'},
                                                              {'key': 'beneficiary',
                                                               'label': 'Beneficiário',
                                                               'type': 'text',
                                                               'required': True}],
                                                   'amount_format': 'currency',
                                                   'assigned_label': 'Responsável financeiro',
                                                   'subtitle_label': 'Fornecedor ou referência',
                                                   'notes_label': 'Observações financeiras',
                                                   'title_label': 'Descrição da conta'},
                              'accounts_receivable': {'label': 'Contas a receber',
                                                      'singular': 'Conta a receber',
                                                      'description': 'Recebimentos previstos e situação de cobrança.',
                                                      'status_category': 'account_status',
                                                      'amount_label': 'Valor',
                                                      'due_label': 'Vencimento',
                                                      'fields': [{'key': 'category',
                                                                  'label': 'Categoria',
                                                                  'type': 'catalog',
                                                                  'category': 'financial_category',
                                                                  'required': True},
                                                                 {'key': 'payment_method',
                                                                  'label': 'Forma de recebimento',
                                                                  'type': 'catalog',
                                                                  'category': 'payment_method'},
                                                                 {'key': 'document',
                                                                  'label': 'Documento / referência',
                                                                  'type': 'text'},
                                                                 {'key': 'payer',
                                                                  'label': 'Pagador',
                                                                  'type': 'text',
                                                                  'required': True}],
                                                      'amount_format': 'currency',
                                                      'assigned_label': 'Responsável financeiro',
                                                      'subtitle_label': 'Pagador ou referência',
                                                      'notes_label': 'Observações financeiras',
                                                      'title_label': 'Descrição do recebimento'}}},
 'services': {'name': 'Prestação de serviços',
              'category': 'Operacional',
              'description': 'Clientes, ordens de serviço, agenda e execução de serviços.',
              'recommended_for': 'Assistência técnica, manutenção, instalação, limpeza e prestadores em geral.',
              'operation_group_label': 'Serviços',
              'modules': ['dashboard',
                          'clients',
                          'service_orders',
                          'schedule',
                          'daily',
                          'intelligence',
                          'users',
                          'teams',
                          'services_catalog',
                          'catalogs',
                          'roles',
                          'audit',
                          'integrations'],
              'navigation_labels': {'clients': 'Clientes',
                                    'service_orders': 'Ordens de serviço',
                                    'schedule': 'Agenda',
                                    'plans': 'Serviços'},
              'admin_labels': {'plans_title': 'Serviços oferecidos',
                               'plans_singular': 'serviço',
                               'provider': 'Área responsável',
                               'service': 'Categoria',
                               'attribute': 'Duração/Referência',
                               'coverage': 'Regiões atendidas'},
              'roles': [{'code': 'coordenador_servicos',
                         'name': 'Coordenador de serviços',
                         'base_role': 'manager',
                         'description': 'Distribui ordens e acompanha a execução.',
                         'permissions': ['dashboard.view',
                                         'clients.view',
                                         'clients.manage',
                                         'service_orders.view',
                                         'service_orders.manage',
                                         'schedule.view',
                                         'schedule.manage',
                                         'daily.view',
                                         'users.view',
                                         'teams.view',
                                         'plans.view',
                                         'catalogs.view',
                                         'intelligence.view',
                                         'ai.use']},
                        {'code': 'tecnico',
                         'name': 'Técnico',
                         'base_role': 'seller',
                         'description': 'Visualiza clientes e atualiza suas ordens de serviço.',
                         'permissions': ['dashboard.view',
                                         'clients.view',
                                         'service_orders.view',
                                         'service_orders.manage',
                                         'schedule.view',
                                         'plans.view']},
                        {'code': 'atendente_servicos',
                         'name': 'Atendente',
                         'base_role': 'bko',
                         'description': 'Cadastra clientes e agenda atendimentos.',
                         'permissions': ['dashboard.view',
                                         'clients.view',
                                         'clients.manage',
                                         'service_orders.view',
                                         'service_orders.manage',
                                         'schedule.view',
                                         'schedule.manage']}],
              'catalog_labels': {'client_type': 'Tipos de cliente',
                                 'service_order_status': 'Status da ordem',
                                 'service_priority': 'Prioridades',
                                 'schedule_status': 'Status da agenda',
                                 'service_period': 'Períodos de atendimento'},
              'catalogs': {'client_type': [('residencial', 'Residencial'),
                                           ('comercial', 'Comercial'),
                                           ('condominio', 'Condomínio')],
                           'service_order_status': [('aberta', 'Aberta'),
                                                    ('agendada', 'Agendada'),
                                                    ('em_execucao', 'Em execução'),
                                                    ('aguardando_cliente', 'Aguardando cliente'),
                                                    ('concluida', 'Concluída'),
                                                    ('cancelada', 'Cancelada')],
                           'service_priority': [('baixa', 'Baixa'),
                                                ('normal', 'Normal'),
                                                ('alta', 'Alta'),
                                                ('urgente', 'Urgente')],
                           'schedule_status': [('agendado', 'Agendado'),
                                               ('confirmado', 'Confirmado'),
                                               ('realizado', 'Realizado'),
                                               ('reagendado', 'Reagendado'),
                                               ('cancelado', 'Cancelado')],
                           'service_period': [('manha', 'Manhã'),
                                              ('tarde', 'Tarde'),
                                              ('noite', 'Noite'),
                                              ('integral', 'Dia inteiro')]},
              'offerings': [{'provider': 'Operação',
                             'service': 'Manutenção',
                             'name': 'Visita técnica',
                             'speed': 'Até 2 horas',
                             'price': 0,
                             'benefits': 'Diagnóstico e atendimento técnico'},
                            {'provider': 'Operação',
                             'service': 'Instalação',
                             'name': 'Instalação padrão',
                             'speed': 'Sob agendamento',
                             'price': 0,
                             'benefits': 'Execução conforme escopo'}],
              'records': {'clients': {'label': 'Clientes',
                                      'singular': 'Cliente',
                                      'description': 'Cadastro dos clientes atendidos.',
                                      'status_options': [('ativo', 'Ativo'),
                                                         ('inativo', 'Inativo'),
                                                         ('prospect', 'Prospect')],
                                      'amount_label': False,
                                      'fields': [{'key': 'client_type',
                                                  'label': 'Tipo de cliente',
                                                  'type': 'catalog',
                                                  'category': 'client_type',
                                                  'required': True},
                                                 {'key': 'document', 'label': 'CPF / CNPJ', 'type': 'text'},
                                                 {'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                 {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                 {'key': 'city', 'label': 'Cidade', 'type': 'text'}],
                                      'due_label': False,
                                      'amount_format': 'currency',
                                      'assigned_label': 'Responsável pelo cliente',
                                      'subtitle_label': 'Empresa ou identificação complementar',
                                      'notes_label': 'Observações',
                                      'title_label': 'Nome do cliente'},
                          'service_orders': {'label': 'Ordens de serviço',
                                             'singular': 'Ordem de serviço',
                                             'description': 'Solicitações e execução dos serviços.',
                                             'status_category': 'service_order_status',
                                             'amount_label': 'Valor do serviço',
                                             'due_label': 'Data prevista',
                                             'fields': [{'key': 'client',
                                                         'label': 'Cliente',
                                                         'type': 'record',
                                                         'module': 'clients',
                                                         'required': True},
                                                        {'key': 'service',
                                                         'label': 'Serviço contratado',
                                                         'type': 'plan',
                                                         'required': True},
                                                        {'key': 'priority',
                                                         'label': 'Prioridade',
                                                         'type': 'catalog',
                                                         'category': 'service_priority',
                                                         'required': True},
                                                        {'key': 'address',
                                                         'label': 'Endereço / local do serviço',
                                                         'type': 'textarea'}],
                                             'amount_format': 'currency',
                                             'assigned_label': 'Técnico responsável',
                                             'subtitle_label': 'Resumo do serviço',
                                             'notes_label': 'Observações',
                                             'title_label': 'Título da ordem de serviço'},
                          'schedule': {'label': 'Agenda',
                                       'singular': 'Agendamento',
                                       'description': 'Agenda de visitas e serviços.',
                                       'status_category': 'schedule_status',
                                       'due_label': 'Data do atendimento',
                                       'fields': [{'key': 'client',
                                                   'label': 'Cliente',
                                                   'type': 'record',
                                                   'module': 'clients',
                                                   'required': True},
                                                  {'key': 'service',
                                                   'label': 'Serviço',
                                                   'type': 'plan',
                                                   'required': True},
                                                  {'key': 'period',
                                                   'label': 'Período',
                                                   'type': 'catalog',
                                                   'category': 'service_period',
                                                   'required': True},
                                                  {'key': 'location', 'label': 'Local do atendimento', 'type': 'text'}],
                                       'amount_label': False,
                                       'amount_format': 'currency',
                                       'assigned_label': 'Profissional responsável',
                                       'subtitle_label': 'Orientação do atendimento',
                                       'notes_label': 'Observações',
                                       'title_label': 'Identificação do agendamento'}}},
 'general_crm': {'name': 'CRM comercial geral',
                 'category': 'Comercial',
                 'description': 'Leads, oportunidades, tarefas e gestão comercial flexível.',
                 'recommended_for': 'Empresas que precisam de um CRM comercial sem fluxo específico de telecom.',
                 'operation_group_label': 'Comercial',
                 'modules': ['dashboard',
                             'leads',
                             'opportunities',
                             'tasks',
                             'daily',
                             'ranking',
                             'intelligence',
                             'users',
                             'teams',
                             'services_catalog',
                             'catalogs',
                             'roles',
                             'audit',
                             'integrations'],
                 'navigation_labels': {'leads': 'Leads',
                                       'opportunities': 'Oportunidades',
                                       'tasks': 'Tarefas',
                                       'plans': 'Produtos e serviços'},
                 'admin_labels': {'plans_title': 'Produtos e serviços',
                                  'plans_singular': 'item',
                                  'provider': 'Marca/Unidade',
                                  'service': 'Categoria',
                                  'attribute': 'Referência',
                                  'coverage': 'Regiões'},
                 'roles': [{'code': 'gerente_comercial',
                            'name': 'Gerente comercial',
                            'base_role': 'manager',
                            'description': 'Gerencia funil, equipes e indicadores.',
                            'permissions': ['dashboard.view',
                                            'leads.view',
                                            'leads.manage',
                                            'opportunities.view',
                                            'opportunities.manage',
                                            'tasks.view',
                                            'tasks.manage',
                                            'daily.view',
                                            'ranking.all',
                                            'users.view',
                                            'teams.view',
                                            'plans.view',
                                            'catalogs.view',
                                            'intelligence.view',
                                            'ai.use']},
                           {'code': 'executivo_comercial',
                            'name': 'Executivo comercial',
                            'base_role': 'seller',
                            'description': 'Trabalha leads e oportunidades.',
                            'permissions': ['dashboard.view',
                                            'leads.view',
                                            'leads.manage',
                                            'opportunities.view',
                                            'opportunities.manage',
                                            'tasks.view',
                                            'tasks.manage',
                                            'ranking.own',
                                            'plans.view']},
                           {'code': 'pre_vendas',
                            'name': 'Pré-vendas',
                            'base_role': 'bko',
                            'description': 'Qualifica leads e agenda oportunidades.',
                            'permissions': ['dashboard.view',
                                            'leads.view',
                                            'leads.manage',
                                            'tasks.view',
                                            'tasks.manage']}],
                 'catalog_labels': {'lead_status': 'Status do lead',
                                    'lead_source': 'Origem do lead',
                                    'opportunity_stage': 'Etapas da oportunidade',
                                    'task_status': 'Status da tarefa',
                                    'task_priority': 'Prioridades de tarefa'},
                 'catalogs': {'lead_status': [('novo', 'Novo'),
                                              ('contato', 'Em contato'),
                                              ('qualificado', 'Qualificado'),
                                              ('descartado', 'Descartado')],
                              'lead_source': [('indicacao', 'Indicação'),
                                              ('site', 'Site'),
                                              ('whatsapp', 'WhatsApp'),
                                              ('trafego_pago', 'Tráfego pago'),
                                              ('prospeccao', 'Prospecção')],
                              'opportunity_stage': [('diagnostico', 'Diagnóstico'),
                                                    ('proposta', 'Proposta'),
                                                    ('negociacao', 'Negociação'),
                                                    ('ganha', 'Ganha'),
                                                    ('perdida', 'Perdida')],
                              'task_status': [('pendente', 'Pendente'),
                                              ('em_andamento', 'Em andamento'),
                                              ('concluida', 'Concluída'),
                                              ('cancelada', 'Cancelada')],
                              'task_priority': [('baixa', 'Baixa'),
                                                ('normal', 'Normal'),
                                                ('alta', 'Alta'),
                                                ('urgente', 'Urgente')]},
                 'offerings': [{'provider': 'Comercial',
                                'service': 'Venda avulsa',
                                'name': 'Produto ou serviço avulso',
                                'speed': 'Sob proposta',
                                'price': 0,
                                'benefits': 'Oferta comercial configurável'},
                               {'provider': 'Comercial',
                                'service': 'Contrato recorrente',
                                'name': 'Contrato recorrente',
                                'speed': 'Mensal',
                                'price': 0,
                                'benefits': 'Serviço ou assinatura recorrente'}],
                 'records': {'leads': {'label': 'Leads',
                                       'singular': 'Lead',
                                       'description': 'Contatos em prospecção e qualificação.',
                                       'status_category': 'lead_status',
                                       'fields': [{'key': 'source',
                                                   'label': 'Origem do lead',
                                                   'type': 'catalog',
                                                   'category': 'lead_source',
                                                   'required': True},
                                                  {'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                  {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                  {'key': 'company', 'label': 'Empresa', 'type': 'text'}],
                                       'due_label': False,
                                       'amount_label': False,
                                       'amount_format': 'currency',
                                       'assigned_label': 'Responsável comercial',
                                       'subtitle_label': 'Empresa ou contexto',
                                       'notes_label': 'Observações',
                                       'title_label': 'Nome do lead'},
                             'opportunities': {'label': 'Oportunidades',
                                               'singular': 'Oportunidade',
                                               'description': 'Negócios em andamento no funil comercial.',
                                               'status_category': 'opportunity_stage',
                                               'amount_label': 'Valor estimado',
                                               'due_label': 'Previsão de fechamento',
                                               'fields': [{'key': 'client',
                                                           'label': 'Lead relacionado',
                                                           'type': 'record',
                                                           'module': 'leads',
                                                           'required': True},
                                                          {'key': 'product',
                                                           'label': 'Produto ou serviço',
                                                           'type': 'plan'},
                                                          {'key': 'probability',
                                                           'label': 'Probabilidade de fechamento (%)',
                                                           'type': 'number',
                                                           'min': 0,
                                                           'max': 100,
                                                           'step': 1}],
                                               'amount_format': 'currency',
                                               'assigned_label': 'Executivo responsável',
                                               'subtitle_label': 'Resumo da oportunidade',
                                               'notes_label': 'Observações',
                                               'title_label': 'Nome da oportunidade'},
                             'tasks': {'label': 'Tarefas',
                                       'singular': 'Tarefa',
                                       'description': 'Atividades e próximos passos da equipe.',
                                       'status_category': 'task_status',
                                       'due_label': 'Prazo',
                                       'fields': [{'key': 'related_to',
                                                   'label': 'Oportunidade relacionada',
                                                   'type': 'record',
                                                   'module': 'opportunities'},
                                                  {'key': 'priority',
                                                   'label': 'Prioridade',
                                                   'type': 'catalog',
                                                   'category': 'task_priority',
                                                   'required': True}],
                                       'amount_label': False,
                                       'amount_format': 'currency',
                                       'assigned_label': 'Responsável pela tarefa',
                                       'subtitle_label': 'Descrição curta',
                                       'notes_label': 'Observações',
                                       'title_label': 'Título da tarefa'}}},
 'collections': {'name': 'Cobrança e recuperação',
                 'category': 'Financeiro',
                 'description': 'Carteiras, negociações, acordos e resultados de recuperação.',
                 'recommended_for': 'Cobrança interna, recuperação de crédito e equipes de negociação.',
                 'operation_group_label': 'Cobrança',
                 'modules': ['dashboard',
                             'debtors',
                             'negotiations',
                             'agreements',
                             'daily',
                             'ranking',
                             'intelligence',
                             'users',
                             'teams',
                             'catalogs',
                             'roles',
                             'audit',
                             'integrations'],
                 'navigation_labels': {'debtors': 'Devedores', 'negotiations': 'Negociações', 'agreements': 'Acordos'},
                 'roles': [{'code': 'supervisor_cobranca',
                            'name': 'Supervisor de cobrança',
                            'base_role': 'manager',
                            'description': 'Gerencia carteira, equipe e acordos.',
                            'permissions': ['dashboard.view',
                                            'debtors.view',
                                            'debtors.manage',
                                            'negotiations.view',
                                            'negotiations.manage',
                                            'agreements.view',
                                            'agreements.manage',
                                            'daily.view',
                                            'ranking.all',
                                            'users.view',
                                            'teams.view',
                                            'intelligence.view',
                                            'ai.use']},
                           {'code': 'negociador',
                            'name': 'Negociador',
                            'base_role': 'seller',
                            'description': 'Realiza contatos e negociações.',
                            'permissions': ['dashboard.view',
                                            'debtors.view',
                                            'negotiations.view',
                                            'negotiations.manage',
                                            'agreements.view',
                                            'ranking.own']},
                           {'code': 'analista_acordos',
                            'name': 'Analista de acordos',
                            'base_role': 'bko',
                            'description': 'Confere e acompanha acordos firmados.',
                            'permissions': ['dashboard.view',
                                            'debtors.view',
                                            'negotiations.view',
                                            'agreements.view',
                                            'agreements.manage']}],
                 'catalog_labels': {'debtor_status': 'Status da carteira',
                                    'negotiation_status': 'Status da negociação',
                                    'agreement_status': 'Status do acordo',
                                    'contact_result': 'Resultado do contato',
                                    'collection_payment_method': 'Formas de pagamento do acordo'},
                 'catalogs': {'debtor_status': [('novo', 'Novo'),
                                                ('em_cobranca', 'Em cobrança'),
                                                ('negociando', 'Negociando'),
                                                ('regularizado', 'Regularizado'),
                                                ('incobravel', 'Incobrável')],
                              'negotiation_status': [('pendente', 'Pendente'),
                                                     ('promessa', 'Promessa de pagamento'),
                                                     ('proposta', 'Proposta enviada'),
                                                     ('sem_acordo', 'Sem acordo'),
                                                     ('concluida', 'Concluída')],
                              'agreement_status': [('aguardando', 'Aguardando pagamento'),
                                                   ('parcial', 'Pagamento parcial'),
                                                   ('quitado', 'Quitado'),
                                                   ('quebrado', 'Acordo quebrado')],
                              'contact_result': [('atendeu', 'Atendeu'),
                                                 ('nao_atendeu', 'Não atendeu'),
                                                 ('recado', 'Recado'),
                                                 ('numero_invalido', 'Número inválido')],
                              'collection_payment_method': [('pix', 'PIX'),
                                                            ('boleto', 'Boleto'),
                                                            ('cartao', 'Cartão'),
                                                            ('debito', 'Débito em conta'),
                                                            ('transferencia', 'Transferência')]},
                 'offerings': [],
                 'records': {'debtors': {'label': 'Devedores',
                                         'singular': 'Devedor',
                                         'description': 'Pessoas ou empresas da carteira de cobrança.',
                                         'status_category': 'debtor_status',
                                         'amount_label': 'Saldo em aberto',
                                         'fields': [{'key': 'document', 'label': 'CPF / CNPJ', 'type': 'text'},
                                                    {'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                    {'key': 'portfolio',
                                                     'label': 'Carteira / contrato',
                                                     'type': 'text'}],
                                         'due_label': False,
                                         'amount_format': 'currency',
                                         'assigned_label': 'Responsável pela carteira',
                                         'subtitle_label': 'Carteira ou contrato',
                                         'notes_label': 'Observações',
                                         'title_label': 'Nome do devedor'},
                             'negotiations': {'label': 'Negociações',
                                              'singular': 'Negociação',
                                              'description': 'Histórico de contato e propostas.',
                                              'status_category': 'negotiation_status',
                                              'amount_label': 'Valor negociado',
                                              'due_label': 'Próximo contato',
                                              'fields': [{'key': 'debtor',
                                                          'label': 'Devedor',
                                                          'type': 'record',
                                                          'module': 'debtors',
                                                          'required': True},
                                                         {'key': 'contact_result',
                                                          'label': 'Resultado do contato',
                                                          'type': 'catalog',
                                                          'category': 'contact_result',
                                                          'required': True},
                                                         {'key': 'proposal',
                                                          'label': 'Proposta apresentada',
                                                          'type': 'textarea'}],
                                              'amount_format': 'currency',
                                              'assigned_label': 'Negociador responsável',
                                              'subtitle_label': 'Resumo da conversa',
                                              'notes_label': 'Observações',
                                              'title_label': 'Identificação da negociação'},
                             'agreements': {'label': 'Acordos',
                                            'singular': 'Acordo',
                                            'description': 'Acordos fechados e acompanhamento de pagamentos.',
                                            'status_category': 'agreement_status',
                                            'amount_label': 'Valor do acordo',
                                            'due_label': 'Vencimento',
                                            'fields': [{'key': 'debtor',
                                                        'label': 'Devedor',
                                                        'type': 'record',
                                                        'module': 'debtors',
                                                        'required': True},
                                                       {'key': 'installments',
                                                        'label': 'Quantidade de parcelas',
                                                        'type': 'number',
                                                        'min': 1,
                                                        'step': 1},
                                                       {'key': 'payment_method',
                                                        'label': 'Forma de pagamento',
                                                        'type': 'catalog',
                                                        'category': 'collection_payment_method',
                                                        'required': True}],
                                            'amount_format': 'currency',
                                            'assigned_label': 'Analista responsável',
                                            'subtitle_label': 'Condição resumida',
                                            'notes_label': 'Observações',
                                            'title_label': 'Identificação do acordo'}}},
 'after_sales': {'name': 'Atendimento e pós-venda',
                 'category': 'Relacionamento',
                 'description': 'Clientes, chamados, acompanhamentos e indicadores de atendimento.',
                 'recommended_for': 'Suporte, retenção, sucesso do cliente e acompanhamento pós-venda.',
                 'operation_group_label': 'Atendimento',
                 'modules': ['dashboard',
                             'customers',
                             'tickets',
                             'followups',
                             'daily',
                             'intelligence',
                             'users',
                             'teams',
                             'catalogs',
                             'roles',
                             'audit',
                             'integrations'],
                 'navigation_labels': {'customers': 'Clientes', 'tickets': 'Chamados', 'followups': 'Acompanhamentos'},
                 'roles': [{'code': 'coordenador_atendimento',
                            'name': 'Coordenador de atendimento',
                            'base_role': 'manager',
                            'description': 'Gerencia filas, equipe e indicadores de atendimento.',
                            'permissions': ['dashboard.view',
                                            'customers.view',
                                            'customers.manage',
                                            'tickets.view',
                                            'tickets.manage',
                                            'followups.view',
                                            'followups.manage',
                                            'daily.view',
                                            'users.view',
                                            'teams.view',
                                            'intelligence.view',
                                            'ai.use',
                                            'plans.view']},
                           {'code': 'analista_suporte',
                            'name': 'Analista de suporte',
                            'base_role': 'seller',
                            'description': 'Atende clientes e atualiza chamados.',
                            'permissions': ['dashboard.view',
                                            'customers.view',
                                            'tickets.view',
                                            'tickets.manage',
                                            'followups.view',
                                            'followups.manage',
                                            'plans.view']},
                           {'code': 'qualidade_atendimento',
                            'name': 'Qualidade',
                            'base_role': 'bko',
                            'description': 'Audita atendimentos e acompanha retorno ao cliente.',
                            'permissions': ['dashboard.view',
                                            'customers.view',
                                            'tickets.view',
                                            'followups.view',
                                            'daily.view',
                                            'audit.view']}],
                 'catalog_labels': {'customer_status': 'Status do cliente',
                                    'ticket_status': 'Status do chamado',
                                    'ticket_priority': 'Prioridade',
                                    'followup_status': 'Status do acompanhamento',
                                    'support_channel': 'Canais de atendimento'},
                 'catalogs': {'customer_status': [('ativo', 'Ativo'), ('risco', 'Em risco'), ('inativo', 'Inativo')],
                              'ticket_status': [('aberto', 'Aberto'),
                                                ('em_atendimento', 'Em atendimento'),
                                                ('aguardando_cliente', 'Aguardando cliente'),
                                                ('resolvido', 'Resolvido'),
                                                ('cancelado', 'Cancelado')],
                              'ticket_priority': [('baixa', 'Baixa'),
                                                  ('normal', 'Normal'),
                                                  ('alta', 'Alta'),
                                                  ('critica', 'Crítica')],
                              'followup_status': [('pendente', 'Pendente'),
                                                  ('agendado', 'Agendado'),
                                                  ('realizado', 'Realizado'),
                                                  ('sem_retorno', 'Sem retorno')],
                              'support_channel': [('telefone', 'Telefone'),
                                                  ('whatsapp', 'WhatsApp'),
                                                  ('email', 'E-mail'),
                                                  ('chat', 'Chat'),
                                                  ('presencial', 'Presencial')]},
                 'offerings': [],
                 'records': {'customers': {'label': 'Clientes',
                                           'singular': 'Cliente',
                                           'description': 'Base de clientes acompanhados pelo pós-venda.',
                                           'status_category': 'customer_status',
                                           'fields': [{'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                      {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                      {'key': 'product',
                                                       'label': 'Produto ou serviço contratado',
                                                       'type': 'text'}],
                                           'due_label': False,
                                           'amount_label': False,
                                           'amount_format': 'currency',
                                           'assigned_label': 'Responsável pelo relacionamento',
                                           'subtitle_label': 'Produto ou contrato',
                                           'notes_label': 'Observações',
                                           'title_label': 'Nome do cliente'},
                             'tickets': {'label': 'Chamados',
                                         'singular': 'Chamado',
                                         'description': 'Solicitações, dúvidas e problemas dos clientes.',
                                         'status_category': 'ticket_status',
                                         'due_label': 'Prazo/SLA',
                                         'fields': [{'key': 'customer',
                                                     'label': 'Cliente',
                                                     'type': 'record',
                                                     'module': 'customers',
                                                     'required': True},
                                                    {'key': 'priority',
                                                     'label': 'Prioridade',
                                                     'type': 'catalog',
                                                     'category': 'ticket_priority',
                                                     'required': True},
                                                    {'key': 'channel',
                                                     'label': 'Canal de atendimento',
                                                     'type': 'catalog',
                                                     'category': 'support_channel'}],
                                         'amount_label': False,
                                         'amount_format': 'currency',
                                         'assigned_label': 'Analista responsável',
                                         'subtitle_label': 'Resumo do chamado',
                                         'notes_label': 'Observações',
                                         'title_label': 'Assunto do chamado'},
                             'followups': {'label': 'Acompanhamentos',
                                           'singular': 'Acompanhamento',
                                           'description': 'Retornos e ações de relacionamento.',
                                           'status_category': 'followup_status',
                                           'due_label': 'Data do retorno',
                                           'fields': [{'key': 'customer',
                                                       'label': 'Cliente',
                                                       'type': 'record',
                                                       'module': 'customers',
                                                       'required': True},
                                                      {'key': 'reason',
                                                       'label': 'Motivo detalhado',
                                                       'type': 'textarea'},
                                                      {'key': 'channel',
                                                       'label': 'Canal de contato',
                                                       'type': 'catalog',
                                                       'category': 'support_channel'}],
                                           'amount_label': False,
                                           'amount_format': 'currency',
                                           'assigned_label': 'Responsável pelo retorno',
                                           'subtitle_label': 'Resumo do acompanhamento',
                                           'notes_label': 'Observações',
                                           'title_label': 'Motivo do acompanhamento'}}},
 'real_estate': {'name': 'Imobiliária e corretores',
                 'category': 'Imobiliário',
                 'description': 'Imóveis, interessados, visitas, propostas e desempenho de corretores.',
                 'recommended_for': 'Imobiliárias, corretores autônomos e equipes de lançamentos imobiliários.',
                 'operation_group_label': 'Imobiliário',
                 'modules': ['dashboard',
                             'properties',
                             'real_estate_leads',
                             'visits',
                             'proposals',
                             'daily',
                             'ranking',
                             'intelligence',
                             'users',
                             'teams',
                             'services_catalog',
                             'catalogs',
                             'roles',
                             'audit',
                             'integrations'],
                 'navigation_labels': {'properties': 'Imóveis',
                                       'real_estate_leads': 'Interessados',
                                       'visits': 'Visitas',
                                       'proposals': 'Propostas',
                                       'plans': 'Serviços imobiliários'},
                 'admin_labels': {'plans_title': 'Serviços imobiliários',
                                  'plans_singular': 'serviço',
                                  'provider': 'Área/Unidade',
                                  'service': 'Modalidade',
                                  'attribute': 'Prazo/Referência',
                                  'coverage': 'Regiões atendidas'},
                 'roles': [{'code': 'gerente_imobiliario',
                            'name': 'Gerente imobiliário',
                            'base_role': 'manager',
                            'description': 'Gerencia imóveis, corretores e propostas.',
                            'permissions': ['dashboard.view',
                                            'properties.view',
                                            'properties.manage',
                                            'real_estate_leads.view',
                                            'real_estate_leads.manage',
                                            'visits.view',
                                            'visits.manage',
                                            'proposals.view',
                                            'proposals.manage',
                                            'daily.view',
                                            'ranking.all',
                                            'users.view',
                                            'teams.view',
                                            'plans.view',
                                            'catalogs.view',
                                            'intelligence.view',
                                            'ai.use']},
                           {'code': 'corretor',
                            'name': 'Corretor',
                            'base_role': 'seller',
                            'description': 'Acompanha interessados, visitas e propostas.',
                            'permissions': ['dashboard.view',
                                            'properties.view',
                                            'real_estate_leads.view',
                                            'real_estate_leads.manage',
                                            'visits.view',
                                            'visits.manage',
                                            'proposals.view',
                                            'proposals.manage',
                                            'ranking.own']},
                           {'code': 'assistente_imobiliario',
                            'name': 'Assistente imobiliário',
                            'base_role': 'bko',
                            'description': 'Organiza cadastros, agenda e documentação.',
                            'permissions': ['dashboard.view',
                                            'properties.view',
                                            'properties.manage',
                                            'real_estate_leads.view',
                                            'real_estate_leads.manage',
                                            'visits.view',
                                            'visits.manage',
                                            'proposals.view']}],
                 'catalog_labels': {'property_type': 'Tipos de imóvel',
                                    'property_status': 'Status do imóvel',
                                    'lead_interest': 'Interesse do cliente',
                                    'visit_status': 'Status da visita',
                                    'proposal_status': 'Status da proposta',
                                    'transaction_type': 'Modalidade',
                                    'visit_period': 'Períodos de visita'},
                 'catalogs': {'property_type': [('apartamento', 'Apartamento'),
                                                ('casa', 'Casa'),
                                                ('terreno', 'Terreno'),
                                                ('comercial', 'Comercial'),
                                                ('rural', 'Rural')],
                              'property_status': [('disponivel', 'Disponível'),
                                                  ('reservado', 'Reservado'),
                                                  ('negociacao', 'Em negociação'),
                                                  ('vendido', 'Vendido'),
                                                  ('alugado', 'Alugado'),
                                                  ('inativo', 'Inativo')],
                              'lead_interest': [('compra', 'Compra'),
                                                ('locacao', 'Locação'),
                                                ('investimento', 'Investimento')],
                              'visit_status': [('solicitada', 'Solicitada'),
                                               ('agendada', 'Agendada'),
                                               ('confirmada', 'Confirmada'),
                                               ('realizada', 'Realizada'),
                                               ('cancelada', 'Cancelada')],
                              'proposal_status': [('rascunho', 'Rascunho'),
                                                  ('enviada', 'Enviada'),
                                                  ('negociacao', 'Em negociação'),
                                                  ('aceita', 'Aceita'),
                                                  ('recusada', 'Recusada')],
                              'transaction_type': [('venda', 'Venda'),
                                                   ('locacao', 'Locação'),
                                                   ('temporada', 'Temporada')],
                              'visit_period': [('manha', 'Manhã'),
                                               ('tarde', 'Tarde'),
                                               ('noite', 'Noite'),
                                               ('flexivel', 'Horário flexível')]},
                 'offerings': [{'provider': 'Imobiliária',
                                'service': 'Venda',
                                'name': 'Intermediação de venda',
                                'speed': 'Por negociação',
                                'price': 0,
                                'benefits': 'Captação, divulgação, visitas e negociação'},
                               {'provider': 'Imobiliária',
                                'service': 'Locação',
                                'name': 'Administração de locação',
                                'speed': 'Mensal',
                                'price': 0,
                                'benefits': 'Gestão contratual e acompanhamento'},
                               {'provider': 'Imobiliária',
                                'service': 'Avaliação',
                                'name': 'Avaliação imobiliária',
                                'speed': 'Sob agendamento',
                                'price': 0,
                                'benefits': 'Parecer comercial do imóvel'}],
                 'records': {'properties': {'label': 'Imóveis',
                                            'singular': 'Imóvel',
                                            'description': 'Carteira de imóveis disponíveis e negociados.',
                                            'status_category': 'property_status',
                                            'amount_label': 'Valor do imóvel',
                                            'fields': [{'key': 'code', 'label': 'Código do imóvel', 'type': 'text'},
                                                       {'key': 'property_type',
                                                        'label': 'Tipo de imóvel',
                                                        'type': 'catalog',
                                                        'category': 'property_type',
                                                        'required': True},
                                                       {'key': 'transaction_type',
                                                        'label': 'Modalidade',
                                                        'type': 'catalog',
                                                        'category': 'transaction_type',
                                                        'required': True},
                                                       {'key': 'location',
                                                        'label': 'Endereço / região',
                                                        'type': 'text',
                                                        'required': True},
                                                       {'key': 'bedrooms',
                                                        'label': 'Quartos',
                                                        'type': 'number',
                                                        'min': 0,
                                                        'step': 1},
                                                       {'key': 'area',
                                                        'label': 'Área (m²)',
                                                        'type': 'number',
                                                        'min': 0,
                                                        'step': 0.01}],
                                            'due_label': False,
                                            'amount_format': 'currency',
                                            'assigned_label': 'Corretor responsável',
                                            'subtitle_label': 'Endereço resumido',
                                            'notes_label': 'Observações',
                                            'title_label': 'Título do imóvel'},
                             'real_estate_leads': {'label': 'Interessados',
                                                   'singular': 'Interessado',
                                                   'description': 'Pessoas interessadas em compra, locação ou '
                                                                  'investimento.',
                                                   'status_options': [('novo', 'Novo'),
                                                                      ('contato', 'Em contato'),
                                                                      ('qualificado', 'Qualificado'),
                                                                      ('sem_interesse', 'Sem interesse')],
                                                   'fields': [{'key': 'interest',
                                                               'label': 'Tipo de interesse',
                                                               'type': 'catalog',
                                                               'category': 'lead_interest',
                                                               'required': True},
                                                              {'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                              {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                              {'key': 'property',
                                                               'label': 'Imóvel de interesse',
                                                               'type': 'record',
                                                               'module': 'properties'}],
                                                   'due_label': False,
                                                   'amount_label': False,
                                                   'amount_format': 'currency',
                                                   'assigned_label': 'Corretor responsável',
                                                   'subtitle_label': 'Preferências principais',
                                                   'notes_label': 'Observações',
                                                   'title_label': 'Nome do interessado'},
                             'visits': {'label': 'Visitas',
                                        'singular': 'Visita',
                                        'description': 'Agenda e resultado das visitas aos imóveis.',
                                        'status_category': 'visit_status',
                                        'due_label': 'Data da visita',
                                        'fields': [{'key': 'property',
                                                    'label': 'Imóvel',
                                                    'type': 'record',
                                                    'module': 'properties',
                                                    'required': True},
                                                   {'key': 'client',
                                                    'label': 'Interessado',
                                                    'type': 'record',
                                                    'module': 'real_estate_leads',
                                                    'required': True},
                                                   {'key': 'period',
                                                    'label': 'Período',
                                                    'type': 'catalog',
                                                    'category': 'visit_period',
                                                    'required': True},
                                                   {'key': 'feedback',
                                                    'label': 'Feedback da visita',
                                                    'type': 'textarea'}],
                                        'amount_label': False,
                                        'amount_format': 'currency',
                                        'assigned_label': 'Corretor responsável',
                                        'subtitle_label': 'Objetivo ou orientação',
                                        'notes_label': 'Observações',
                                        'title_label': 'Identificação da visita'},
                             'proposals': {'label': 'Propostas',
                                           'singular': 'Proposta',
                                           'description': 'Propostas de compra ou locação.',
                                           'status_category': 'proposal_status',
                                           'amount_label': 'Valor proposto',
                                           'due_label': 'Validade',
                                           'fields': [{'key': 'property',
                                                       'label': 'Imóvel',
                                                       'type': 'record',
                                                       'module': 'properties',
                                                       'required': True},
                                                      {'key': 'client',
                                                       'label': 'Interessado',
                                                       'type': 'record',
                                                       'module': 'real_estate_leads',
                                                       'required': True},
                                                      {'key': 'transaction_type',
                                                       'label': 'Modalidade',
                                                       'type': 'catalog',
                                                       'category': 'transaction_type',
                                                       'required': True},
                                                      {'key': 'conditions',
                                                       'label': 'Condições da proposta',
                                                       'type': 'textarea'}],
                                           'amount_format': 'currency',
                                           'assigned_label': 'Corretor responsável',
                                           'subtitle_label': 'Resumo da negociação',
                                           'notes_label': 'Observações',
                                           'title_label': 'Identificação da proposta'}}},
 'retail': {'name': 'Loja e varejo',
            'category': 'Varejo',
            'description': 'Produtos, pedidos, estoque, caixa e desempenho da operação.',
            'recommended_for': 'Lojas físicas, pequenos varejos, quiosques e operações comerciais enxutas.',
            'operation_group_label': 'Loja',
            'modules': ['dashboard',
                        'products',
                        'customers',
                        'orders',
                        'stock',
                        'cash',
                        'daily',
                        'ranking',
                        'intelligence',
                        'users',
                        'teams',
                        'catalogs',
                        'roles',
                        'audit',
                        'integrations'],
            'navigation_labels': {'products': 'Produtos',
                                  'orders': 'Pedidos',
                                  'stock': 'Estoque',
                                  'cash': 'Caixa',
                                  'customers': 'Clientes'},
            'roles': [{'code': 'gerente_loja',
                       'name': 'Gerente de loja',
                       'base_role': 'manager',
                       'description': 'Gerencia produtos, pedidos, estoque e equipe.',
                       'permissions': ['dashboard.view',
                                       'products.view',
                                       'products.manage',
                                       'orders.view',
                                       'orders.manage',
                                       'stock.view',
                                       'stock.manage',
                                       'cash.view',
                                       'cash.manage',
                                       'daily.view',
                                       'ranking.all',
                                       'users.view',
                                       'teams.view',
                                       'intelligence.view',
                                       'ai.use',
                                       'customers.view',
                                       'customers.manage']},
                      {'code': 'vendedor_loja',
                       'name': 'Vendedor',
                       'base_role': 'seller',
                       'description': 'Cadastra e acompanha pedidos.',
                       'permissions': ['dashboard.view',
                                       'products.view',
                                       'orders.view',
                                       'orders.manage',
                                       'stock.view',
                                       'ranking.own',
                                       'customers.view',
                                       'customers.manage']},
                      {'code': 'estoquista',
                       'name': 'Estoquista',
                       'base_role': 'bko',
                       'description': 'Controla produtos e movimentações de estoque.',
                       'permissions': ['dashboard.view',
                                       'products.view',
                                       'products.manage',
                                       'stock.view',
                                       'stock.manage']}],
            'catalog_labels': {'product_category': 'Categorias de produto',
                               'product_status': 'Status do produto',
                               'order_status': 'Status do pedido',
                               'stock_movement': 'Movimentos de estoque',
                               'customer_status': 'Status do cliente',
                               'retail_payment_method': 'Formas de pagamento'},
            'catalogs': {'product_category': [('geral', 'Geral'),
                                              ('eletronicos', 'Eletrônicos'),
                                              ('vestuario', 'Vestuário'),
                                              ('casa', 'Casa e decoração')],
                         'product_status': [('ativo', 'Ativo'),
                                            ('sem_estoque', 'Sem estoque'),
                                            ('descontinuado', 'Descontinuado')],
                         'order_status': [('aberto', 'Aberto'),
                                          ('pago', 'Pago'),
                                          ('separacao', 'Em separação'),
                                          ('entregue', 'Entregue'),
                                          ('cancelado', 'Cancelado')],
                         'stock_movement': [('entrada', 'Entrada'),
                                            ('saida', 'Saída'),
                                            ('ajuste', 'Ajuste'),
                                            ('perda', 'Perda')],
                         'customer_status': [('ativo', 'Ativo'), ('vip', 'VIP'), ('inativo', 'Inativo')],
                         'retail_payment_method': [('pix', 'PIX'),
                                                   ('dinheiro', 'Dinheiro'),
                                                   ('debito', 'Cartão de débito'),
                                                   ('credito', 'Cartão de crédito'),
                                                   ('boleto', 'Boleto')]},
            'offerings': [],
            'records': {'products': {'label': 'Produtos',
                                     'singular': 'Produto',
                                     'description': 'Cadastro de produtos comercializados.',
                                     'status_category': 'product_status',
                                     'amount_label': 'Preço de venda',
                                     'fields': [{'key': 'sku', 'label': 'SKU / código', 'type': 'text'},
                                                {'key': 'category',
                                                 'label': 'Categoria',
                                                 'type': 'catalog',
                                                 'category': 'product_category',
                                                 'required': True},
                                                {'key': 'cost',
                                                 'label': 'Custo unitário',
                                                 'type': 'number',
                                                 'min': 0,
                                                 'step': 0.01},
                                                {'key': 'minimum_stock',
                                                 'label': 'Estoque mínimo',
                                                 'type': 'number',
                                                 'min': 0,
                                                 'step': 1}],
                                     'due_label': False,
                                     'amount_format': 'currency',
                                     'assigned_label': False,
                                     'subtitle_label': 'Marca ou modelo',
                                     'notes_label': 'Observações',
                                     'title_label': 'Nome do produto'},
                        'orders': {'label': 'Pedidos',
                                   'singular': 'Pedido',
                                   'description': 'Pedidos e vendas realizadas.',
                                   'status_category': 'order_status',
                                   'amount_label': 'Valor total',
                                   'due_label': 'Data de entrega',
                                   'fields': [{'key': 'customer',
                                               'label': 'Cliente',
                                               'type': 'record',
                                               'module': 'customers',
                                               'required': True},
                                              {'key': 'items',
                                               'label': 'Itens do pedido',
                                               'type': 'textarea',
                                               'required': True},
                                              {'key': 'payment_method',
                                               'label': 'Forma de pagamento',
                                               'type': 'catalog',
                                               'category': 'retail_payment_method',
                                               'required': True}],
                                   'amount_format': 'currency',
                                   'assigned_label': 'Vendedor responsável',
                                   'subtitle_label': 'Resumo do pedido',
                                   'notes_label': 'Observações',
                                   'title_label': 'Número ou identificação do pedido'},
                        'stock': {'label': 'Estoque',
                                  'singular': 'Movimentação de estoque',
                                  'description': 'Entradas, saídas e ajustes de estoque.',
                                  'status_category': 'stock_movement',
                                  'amount_label': 'Quantidade',
                                  'fields': [{'key': 'product',
                                              'label': 'Produto',
                                              'type': 'record',
                                              'module': 'products',
                                              'required': True},
                                             {'key': 'movement',
                                              'label': 'Tipo de movimentação',
                                              'type': 'catalog',
                                              'category': 'stock_movement',
                                              'required': True},
                                             {'key': 'document', 'label': 'Documento / referência', 'type': 'text'},
                                             {'key': 'location', 'label': 'Localização no estoque', 'type': 'text'}],
                                  'due_label': False,
                                  'amount_format': 'number',
                                  'assigned_label': 'Responsável pela movimentação',
                                  'subtitle_label': 'Referência ou lote',
                                  'notes_label': 'Observações',
                                  'title_label': 'Identificação da movimentação',
                                  'amount_step': 1},
                        'customers': {'label': 'Clientes',
                                      'singular': 'Cliente',
                                      'description': 'Clientes e compradores da loja.',
                                      'status_category': 'customer_status',
                                      'title_label': 'Nome do cliente',
                                      'assigned_label': 'Vendedor responsável',
                                      'subtitle_label': 'Observação do cliente',
                                      'due_label': False,
                                      'amount_label': False,
                                      'amount_format': 'currency',
                                      'notes_label': 'Observações',
                                      'fields': [{'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                 {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                 {'key': 'document', 'label': 'CPF / CNPJ', 'type': 'text'}]}}},
 'consulting': {'name': 'Consultoria e projetos',
                'category': 'Serviços',
                'description': 'Clientes, projetos, entregas, tarefas e acompanhamento gerencial.',
                'recommended_for': 'Consultorias, agências, escritórios e empresas de projetos sob demanda.',
                'operation_group_label': 'Projetos',
                'modules': ['dashboard',
                            'clients',
                            'projects',
                            'deliverables',
                            'tasks',
                            'daily',
                            'intelligence',
                            'users',
                            'teams',
                            'services_catalog',
                            'catalogs',
                            'roles',
                            'audit',
                            'integrations'],
                'navigation_labels': {'clients': 'Clientes',
                                      'projects': 'Projetos',
                                      'deliverables': 'Entregas',
                                      'tasks': 'Tarefas',
                                      'plans': 'Serviços e pacotes'},
                'roles': [{'code': 'gerente_projetos',
                           'name': 'Gerente de projetos',
                           'base_role': 'manager',
                           'description': 'Gerencia clientes, projetos e entregas.',
                           'permissions': ['dashboard.view',
                                           'clients.view',
                                           'clients.manage',
                                           'projects.view',
                                           'projects.manage',
                                           'deliverables.view',
                                           'deliverables.manage',
                                           'tasks.view',
                                           'tasks.manage',
                                           'daily.view',
                                           'users.view',
                                           'teams.view',
                                           'plans.view',
                                           'intelligence.view',
                                           'ai.use']},
                          {'code': 'consultor',
                           'name': 'Consultor',
                           'base_role': 'seller',
                           'description': 'Executa atividades e atualiza entregas.',
                           'permissions': ['dashboard.view',
                                           'clients.view',
                                           'projects.view',
                                           'deliverables.view',
                                           'deliverables.manage',
                                           'tasks.view',
                                           'tasks.manage']},
                          {'code': 'analista_projetos',
                           'name': 'Analista de projetos',
                           'base_role': 'bko',
                           'description': 'Apoia documentação, agenda e controle.',
                           'permissions': ['dashboard.view',
                                           'clients.view',
                                           'clients.manage',
                                           'projects.view',
                                           'projects.manage',
                                           'deliverables.view',
                                           'tasks.view',
                                           'tasks.manage']}],
                'catalog_labels': {'client_status': 'Status do cliente',
                                   'project_status': 'Status do projeto',
                                   'deliverable_status': 'Status da entrega',
                                   'task_status': 'Status da tarefa',
                                   'client_segment': 'Segmentos de cliente',
                                   'task_priority': 'Prioridades de tarefa'},
                'catalogs': {'client_status': [('prospect', 'Prospect'),
                                               ('ativo', 'Ativo'),
                                               ('pausado', 'Pausado'),
                                               ('encerrado', 'Encerrado')],
                             'project_status': [('planejamento', 'Planejamento'),
                                                ('em_execucao', 'Em execução'),
                                                ('aguardando', 'Aguardando cliente'),
                                                ('concluido', 'Concluído'),
                                                ('cancelado', 'Cancelado')],
                             'deliverable_status': [('pendente', 'Pendente'),
                                                    ('em_revisao', 'Em revisão'),
                                                    ('aprovada', 'Aprovada'),
                                                    ('atrasada', 'Atrasada')],
                             'task_status': [('pendente', 'Pendente'),
                                             ('em_andamento', 'Em andamento'),
                                             ('concluida', 'Concluída'),
                                             ('bloqueada', 'Bloqueada')],
                             'client_segment': [('servicos', 'Serviços'),
                                                ('varejo', 'Varejo'),
                                                ('industria', 'Indústria'),
                                                ('tecnologia', 'Tecnologia'),
                                                ('saude', 'Saúde'),
                                                ('outro', 'Outro')],
                             'task_priority': [('baixa', 'Baixa'),
                                               ('normal', 'Normal'),
                                               ('alta', 'Alta'),
                                               ('critica', 'Crítica')]},
                'offerings': [{'provider': 'Consultoria',
                               'service': 'Diagnóstico',
                               'name': 'Diagnóstico inicial',
                               'speed': 'Projeto',
                               'price': 0,
                               'benefits': 'Levantamento e recomendações'},
                              {'provider': 'Consultoria',
                               'service': 'Projeto',
                               'name': 'Pacote de consultoria',
                               'speed': 'Mensal',
                               'price': 0,
                               'benefits': 'Acompanhamento por escopo'}],
                'records': {'clients': {'label': 'Clientes',
                                        'singular': 'Cliente',
                                        'description': 'Clientes e prospects da consultoria.',
                                        'status_category': 'client_status',
                                        'fields': [{'key': 'company', 'label': 'Empresa', 'type': 'text'},
                                                   {'key': 'contact', 'label': 'Contato principal', 'type': 'text'},
                                                   {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                   {'key': 'segment',
                                                    'label': 'Segmento',
                                                    'type': 'catalog',
                                                    'category': 'client_segment'}],
                                        'due_label': False,
                                        'amount_label': False,
                                        'amount_format': 'currency',
                                        'assigned_label': 'Consultor responsável',
                                        'subtitle_label': 'Empresa ou unidade',
                                        'notes_label': 'Observações',
                                        'title_label': 'Nome do cliente'},
                            'projects': {'label': 'Projetos',
                                         'singular': 'Projeto',
                                         'description': 'Projetos em planejamento ou execução.',
                                         'status_category': 'project_status',
                                         'amount_label': 'Valor contratado',
                                         'due_label': 'Prazo final',
                                         'fields': [{'key': 'client',
                                                     'label': 'Cliente',
                                                     'type': 'record',
                                                     'module': 'clients',
                                                     'required': True},
                                                    {'key': 'scope',
                                                     'label': 'Escopo',
                                                     'type': 'textarea',
                                                     'required': True}],
                                         'amount_format': 'currency',
                                         'assigned_label': 'Gerente do projeto',
                                         'subtitle_label': 'Resumo executivo',
                                         'notes_label': 'Observações',
                                         'title_label': 'Nome do projeto'},
                            'deliverables': {'label': 'Entregas',
                                             'singular': 'Entrega',
                                             'description': 'Marcos e entregáveis dos projetos.',
                                             'status_category': 'deliverable_status',
                                             'due_label': 'Prazo',
                                             'fields': [{'key': 'project',
                                                         'label': 'Projeto',
                                                         'type': 'record',
                                                         'module': 'projects',
                                                         'required': True}],
                                             'amount_label': False,
                                             'amount_format': 'currency',
                                             'assigned_label': 'Aprovador ou responsável',
                                             'subtitle_label': 'Critério de aceite',
                                             'notes_label': 'Observações',
                                             'title_label': 'Nome da entrega'},
                            'tasks': {'label': 'Tarefas',
                                      'singular': 'Tarefa',
                                      'description': 'Atividades dos projetos.',
                                      'status_category': 'task_status',
                                      'due_label': 'Prazo',
                                      'fields': [{'key': 'project',
                                                  'label': 'Projeto',
                                                  'type': 'record',
                                                  'module': 'projects',
                                                  'required': True},
                                                 {'key': 'priority',
                                                  'label': 'Prioridade',
                                                  'type': 'catalog',
                                                  'category': 'task_priority',
                                                  'required': True}],
                                      'amount_label': False,
                                      'amount_format': 'currency',
                                      'assigned_label': 'Responsável pela tarefa',
                                      'subtitle_label': 'Descrição curta',
                                      'notes_label': 'Observações',
                                      'title_label': 'Título da tarefa'}}},
 'recruitment': {'name': 'Recrutamento e seleção',
                 'category': 'Pessoas',
                 'description': 'Vagas, candidatos, entrevistas e tarefas de seleção.',
                 'recommended_for': 'RH interno, consultorias de recrutamento e seleção de alto volume.',
                 'operation_group_label': 'Recrutamento',
                 'modules': ['dashboard',
                             'vacancies',
                             'candidates',
                             'interviews',
                             'tasks',
                             'daily',
                             'intelligence',
                             'users',
                             'teams',
                             'services_catalog',
                             'catalogs',
                             'roles',
                             'audit',
                             'integrations'],
                 'navigation_labels': {'vacancies': 'Vagas',
                                       'candidates': 'Candidatos',
                                       'interviews': 'Entrevistas',
                                       'tasks': 'Tarefas',
                                       'plans': 'Serviços de recrutamento'},
                 'roles': [{'code': 'coordenador_rh',
                            'name': 'Coordenador de RH',
                            'base_role': 'manager',
                            'description': 'Gerencia vagas, candidatos e indicadores.',
                            'permissions': ['dashboard.view',
                                            'vacancies.view',
                                            'vacancies.manage',
                                            'candidates.view',
                                            'candidates.manage',
                                            'interviews.view',
                                            'interviews.manage',
                                            'tasks.view',
                                            'tasks.manage',
                                            'daily.view',
                                            'users.view',
                                            'teams.view',
                                            'intelligence.view',
                                            'ai.use']},
                           {'code': 'recrutador',
                            'name': 'Recrutador',
                            'base_role': 'seller',
                            'description': 'Trabalha candidatos e entrevistas.',
                            'permissions': ['dashboard.view',
                                            'vacancies.view',
                                            'candidates.view',
                                            'candidates.manage',
                                            'interviews.view',
                                            'interviews.manage',
                                            'tasks.view',
                                            'tasks.manage']},
                           {'code': 'assistente_rh',
                            'name': 'Assistente de RH',
                            'base_role': 'bko',
                            'description': 'Apoia triagem, agenda e documentação.',
                            'permissions': ['dashboard.view',
                                            'vacancies.view',
                                            'candidates.view',
                                            'candidates.manage',
                                            'interviews.view',
                                            'interviews.manage',
                                            'tasks.view']}],
                 'catalog_labels': {'vacancy_status': 'Status da vaga',
                                    'candidate_stage': 'Etapas do candidato',
                                    'interview_status': 'Status da entrevista',
                                    'task_status': 'Status da tarefa',
                                    'hr_department': 'Áreas e departamentos',
                                    'work_model': 'Modelos de trabalho',
                                    'employment_type': 'Tipos de contratação',
                                    'candidate_source': 'Canais de candidatura',
                                    'interview_format': 'Formatos de entrevista',
                                    'task_priority': 'Prioridades de tarefa'},
                 'catalogs': {'vacancy_status': [('rascunho', 'Rascunho'),
                                                 ('aberta', 'Aberta'),
                                                 ('pausada', 'Pausada'),
                                                 ('preenchida', 'Preenchida'),
                                                 ('cancelada', 'Cancelada')],
                              'candidate_stage': [('inscrito', 'Inscrito'),
                                                  ('triagem', 'Triagem'),
                                                  ('entrevista', 'Entrevista'),
                                                  ('proposta', 'Proposta'),
                                                  ('contratado', 'Contratado'),
                                                  ('reprovado', 'Reprovado')],
                              'interview_status': [('agendada', 'Agendada'),
                                                   ('confirmada', 'Confirmada'),
                                                   ('realizada', 'Realizada'),
                                                   ('reagendada', 'Reagendada'),
                                                   ('cancelada', 'Cancelada')],
                              'task_status': [('pendente', 'Pendente'),
                                              ('em_andamento', 'Em andamento'),
                                              ('concluida', 'Concluída')],
                              'hr_department': [('administrativo', 'Administrativo'),
                                                ('comercial', 'Comercial'),
                                                ('financeiro', 'Financeiro'),
                                                ('operacoes', 'Operações'),
                                                ('rh', 'Recursos Humanos'),
                                                ('tecnologia', 'Tecnologia'),
                                                ('outro', 'Outro')],
                              'work_model': [('presencial', 'Presencial'),
                                             ('hibrido', 'Híbrido'),
                                             ('remoto', 'Remoto')],
                              'employment_type': [('clt', 'CLT'),
                                                  ('pj', 'Pessoa jurídica'),
                                                  ('estagio', 'Estágio'),
                                                  ('temporario', 'Temporário'),
                                                  ('freelancer', 'Freelancer')],
                              'candidate_source': [('linkedin', 'LinkedIn'),
                                                   ('indeed', 'Indeed'),
                                                   ('gupy', 'Gupy'),
                                                   ('indicacao', 'Indicação'),
                                                   ('site', 'Site da empresa'),
                                                   ('banco_talentos', 'Banco de talentos'),
                                                   ('outro', 'Outro')],
                              'interview_format': [('video', 'Videoconferência'),
                                                   ('presencial', 'Presencial'),
                                                   ('telefone', 'Telefone'),
                                                   ('teste_tecnico', 'Teste técnico')],
                              'task_priority': [('baixa', 'Baixa'),
                                                ('normal', 'Normal'),
                                                ('alta', 'Alta'),
                                                ('urgente', 'Urgente')]},
                 'offerings': [{'provider': 'RH',
                                'service': 'Recrutamento',
                                'name': 'Seleção por vaga',
                                'speed': 'Por processo',
                                'price': 0,
                                'benefits': 'Divulgação, triagem e entrevistas'}],
                 'records': {'vacancies': {'label': 'Vagas',
                                           'singular': 'Vaga',
                                           'description': 'Vagas abertas e processos seletivos.',
                                           'status_category': 'vacancy_status',
                                           'amount_label': False,
                                           'due_label': 'Data limite',
                                           'fields': [{'key': 'department',
                                                       'label': 'Área / departamento',
                                                       'type': 'catalog',
                                                       'category': 'hr_department',
                                                       'required': True},
                                                      {'key': 'location', 'label': 'Localidade', 'type': 'text'},
                                                      {'key': 'work_model',
                                                       'label': 'Modelo de trabalho',
                                                       'type': 'catalog',
                                                       'category': 'work_model',
                                                       'required': True},
                                                      {'key': 'employment_type',
                                                       'label': 'Tipo de contratação',
                                                       'type': 'catalog',
                                                       'category': 'employment_type',
                                                       'required': True},
                                                      {'key': 'positions',
                                                       'label': 'Quantidade de vagas',
                                                       'type': 'number',
                                                       'min': 1,
                                                       'step': 1,
                                                       'required': True},
                                                      {'key': 'salary_min',
                                                       'label': 'Salário mínimo',
                                                       'type': 'number',
                                                       'min': 0,
                                                       'step': 0.01},
                                                      {'key': 'salary_max',
                                                       'label': 'Salário máximo',
                                                       'type': 'number',
                                                       'min': 0,
                                                       'step': 0.01}],
                                           'amount_format': 'currency',
                                           'assigned_label': 'Recrutador responsável',
                                           'subtitle_label': 'Resumo da oportunidade',
                                           'notes_label': 'Observações',
                                           'title_label': 'Título da vaga'},
                             'candidates': {'label': 'Candidatos',
                                            'singular': 'Candidato',
                                            'description': 'Candidatos e etapa atual no processo.',
                                            'status_category': 'candidate_stage',
                                            'fields': [{'key': 'phone', 'label': 'Telefone', 'type': 'tel'},
                                                       {'key': 'email', 'label': 'E-mail', 'type': 'email'},
                                                       {'key': 'vacancy',
                                                        'label': 'Vaga pretendida',
                                                        'type': 'record',
                                                        'module': 'vacancies',
                                                        'status_in': ['aberta'],
                                                        'required': True},
                                                       {'key': 'source',
                                                        'label': 'Canal de candidatura',
                                                        'type': 'catalog',
                                                        'category': 'candidate_source'},
                                                       {'key': 'city', 'label': 'Cidade', 'type': 'text'},
                                                       {'key': 'resume_url',
                                                        'label': 'Link do currículo / portfólio',
                                                        'type': 'url'},
                                                       {'key': 'salary_expectation',
                                                        'label': 'Pretensão salarial',
                                                        'type': 'number',
                                                        'min': 0,
                                                        'step': 0.01}],
                                            'due_label': False,
                                            'amount_label': False,
                                            'amount_format': 'currency',
                                            'assigned_label': 'Recrutador responsável',
                                            'subtitle_label': 'Resumo profissional',
                                            'notes_label': 'Observações',
                                            'title_label': 'Nome completo do candidato'},
                             'interviews': {'label': 'Entrevistas',
                                            'singular': 'Entrevista',
                                            'description': 'Agenda e resultado das entrevistas.',
                                            'status_category': 'interview_status',
                                            'due_label': 'Data da entrevista',
                                            'fields': [{'key': 'candidate',
                                                        'label': 'Candidato',
                                                        'type': 'record',
                                                        'module': 'candidates',
                                                        'required': True},
                                                       {'key': 'vacancy',
                                                        'label': 'Vaga',
                                                        'type': 'record',
                                                        'module': 'vacancies',
                                                        'required': True},
                                                       {'key': 'format',
                                                        'label': 'Formato',
                                                        'type': 'catalog',
                                                        'category': 'interview_format',
                                                        'required': True},
                                                       {'key': 'location_or_link',
                                                        'label': 'Local ou link da entrevista',
                                                        'type': 'text'}],
                                            'amount_label': False,
                                            'amount_format': 'currency',
                                            'assigned_label': 'Entrevistador responsável',
                                            'subtitle_label': 'Pauta ou orientação',
                                            'notes_label': 'Observações',
                                            'title_label': 'Identificação da entrevista'},
                             'tasks': {'label': 'Tarefas',
                                       'singular': 'Tarefa',
                                       'description': 'Pendências do processo seletivo.',
                                       'status_category': 'task_status',
                                       'due_label': 'Prazo',
                                       'fields': [{'key': 'related_to',
                                                   'label': 'Candidato relacionado',
                                                   'type': 'record',
                                                   'module': 'candidates'},
                                                  {'key': 'priority',
                                                   'label': 'Prioridade',
                                                   'type': 'catalog',
                                                   'category': 'task_priority',
                                                   'required': True}],
                                       'amount_label': False,
                                       'amount_format': 'currency',
                                       'assigned_label': 'Responsável pela tarefa',
                                       'subtitle_label': 'Descrição curta',
                                       'notes_label': 'Observações',
                                       'title_label': 'Título da tarefa'}}},
 'custom': {'name': 'Perfil personalizado',
            'category': 'Personalizado',
            'description': 'Estrutura mínima para montar um perfil escolhendo manualmente os módulos necessários.',
            'recommended_for': 'Operações que não se encaixam nos modelos prontos ou precisam começar do zero.',
            'operation_group_label': 'Operação',
            'modules': ['dashboard', 'users', 'roles', 'audit'],
            'navigation_labels': {},
            'roles': [],
            'catalog_labels': {},
            'catalogs': {},
            'offerings': [],
            'records': {}}}

GENERIC_RECORD_MODULES = ['accounts_payable',
 'accounts_receivable',
 'agreements',
 'candidates',
 'clients',
 'customers',
 'debtors',
 'deliverables',
 'followups',
 'interviews',
 'leads',
 'negotiations',
 'opportunities',
 'orders',
 'products',
 'projects',
 'properties',
 'proposals',
 'real_estate_leads',
 'schedule',
 'service_orders',
 'stock',
 'tasks',
 'tickets',
 'vacancies',
 'visits']
PRESET_SCHEMA_VERSION = 3

# O Contratante funciona como administrador de visualização do perfil.
# Ele enxerga todos os dados permitidos no próprio ambiente, mas não cria,
# edita, exclui, trata ou configura registros.
PROFILE_CONTRACTOR_PERMISSIONS = {
    "profile.view",
    "dashboard.view",
    "sales.all",
    "ranking.all", "daily.view",
    "users.view", "teams.view",
    "plans.view", "catalogs.view", "roles.view", "audit.view",
    "intelligence.view", "ai.use", "powerbi.view", "integrations.view",
    "cash.view",
}

PROFILE_ADMIN_PERMISSIONS = {
    "users.manage", "teams.manage", "plans.manage", "catalogs.manage",
    "roles.manage", "integrations.manage",
}

# Visualização genérica para o Contratante. A checagem de módulo continua
# sendo feita pelo perfil ativo, portanto ele não ganha acesso cruzado.
PROFILE_CONTRACTOR_PERMISSIONS.update({f"{module}.view" for module in GENERIC_RECORD_MODULES})

REQUEST_CONTEXT = threading.local()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
        return parsed
    except Exception:
        return default


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized[:64] or f"perfil-{secrets.token_hex(3)}"


def install_profiles(ns: dict[str, Any]) -> None:
    db_connect = ns["db_connect"]
    utc_now = ns["utc_now"]
    local_today = ns["local_today"]
    ApiError = ns["ApiError"]
    Handler = ns["OneCRMHandler"]
    original_init_database = ns["init_database"]
    original_get_role_permissions = ns["get_role_permissions"]
    original_read_json = Handler.read_json
    original_route_get = Handler.route_get
    original_route_write = Handler.route_write
    original_dashboard = Handler.api_dashboard
    original_intelligence = Handler.api_intelligence
    original_sale_list = Handler.api_sales_list
    original_sale_detail = Handler.api_sale_detail
    original_sale_update = Handler.api_sale_update
    original_sale_workflow = Handler.api_sale_workflow
    original_api_user_update = Handler.api_user_update
    original_export_sales = Handler.api_export_sales
    original_trigger_webhook = Handler.trigger_webhook

    # Permissões novas são acrescentadas antes de init_database() chamar seed_database().
    extra_permissions = [
        ("profile.view", "Perfil", "Visualizar a identidade e os módulos do perfil atual"),
        ("plans.view", "Cadastros", "Visualizar planos e serviços"),
        ("catalogs.view", "Cadastros", "Visualizar opções e status"),
        ("roles.view", "Segurança", "Visualizar cargos e permissões"),
        ("integrations.view", "Sistema", "Visualizar o estado das integrações"),
        ("cash.view", "Caixa", "Visualizar lançamentos e saldo do caixa"),
        ("cash.manage", "Caixa", "Criar e editar lançamentos do caixa"),
    ]
    module_titles: dict[str, str] = {}
    for template in PROFILE_TEMPLATES.values():
        for module, config in template.get("records", {}).items():
            module_titles.setdefault(module, str(config.get("label") or module))
    for module in GENERIC_RECORD_MODULES:
        title = module_titles.get(module, module.replace("_", " ").title())
        extra_permissions.extend([
            (f"{module}.view", title, f"Visualizar {title.lower()}"),
            (f"{module}.manage", title, f"Criar e administrar {title.lower()}"),
        ])
    existing_permission_codes = {item[0] for item in ns["PERMISSIONS"]}
    ns["PERMISSIONS"].extend(item for item in extra_permissions if item[0] not in existing_permission_codes)

    def add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def ensure_profile_schema() -> None:
        now = utc_now()
        with db_connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    business_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    contractor_user_id INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    modules_json TEXT NOT NULL DEFAULT '[]',
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(contractor_user_id) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS profile_users (
                    profile_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_code TEXT NOT NULL,
                    team_id INTEGER,
                    is_contractor INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(profile_id,user_id),
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(role_code) REFERENCES roles(code) ON DELETE RESTRICT,
                    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS platform_roles (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    is_system INTEGER NOT NULL DEFAULT 0,
                    is_owner INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS platform_role_permissions (
                    role_code TEXT NOT NULL,
                    permission_code TEXT NOT NULL,
                    allowed INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY(role_code,permission_code),
                    FOREIGN KEY(role_code) REFERENCES platform_roles(code) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS profile_settings (
                    profile_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    secret INTEGER NOT NULL DEFAULT 0,
                    updated_by INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(profile_id,key),
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS cash_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('entry','exit')),
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount >= 0),
                    transaction_date TEXT NOT NULL,
                    payment_method TEXT,
                    notes TEXT,
                    created_by INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS profile_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    module_code TEXT NOT NULL,
                    title TEXT NOT NULL,
                    subtitle TEXT,
                    status TEXT,
                    amount REAL NOT NULL DEFAULT 0,
                    assigned_user_id INTEGER,
                    due_date TEXT,
                    notes TEXT,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    active INTEGER NOT NULL DEFAULT 1,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(assigned_user_id) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_profile_users_user ON profile_users(user_id,active);
                CREATE INDEX IF NOT EXISTS idx_profile_records_module ON profile_records(profile_id,module_code,active);
                CREATE INDEX IF NOT EXISTS idx_profile_records_due ON profile_records(profile_id,due_date);
                CREATE INDEX IF NOT EXISTS idx_cash_profile_date ON cash_transactions(profile_id,transaction_date);
                """
            )

            add_column(conn, "sessions", "active_profile_id", "INTEGER")
            add_column(conn, "teams", "profile_id", "INTEGER")
            add_column(conn, "roles", "profile_id", "INTEGER")
            add_column(conn, "catalog_items", "profile_id", "INTEGER")
            add_column(conn, "plans", "profile_id", "INTEGER")
            add_column(conn, "sales", "profile_id", "INTEGER")
            add_column(conn, "audit_logs", "profile_id", "INTEGER")
            add_column(conn, "ai_usage_logs", "profile_id", "INTEGER")
            add_column(conn, "users", "platform_role_code", "TEXT")

            conn.execute(
                """INSERT OR IGNORE INTO platform_roles
                   (code,name,description,is_system,is_owner,active,created_at,updated_at)
                   VALUES('owner','Dono da Plataforma','Acesso total à plataforma e a todos os perfis.',1,1,1,?,?)""",
                (now, now),
            )
            conn.execute(
                """INSERT OR IGNORE INTO platform_roles
                   (code,name,description,is_system,is_owner,active,created_at,updated_at)
                   VALUES('platform_admin','Administrador da Plataforma','Administra os perfis atribuídos, sem acesso à criação de Donos.',1,0,1,?,?)""",
                (now, now),
            )
            conn.execute("UPDATE users SET platform_role_code='owner' WHERE role_code='owner' AND COALESCE(platform_role_code,'')=''")
            for permission in PLATFORM_ROLE_DEFAULTS["platform_admin"]:
                conn.execute(
                    "INSERT OR IGNORE INTO platform_role_permissions(role_code,permission_code,allowed) VALUES('platform_admin',?,1)",
                    (permission,),
                )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_platform_role ON users(platform_role_code)")

            profile = conn.execute("SELECT id FROM business_profiles ORDER BY id LIMIT 1").fetchone()
            if profile:
                default_profile_id = int(profile[0])
            else:
                template = PROFILE_TEMPLATES["internet_sales"]
                cur = conn.execute(
                    """INSERT INTO business_profiles
                       (name,slug,business_type,description,active,modules_json,settings_json,created_at,updated_at)
                       VALUES(?,?,?,?,1,?,'{}',?,?)""",
                    (
                        "Operação principal",
                        "operacao-principal",
                        "internet_sales",
                        template["description"],
                        _json(template["modules"]),
                        now,
                        now,
                    ),
                )
                default_profile_id = int(cur.lastrowid)

            for table in ("teams", "catalog_items", "plans", "sales", "audit_logs", "ai_usage_logs"):
                conn.execute(f"UPDATE {table} SET profile_id=? WHERE profile_id IS NULL OR profile_id=0", (default_profile_id,))
            conn.execute("UPDATE roles SET profile_id=? WHERE is_system=0 AND profile_id IS NULL", (default_profile_id,))

            # Migra os usuários atuais para o perfil inicial. O Dono continua sendo global.
            users = conn.execute(
                "SELECT id,role_code,custom_role_code,team_id,active,created_at,updated_at FROM users"
            ).fetchall()
            for row in users:
                effective = row["custom_role_code"] or row["role_code"]
                conn.execute(
                    """INSERT OR IGNORE INTO profile_users
                       (profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,?,?,0,?,?,?)""",
                    (
                        default_profile_id,
                        row["id"],
                        effective,
                        row["team_id"],
                        row["active"],
                        row["created_at"] or now,
                        row["updated_at"] or now,
                    ),
                )

            conn.execute(
                "UPDATE sessions SET active_profile_id=? WHERE active_profile_id IS NULL",
                (default_profile_id,),
            )

            # Configurações antigas passam a pertencer ao perfil inicial.
            settings = conn.execute("SELECT key,value,secret,updated_by,updated_at FROM system_settings").fetchall()
            for row in settings:
                conn.execute(
                    """INSERT OR IGNORE INTO profile_settings(profile_id,key,value,secret,updated_by,updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    (default_profile_id, row["key"], row["value"], row["secret"], row["updated_by"], row["updated_at"]),
                )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_profile ON sales(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_teams_profile ON teams(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_profile ON plans(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_profile ON catalog_items(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_roles_profile ON roles(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_profile ON audit_logs(profile_id)")

            # Permissão legada removida: desde a 2.0.1 somente o Dono da
            # Plataforma pode alterar a identidade e os módulos de um perfil.
            conn.execute("DELETE FROM role_permissions WHERE permission_code='profile.configure'")
            conn.execute("DELETE FROM permissions WHERE code='profile.configure'")

    def init_database() -> None:
        original_init_database()
        ensure_profile_schema()

    ns["init_database"] = init_database

    def is_platform_owner(user: dict[str, Any] | None) -> bool:
        return bool(user and (user.get("platform_role_code") == "owner" or user.get("role_code") == "owner"))

    def platform_role_data(conn: sqlite3.Connection, user_id: int, legacy_role_code: str | None = None) -> tuple[dict[str, Any] | None, set[str]]:
        row = conn.execute(
            """SELECT pr.* FROM users u
               LEFT JOIN platform_roles pr ON pr.code=COALESCE(u.platform_role_code,CASE WHEN u.role_code='owner' THEN 'owner' END)
               WHERE u.id=?""",
            (user_id,),
        ).fetchone()
        if not row and legacy_role_code == "owner":
            row = conn.execute("SELECT * FROM platform_roles WHERE code='owner'").fetchone()
        if not row:
            return None, set()
        role = dict(row)
        permissions = {
            str(item[0]) for item in conn.execute(
                "SELECT permission_code FROM platform_role_permissions WHERE role_code=? AND allowed=1",
                (role["code"],),
            ).fetchall()
        }
        return role, permissions

    def platform_profile_permissions(platform_permissions: set[str]) -> set[str]:
        all_codes = {code for code, _, _ in ns["PERMISSIONS"]}
        result: set[str] = set()
        if "platform.profile.read" in platform_permissions:
            result.update(code for code in all_codes if code.endswith(".view"))
            result.update({"sales.all", "ranking.all", "daily.view", "profile.view"} & all_codes)
        if "platform.profile.manage" in platform_permissions:
            excluded_prefixes = ("users.", "teams.", "roles.", "integrations.", "audit.", "backups.")
            result.update(code for code in all_codes if not code.startswith(excluded_prefixes))
        if "platform.people.manage" in platform_permissions:
            result.update({"users.view", "users.manage", "teams.view", "teams.manage"} & all_codes)
        if "platform.security.manage" in platform_permissions:
            result.update({"roles.view", "roles.manage", "catalogs.view", "catalogs.manage", "plans.view", "plans.manage"} & all_codes)
        if "platform.integrations.manage" in platform_permissions:
            result.update({"integrations.view", "integrations.manage"} & all_codes)
        if "platform.audit.view" in platform_permissions:
            result.add("audit.view")
        if "platform.backups.manage" in platform_permissions:
            result.add("backups.manage")
        return result & all_codes

    def current_profile_id(user: dict[str, Any] | None) -> int:
        try:
            return int((user or {}).get("profile_id") or 0)
        except Exception:
            return 0

    def get_profile(profile_id: int) -> dict[str, Any] | None:
        if not profile_id:
            return None
        with db_connect() as conn:
            row = conn.execute(
                "SELECT * FROM business_profiles WHERE id=?",
                (profile_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["modules"] = _parse_json(result.pop("modules_json", "[]"), [])
        result["settings"] = _parse_json(result.pop("settings_json", "{}"), {})
        return result

    def accessible_profiles(user_id: int, owner: bool = False) -> list[dict[str, Any]]:
        with db_connect() as conn:
            if owner:
                rows = conn.execute(
                    """SELECT p.*,u.name AS contractor_name,
                       (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=p.id AND pu.active=1) AS users_count
                       FROM business_profiles p
                       LEFT JOIN users u ON u.id=p.contractor_user_id
                       ORDER BY p.active DESC,p.name"""
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT p.*,u.name AS contractor_name,
                       (SELECT COUNT(*) FROM profile_users x WHERE x.profile_id=p.id AND x.active=1) AS users_count
                       FROM profile_users pu
                       JOIN business_profiles p ON p.id=pu.profile_id
                       LEFT JOIN users u ON u.id=p.contractor_user_id
                       WHERE pu.user_id=? AND pu.active=1 AND p.active=1
                       ORDER BY p.name""",
                    (user_id,),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["modules"] = _parse_json(item.pop("modules_json", "[]"), [])
            item["settings"] = _parse_json(item.pop("settings_json", "{}"), {})
            item["active"] = bool(item["active"])
            result.append(item)
        return result

    def choose_profile_for_user(conn: sqlite3.Connection, user_id: int, owner: bool, requested: int | None = None) -> int | None:
        if requested:
            if owner:
                row = conn.execute("SELECT id FROM business_profiles WHERE id=? AND active=1", (requested,)).fetchone()
            else:
                row = conn.execute(
                    """SELECT p.id FROM business_profiles p JOIN profile_users pu ON pu.profile_id=p.id
                       WHERE p.id=? AND p.active=1 AND pu.user_id=? AND pu.active=1""",
                    (requested, user_id),
                ).fetchone()
            if row:
                return int(row[0])
        if owner:
            row = conn.execute("SELECT id FROM business_profiles WHERE active=1 ORDER BY id LIMIT 1").fetchone()
        else:
            row = conn.execute(
                """SELECT p.id FROM business_profiles p JOIN profile_users pu ON pu.profile_id=p.id
                   WHERE pu.user_id=? AND pu.active=1 AND p.active=1 ORDER BY p.id LIMIT 1""",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else None

    def create_session(user_id: int, hours: int) -> tuple[str, str]:
        raw = secrets.token_urlsafe(40)
        csrf = secrets.token_urlsafe(28)
        expires = (ns["datetime"].now() + ns["timedelta"](hours=hours)).replace(microsecond=0).isoformat()
        with db_connect() as conn:
            row = conn.execute("SELECT role_code FROM users WHERE id=?", (user_id,)).fetchone()
            owner = bool(row and row["role_code"] == "owner")
            profile_id = choose_profile_for_user(conn, user_id, owner)
            if not profile_id:
                raise ApiError(403, "Este usuário não está vinculado a nenhum perfil ativo.")
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (utc_now(),))
            conn.execute(
                """INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at,active_profile_id)
                   VALUES(?,?,?,?,?,?)""",
                (ns["token_hash"](raw), user_id, csrf, expires, utc_now(), profile_id),
            )
        return raw, csrf

    ns["create_session"] = create_session

    def get_user_by_session(raw_token: str | None) -> tuple[dict[str, Any] | None, str | None]:
        if not raw_token:
            return None, None
        with db_connect() as conn:
            session = conn.execute(
                """SELECT s.*,u.* FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
                (ns["token_hash"](raw_token), utc_now()),
            ).fetchone()
            if not session:
                return None, None
            data = dict(session)
            platform_role, platform_permissions = platform_role_data(conn, int(data["user_id"]), data.get("role_code"))
            platform_code = str((platform_role or {}).get("code") or data.get("platform_role_code") or ("owner" if data.get("role_code") == "owner" else ""))
            owner = platform_code == "owner" or data["role_code"] == "owner"
            profile_id = choose_profile_for_user(conn, data["user_id"], owner, data.get("active_profile_id"))
            if not profile_id:
                return None, None
            if profile_id != data.get("active_profile_id"):
                conn.execute(
                    "UPDATE sessions SET active_profile_id=? WHERE token_hash=?",
                    (profile_id, ns["token_hash"](raw_token)),
                )
            ensure_profile_preset(conn, profile_id)
            profile = conn.execute("SELECT * FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
            membership = conn.execute(
                """SELECT pu.*,r.name AS membership_role_name,r.base_role AS membership_base_role,t.name AS membership_team_name
                   FROM profile_users pu
                   LEFT JOIN roles r ON r.code=pu.role_code
                   LEFT JOIN teams t ON t.id=pu.team_id AND t.profile_id=pu.profile_id
                   WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                (profile_id, data["user_id"]),
            ).fetchone()
            if not owner and not membership:
                return None, None

        user = {key: data[key] for key in data.keys() if key not in {"token_hash", "csrf_token", "expires_at", "created_at", "active_profile_id", "user_id"}}
        user["id"] = data["user_id"]
        user["platform_role_code"] = platform_code or None
        user["platform_role_name"] = (platform_role or {}).get("name")
        user["platform_permissions"] = sorted(platform_permissions)
        user["is_platform_staff"] = bool(platform_code)
        if owner:
            user["role_code"] = "owner"
            user["effective_role_code"] = "owner"
            user["role_name"] = "Dono"
            user["team_id"] = membership["team_id"] if membership else None
            user["team_name"] = membership["membership_team_name"] if membership else None
            user["is_contractor"] = False
            user["permissions"] = sorted(code for code, _, _ in ns["PERMISSIONS"])
        else:
            member = dict(membership)
            effective = member["role_code"]
            base = member.get("membership_base_role") or "seller"
            user["role_code"] = base
            user["effective_role_code"] = effective
            user["role_name"] = member.get("membership_role_name") or effective
            user["team_id"] = member.get("team_id")
            user["team_name"] = member.get("membership_team_name")
            user["is_contractor"] = bool(member.get("is_contractor"))
            if user["is_contractor"]:
                permissions = set(PROFILE_CONTRACTOR_PERMISSIONS)
                user["role_name"] = "Contratante"
            else:
                permissions = set(original_get_role_permissions(effective))
            if platform_code:
                permissions.update(platform_profile_permissions(platform_permissions))
                user["role_name"] = (platform_role or {}).get("name") or user["role_name"]
                user["is_contractor"] = False
            user["permissions"] = sorted(permissions)
        profile_dict = dict(profile)
        user["profile_id"] = profile_id
        user["profile_name"] = profile_dict["name"]
        user["profile_type"] = profile_dict["business_type"]
        user["profile_modules"] = _parse_json(profile_dict["modules_json"], [])
        user["profile_settings"] = _parse_json(profile_dict["settings_json"], {})
        user["profile_active"] = bool(profile_dict["active"])
        return user, data["csrf_token"]

    ns["get_user_by_session"] = get_user_by_session

    def effective_role_code(user: dict[str, Any] | sqlite3.Row | None) -> str:
        if not user:
            return "seller"
        if isinstance(user, dict):
            return str(user.get("effective_role_code") or user.get("membership_role_code") or user.get("custom_role_code") or user.get("role_code") or "seller")
        keys = user.keys()
        for key in ("effective_role_code", "membership_role_code", "custom_role_code", "role_code"):
            if key in keys and user[key]:
                return str(user[key])
        return "seller"

    ns["effective_role_code"] = effective_role_code

    permission_modules = {
        "dashboard.view": "dashboard",
        "sales.own": "sales", "sales.all": "sales", "sales.create": "sales",
        "sales.edit_own": "sales", "sales.edit_all": "sales",
        "workflow.bko": "bko", "workflow.assign": "bko",
        "ranking.own": "ranking", "ranking.all": "ranking",
        "daily.view": "daily", "users.view": "users", "users.manage": "users",
        "teams.view": "teams", "teams.manage": "teams",
        "catalogs.view": "catalogs", "catalogs.manage": "catalogs",
        "roles.view": "roles", "roles.manage": "roles", "audit.view": "audit",
        "intelligence.view": "intelligence", "ai.use": "intelligence",
        "powerbi.view": "powerbi",
        "integrations.view": "integrations", "integrations.manage": "integrations",
        "profile.view": "users",
        "cash.view": "cash", "cash.manage": "cash",
    }
    for module in GENERIC_RECORD_MODULES:
        permission_modules[f"{module}.view"] = module
        permission_modules[f"{module}.manage"] = module

    def has_permission(user: dict[str, Any] | None, code: str) -> bool:
        if not user:
            return False
        if is_platform_owner(user):
            return True
        modules = set(user.get("profile_modules") or [])
        if code in {"plans.view", "plans.manage"}:
            if not ({"plans", "services_catalog"} & modules):
                return False
        required_module = permission_modules.get(code)
        if required_module and required_module not in modules:
            return False
        if user.get("is_contractor") and code in PROFILE_CONTRACTOR_PERMISSIONS:
            return True
        return code in set(user.get("permissions", []))

    ns["has_permission"] = has_permission

    def sale_scope_sql(user: dict[str, Any], alias: str = "s") -> tuple[str, list[Any]]:
        pid = current_profile_id(user)
        if not pid:
            return "0=1", []
        prefix = f"{alias}.profile_id=?"
        if has_permission(user, "sales.all"):
            return prefix, [pid]
        if user.get("role_code") == "bko":
            return (
                f"{prefix} AND ({alias}.bko_user_id=? OR ({alias}.bko_user_id IS NULL AND {alias}.status IN ('nova','em_tratamento')))",
                [pid, user["id"]],
            )
        return f"{prefix} AND {alias}.seller_id=?", [pid, user["id"]]

    ns["sale_scope_sql"] = sale_scope_sql

    def can_access_sale(user: dict[str, Any], sale: dict[str, Any]) -> bool:
        if int(sale.get("profile_id") or 0) != current_profile_id(user):
            return False
        if has_permission(user, "sales.all"):
            return True
        if user.get("role_code") == "bko":
            return sale.get("bko_user_id") in (None, user["id"])
        return sale.get("seller_id") == user["id"]

    ns["can_access_sale"] = can_access_sale

    original_audit = ns["audit"]

    def audit(user_id: int | None, action: str, entity_type: str | None = None,
              entity_id: str | int | None = None, details: Any = None, ip: str | None = None) -> None:
        profile_id = getattr(REQUEST_CONTEXT, "profile_id", None)
        detail_text = details if isinstance(details, str) else ns["json_dumps"](details or {})
        with db_connect() as conn:
            conn.execute(
                """INSERT INTO audit_logs(profile_id,user_id,action,entity_type,entity_id,details,ip_address,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (profile_id, user_id, action, entity_type, str(entity_id) if entity_id is not None else None, detail_text, ip, utc_now()),
            )

    ns["audit"] = audit

    def read_json_cached(self: Any) -> dict[str, Any]:
        if hasattr(self, "_onecrm_json_cache"):
            return self._onecrm_json_cache
        value = original_read_json(self)
        self._onecrm_json_cache = value
        return value

    Handler.read_json = read_json_cached

    original_require_user = Handler.require_user

    def require_user(self: Any) -> tuple[dict[str, Any], str, str]:
        user, csrf, raw = original_require_user(self)
        REQUEST_CONTEXT.profile_id = current_profile_id(user)
        return user, csrf, raw

    Handler.require_user = require_user

    def public_user(self: Any, user: dict[str, Any]) -> dict[str, Any]:
        owner = is_platform_owner(user)
        with db_connect() as conn:
            profile_ids = [int(row[0]) for row in conn.execute("SELECT id FROM business_profiles").fetchall()]
            for profile_id in profile_ids:
                ensure_profile_preset(conn, profile_id)
        profiles = accessible_profiles(user["id"], owner)
        profile = {
            "id": user.get("profile_id"),
            "name": user.get("profile_name"),
            "business_type": user.get("profile_type"),
            "modules": user.get("profile_modules", []),
            "settings": user.get("profile_settings", {}),
            "preset": public_template(str(user.get("profile_type") or "custom")),
            "active": bool(user.get("profile_active", True)),
        }
        return {
            "id": user["id"],
            "name": user["name"],
            "display_name": user.get("display_name") or user["name"],
            "email": user["email"],
            "phone": user.get("phone") or "",
            "bio": user.get("bio") or "",
            "theme_preference": user.get("theme_preference") or "dark",
            "accent_preference": user.get("accent_preference") or "emerald",
            "background_preference": user.get("background_preference") or "graphite",
            "role_code": user.get("effective_role_code") or user.get("role_code"),
            "base_role": user.get("role_code"),
            "role_name": "Dono da Plataforma" if owner else (user.get("role_name") or "Usuário"),
            "team_id": user.get("team_id"),
            "team_name": user.get("team_name"),
            "permissions": user.get("permissions", []),
            "must_change_password": bool(user.get("must_change_password")),
            "is_platform_owner": owner,
            "is_platform_staff": bool(user.get("is_platform_staff")),
            "platform_role_code": user.get("platform_role_code"),
            "platform_role_name": user.get("platform_role_name"),
            "platform_permissions": user.get("platform_permissions", []),
            "is_contractor": bool(user.get("is_contractor")),
            "profile": profile,
            "profiles": profiles,
        }

    Handler.public_user = public_user

    # ------------------------- perfis -------------------------
    def normalize_modules(business_type: str, modules: Any) -> list[str]:
        allowed = {
            "dashboard", "sales", "bko", "daily", "ranking", "intelligence",
            "powerbi", "users", "teams", "plans", "services_catalog",
            "catalogs", "roles", "audit", "integrations", "cash",
            *GENERIC_RECORD_MODULES,
        }
        if not isinstance(modules, list):
            modules = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["services"])["modules"]
        result = [str(item) for item in modules if str(item) in allowed]
        if "dashboard" not in result:
            result.insert(0, "dashboard")
        for essential in ("users", "roles"):
            if essential not in result:
                result.append(essential)
        return list(dict.fromkeys(result))

    def public_template(business_type: str) -> dict[str, Any]:
        template = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["custom"])
        return {
            "code": business_type,
            "name": template.get("name", business_type),
            "category": template.get("category", "Perfil"),
            "description": template.get("description", ""),
            "recommended_for": template.get("recommended_for", ""),
            "operation_group_label": template.get("operation_group_label", "Operação"),
            "modules": list(template.get("modules", [])),
            "navigation_labels": dict(template.get("navigation_labels", {})),
            "admin_labels": dict(template.get("admin_labels", {})),
            "catalog_labels": dict(template.get("catalog_labels", {})),
            "records": dict(template.get("records", {})),
            "roles": [{"name": role.get("name"), "description": role.get("description"), "base_role": role.get("base_role")} for role in template.get("roles", [])],
            "catalogs": [{"category": category, "label": template.get("catalog_labels", {}).get(category, category), "items": [item[1] for item in items]} for category, items in template.get("catalogs", {}).items()],
            "offerings": [{"name": item.get("name"), "service": item.get("service")} for item in template.get("offerings", [])],
            "roles_count": len(template.get("roles", [])),
            "catalogs_count": sum(len(items) for items in template.get("catalogs", {}).values()),
            "offerings_count": len(template.get("offerings", [])),
        }

    def unique_role_name(conn: sqlite3.Connection, profile_id: int, desired: str) -> str:
        row = conn.execute("SELECT code,profile_id FROM roles WHERE name=? COLLATE NOCASE", (desired,)).fetchone()
        if not row or int(row["profile_id"] or 0) == profile_id:
            return desired
        profile = conn.execute("SELECT name FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
        suffix = str(profile["name"] if profile else f"Perfil {profile_id}")[:40]
        return f"{desired} · {suffix}"

    def seed_profile(conn: sqlite3.Connection, profile_id: int, business_type: str) -> None:
        now = utc_now()
        template = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["custom"])

        # O perfil de internet reaproveita os cadastros da operação original.
        if business_type == "internet_sales":
            source_profile = conn.execute(
                "SELECT id FROM business_profiles WHERE id<>? AND business_type='internet_sales' ORDER BY id LIMIT 1",
                (profile_id,),
            ).fetchone()
            if source_profile:
                source_id = int(source_profile[0])
                plan_count = conn.execute("SELECT COUNT(*) FROM plans WHERE profile_id=?", (profile_id,)).fetchone()[0]
                if not plan_count:
                    conn.execute(
                        """INSERT INTO plans(profile_id,provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                           SELECT ?,provider,service,name,speed,price,benefits,uf_list,sort_order,active,?,? FROM plans WHERE profile_id=?""",
                        (profile_id, now, now, source_id),
                    )
                cat_count = conn.execute("SELECT COUNT(*) FROM catalog_items WHERE profile_id=?", (profile_id,)).fetchone()[0]
                if not cat_count:
                    rows = conn.execute(
                        "SELECT category,code,label,sort_order,active,metadata_json FROM catalog_items WHERE profile_id=?",
                        (source_id,),
                    ).fetchall()
                    for row in rows:
                        code = f"p{profile_id}_{re.sub(r'[^a-z0-9_]+', '_', str(row['code']).lower()).strip('_')}"
                        conn.execute(
                            """INSERT OR IGNORE INTO catalog_items
                               (profile_id,category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (profile_id, row["category"], code, row["label"], row["sort_order"], row["active"], row["metadata_json"], now, now),
                        )

        # Cargos iniciais do segmento.
        for role in template.get("roles", []):
            raw_code = re.sub(r"[^a-z0-9_]+", "_", str(role.get("code") or role.get("name") or "cargo").lower()).strip("_")
            role_code = f"p{profile_id}_{raw_code}"[:64]
            stored_name = unique_role_name(conn, profile_id, str(role.get("name") or raw_code.replace("_", " ").title()))
            conn.execute(
                """INSERT OR IGNORE INTO roles
                   (code,name,description,base_role,is_system,active,created_at,updated_at,profile_id)
                   VALUES(?,?,?,?,0,1,?,?,?)""",
                (role_code, stored_name, str(role.get("description") or ""), str(role.get("base_role") or "seller"), now, now, profile_id),
            )
            conn.execute(
                """UPDATE roles SET description=?,base_role=?,active=1,updated_at=?,profile_id=? WHERE code=?""",
                (str(role.get("description") or ""), str(role.get("base_role") or "seller"), now, profile_id, role_code),
            )
            for permission in role.get("permissions", []):
                if conn.execute("SELECT 1 FROM permissions WHERE code=?", (permission,)).fetchone():
                    conn.execute(
                        "INSERT OR REPLACE INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                        (role_code, permission),
                    )

        # Catálogos próprios do preset.
        for category, items in template.get("catalogs", {}).items():
            for order, item in enumerate(items, 1):
                raw_code, label = item[0], item[1]
                existing = conn.execute(
                    "SELECT id FROM catalog_items WHERE profile_id=? AND category=? AND label=? COLLATE NOCASE",
                    (profile_id, category, label),
                ).fetchone()
                if existing:
                    continue
                clean_code = re.sub(r"[^a-z0-9_]+", "_", str(raw_code).lower()).strip("_")
                stored_code = f"p{profile_id}_{clean_code}"[:80]
                conn.execute(
                    """INSERT OR IGNORE INTO catalog_items
                       (profile_id,category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                       VALUES(?,?,?,?,?,1,'{}',?,?)""",
                    (profile_id, category, stored_code, label, order, now, now),
                )

        # Produtos, planos ou serviços recomendados pelo segmento.
        for order, item in enumerate(template.get("offerings", []), 1):
            name = str(item.get("name") or "Serviço")
            if conn.execute("SELECT 1 FROM plans WHERE profile_id=? AND name=? COLLATE NOCASE", (profile_id, name)).fetchone():
                continue
            conn.execute(
                """INSERT INTO plans(profile_id,provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                (profile_id, str(item.get("provider") or ""), str(item.get("service") or ""), name,
                 str(item.get("speed") or ""), float(item.get("price") or 0), str(item.get("benefits") or ""),
                 str(item.get("uf_list") or ""), order * 10, now, now),
            )

    def ensure_profile_preset(conn: sqlite3.Connection, profile_id: int) -> None:
        row = conn.execute("SELECT business_type,modules_json,settings_json FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
        if not row:
            return
        business_type = str(row["business_type"] or "custom")
        template = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["custom"])
        settings = _parse_json(row["settings_json"], {})
        current_version = int(settings.get("preset_schema_version") or 0)
        if current_version < PRESET_SCHEMA_VERSION:
            settings["preset_schema_version"] = PRESET_SCHEMA_VERSION
            settings["preset_name"] = template.get("name", business_type)
            settings["preset_category"] = template.get("category", "Perfil")
            # Perfis anteriores à 2.2 recebiam módulos comerciais genéricos.
            # Agora cada preset passa a ter somente as abas do próprio segmento.
            modules = normalize_modules(business_type, template.get("modules", [])) if business_type != "custom" else normalize_modules(business_type, _parse_json(row["modules_json"], []))
            conn.execute(
                "UPDATE business_profiles SET modules_json=?,settings_json=?,updated_at=? WHERE id=?",
                (_json(modules), _json(settings), utc_now(), profile_id),
            )
        seed_profile(conn, profile_id, business_type)

    def api_profiles(self: Any) -> None:
        user, _, _ = self.require_user()
        owner = is_platform_owner(user)
        profiles = accessible_profiles(user["id"], owner)
        if not owner:
            profiles = [item for item in profiles if item["id"] == current_profile_id(user)]
        candidates = []
        if owner:
            with db_connect() as conn:
                candidates = [dict(row) for row in conn.execute(
                    "SELECT id,name,email FROM users WHERE active=1 AND role_code<>'owner' AND COALESCE(platform_role_code,'')='' ORDER BY name"
                ).fetchall()]
        self.send_json(200, {
            "ok": True,
            "profiles": profiles,
            "templates": [public_template(code) for code in PROFILE_TEMPLATES],
            "available_contractors": candidates,
        })

    def api_profile_create(self: Any, actor: dict[str, Any]) -> None:
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da plataforma pode criar perfis.")
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        business_type = str(data.get("business_type") or "internet_sales").strip()
        description = str(data.get("description") or "").strip()[:600]
        contractor_user_id = int(data.get("contractor_user_id") or 0) or None
        if len(name) < 3:
            raise ApiError(400, "Informe um nome de perfil com pelo menos 3 caracteres.")
        if business_type not in PROFILE_TEMPLATES:
            raise ApiError(400, "Modelo de negócio inválido.")
        modules = normalize_modules(business_type, data.get("modules"))
        slug = _slug(data.get("slug") or name)
        now = utc_now()
        with db_connect() as conn:
            base_slug = slug
            suffix = 2
            while conn.execute("SELECT 1 FROM business_profiles WHERE slug=?", (slug,)).fetchone():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            if contractor_user_id and not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (contractor_user_id,)).fetchone():
                raise ApiError(400, "Contratante inválido ou inativo.")
            cur = conn.execute(
                """INSERT INTO business_profiles
                   (name,slug,business_type,description,contractor_user_id,active,modules_json,settings_json,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,?,?,?,?,?)""",
                (name, slug, business_type, description or PROFILE_TEMPLATES[business_type]["description"], contractor_user_id,
                 _json(modules), _json({"preset_schema_version": PRESET_SCHEMA_VERSION, "preset_name": PROFILE_TEMPLATES[business_type]["name"]}), actor["id"], now, now),
            )
            profile_id = int(cur.lastrowid)
            seed_profile(conn, profile_id, business_type)
            if contractor_user_id:
                conn.execute(
                    """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,'manager',NULL,1,1,?,?)
                       ON CONFLICT(profile_id,user_id) DO UPDATE SET role_code='manager',is_contractor=1,active=1,updated_at=excluded.updated_at""",
                    (profile_id, contractor_user_id, now, now),
                )
                conn.execute(
                    "UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?",
                    (now, contractor_user_id, profile_id),
                )
        audit(actor["id"], "profile.create", "profile", profile_id, {"name": name, "business_type": business_type}, self.client_ip())
        self.send_json(201, {"ok": True, "id": profile_id, "message": "Perfil criado."})

    def api_profile_update_business(self: Any, actor: dict[str, Any], profile_id: int) -> None:
        owner = is_platform_owner(actor)
        if not owner:
            raise ApiError(403, "Apenas o Dono da Plataforma pode configurar perfis.")
        data = self.read_json()
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
            if not current:
                raise ApiError(404, "Perfil não encontrado.")
            updates: dict[str, Any] = {}
            if "name" in data:
                name = str(data.get("name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome do perfil inválido.")
                updates["name"] = name
            if "description" in data:
                updates["description"] = str(data.get("description") or "").strip()[:600]
            business_type = current["business_type"]
            if owner and "business_type" in data:
                business_type = str(data.get("business_type") or "").strip()
                if business_type not in PROFILE_TEMPLATES:
                    raise ApiError(400, "Modelo de negócio inválido.")
                updates["business_type"] = business_type
            if "modules" in data:
                updates["modules_json"] = _json(normalize_modules(business_type, data.get("modules")))
            if "settings" in data:
                settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
                updates["settings_json"] = _json(settings)
            if owner and "active" in data:
                updates["active"] = 1 if bool(data.get("active")) else 0
            contractor_id = None
            if owner and "contractor_user_id" in data:
                contractor_id = int(data.get("contractor_user_id") or 0) or None
                if contractor_id and not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (contractor_id,)).fetchone():
                    raise ApiError(400, "Contratante inválido.")
                updates["contractor_user_id"] = contractor_id
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            updates["updated_at"] = utc_now()
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE business_profiles SET {assignments} WHERE id=?", [*updates.values(), profile_id])
            if "business_type" in updates:
                settings = _parse_json(current["settings_json"], {})
                settings.update({"preset_schema_version": PRESET_SCHEMA_VERSION, "preset_name": PROFILE_TEMPLATES[business_type]["name"]})
                conn.execute("UPDATE business_profiles SET modules_json=?,settings_json=?,updated_at=? WHERE id=?",
                             (_json(normalize_modules(business_type, PROFILE_TEMPLATES[business_type]["modules"])), _json(settings), utc_now(), profile_id))
                seed_profile(conn, profile_id, business_type)
            if owner and "contractor_user_id" in data:
                conn.execute("UPDATE profile_users SET is_contractor=0,updated_at=? WHERE profile_id=?", (utc_now(), profile_id))
                if contractor_id:
                    conn.execute(
                        """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                           VALUES(?,?,'manager',NULL,1,1,?,?)
                           ON CONFLICT(profile_id,user_id) DO UPDATE SET role_code='manager',is_contractor=1,active=1,updated_at=excluded.updated_at""",
                        (profile_id, contractor_id, utc_now(), utc_now()),
                    )
                    conn.execute(
                        "UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?",
                        (utc_now(), contractor_id, profile_id),
                    )
        audit(actor["id"], "profile.update", "profile", profile_id, {"fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Perfil atualizado."})

    def api_profile_switch(self: Any, actor: dict[str, Any]) -> None:
        data = self.read_json()
        profile_id = int(data.get("profile_id") or 0)
        if not profile_id:
            raise ApiError(400, "Perfil inválido.")
        raw = self.parse_cookie(ns["COOKIE_NAME"])
        if not raw:
            raise ApiError(401, "Sessão expirada.")
        with db_connect() as conn:
            selected = choose_profile_for_user(conn, actor["id"], is_platform_owner(actor), profile_id)
            if selected != profile_id:
                raise ApiError(403, "Você não possui acesso a este perfil.")
            conn.execute(
                "UPDATE sessions SET active_profile_id=? WHERE token_hash=?",
                (profile_id, ns["token_hash"](raw)),
            )
        audit(actor["id"], "profile.switch", "profile", profile_id, {}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Perfil alterado."})

    # ------------------------- usuários do perfil -------------------------
    def role_allowed_in_profile(conn: sqlite3.Connection, profile_id: int, role_code: str) -> sqlite3.Row | None:
        role = conn.execute(
            """SELECT * FROM roles WHERE code=? AND active=1 AND profile_id=?""",
            (role_code, profile_id),
        ).fetchone()
        if role:
            return role
        # Compatibilidade com a operação original: cargos nativos ainda podem
        # existir em perfis de venda de internet, embora não apareçam como
        # opções dos novos presets nem na tela de cargos.
        profile = conn.execute("SELECT business_type FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
        if profile and profile["business_type"] == "internet_sales":
            return conn.execute(
                "SELECT * FROM roles WHERE code=? AND active=1 AND is_system=1 AND code IN ('manager','bko','seller')",
                (role_code,),
            ).fetchone()
        return None

    def api_users_list(self: Any) -> None:
        actor = self.require_permission("users.view")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT u.id,u.name,u.email,pu.role_code,r.base_role,
                   COALESCE(pr.name,r.name) AS role_name,u.platform_role_code,pr.name AS platform_role_name,
                   pu.team_id,pu.is_contractor,pu.active,u.must_change_password,u.last_login_at,u.created_at,
                   t.name AS team_name
                   FROM profile_users pu JOIN users u ON u.id=pu.user_id
                   LEFT JOIN roles r ON r.code=pu.role_code
                   LEFT JOIN platform_roles pr ON pr.code=u.platform_role_code
                   LEFT JOIN teams t ON t.id=pu.team_id AND t.profile_id=pu.profile_id
                   WHERE pu.profile_id=?
                   ORDER BY pu.active DESC,pu.is_contractor DESC,u.name""",
                (pid,),
            ).fetchall()
        users = [dict(row) for row in rows]
        self.send_json(200, {"ok": True, "users": users})

    def api_user_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "users.manage"):
            raise ApiError(403, "Sem permissão para administrar usuários neste perfil.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        email = ns["normalize_email"](data.get("email") or "")
        role_code = str(data.get("role_code") or "seller").strip()
        team_id = int(data.get("team_id") or 0) or None
        password = str(data.get("password") or "")
        make_contractor = bool(data.get("is_contractor")) and is_platform_owner(actor)
        if len(name) < 3 or "@" not in email:
            raise ApiError(400, "Nome ou e-mail inválido.")
        with db_connect() as conn:
            role = role_allowed_in_profile(conn, pid, role_code)
            if not role:
                raise ApiError(400, "Cargo inválido para este perfil.")
            if role["base_role"] == "owner" and not is_platform_owner(actor):
                raise ApiError(403, "Somente o Dono da plataforma pode nomear outro Dono.")
            if team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND profile_id=? AND active=1", (team_id, pid)).fetchone():
                raise ApiError(400, "Equipe inválida.")
            existing = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            now = utc_now()
            if existing:
                user_id = int(existing["id"])
                if existing["role_code"] == "owner" and role["base_role"] != "owner":
                    raise ApiError(400, "A conta de Dono da plataforma não pode ser vinculada como funcionário comum.")
            else:
                error = ns["validate_password"](password)
                if error:
                    raise ApiError(400, error)
                cur = conn.execute(
                    """INSERT INTO users(name,email,password_hash,role_code,custom_role_code,team_id,active,must_change_password,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,1,?,?,?)""",
                    (name, email, ns["hash_password"](password), role["base_role"], None if role["base_role"] == "owner" or role_code == role["base_role"] else role_code,
                     team_id, 1 if data.get("must_change_password", True) else 0, now, now),
                )
                user_id = int(cur.lastrowid)
            try:
                conn.execute(
                    """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,?,?,?,1,?,?)""",
                    (pid, user_id, role_code, team_id, 1 if make_contractor else 0, now, now),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Este usuário já pertence ao perfil atual.")
            if make_contractor:
                conn.execute("UPDATE profile_users SET is_contractor=0 WHERE profile_id=? AND user_id<>?", (pid, user_id))
                conn.execute("UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?", (now, user_id, pid))
                conn.execute("UPDATE business_profiles SET contractor_user_id=?,updated_at=? WHERE id=?", (user_id, now, pid))
        audit(actor["id"], "profile_user.create", "user", user_id, {"profile_id": pid, "role": role_code}, self.client_ip())
        self.send_json(201, {"ok": True, "id": user_id, "message": "Usuário vinculado ao perfil."})

    def api_user_update(self: Any, actor: dict[str, Any], user_id: int) -> None:
        if not has_permission(actor, "users.manage"):
            raise ApiError(403, "Sem permissão para administrar usuários neste perfil.")
        pid = current_profile_id(actor)
        data = self.read_json()
        if is_platform_owner(actor):
            with db_connect() as owner_conn:
                global_target = owner_conn.execute("SELECT role_code FROM users WHERE id=?", (user_id,)).fetchone()
            if global_target and global_target["role_code"] == "owner":
                return original_api_user_update(self, actor, user_id)
        with db_connect() as conn:
            target = conn.execute(
                """SELECT u.*,pu.role_code AS membership_role,pu.team_id AS membership_team,
                   pu.active AS membership_active,pu.is_contractor
                   FROM users u JOIN profile_users pu ON pu.user_id=u.id
                   WHERE u.id=? AND pu.profile_id=?""",
                (user_id, pid),
            ).fetchone()
            if not target:
                raise ApiError(404, "Usuário não encontrado neste perfil.")
            if target["role_code"] == "owner":
                raise ApiError(403, "A conta de Dono da plataforma não pode ser alterada por um perfil.")
            user_updates: dict[str, Any] = {}
            member_updates: dict[str, Any] = {}
            if "name" in data:
                name = str(data.get("name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome inválido.")
                user_updates["name"] = name
            if "email" in data:
                email = ns["normalize_email"](data.get("email") or "")
                if "@" not in email:
                    raise ApiError(400, "E-mail inválido.")
                user_updates["email"] = email
            if data.get("password"):
                error = ns["validate_password"](data["password"])
                if error:
                    raise ApiError(400, error)
                user_updates["password_hash"] = ns["hash_password"](data["password"])
                user_updates["must_change_password"] = 1 if data.get("must_change_password", True) else 0
            if "role_code" in data:
                role_code = str(data.get("role_code") or "").strip()
                role = role_allowed_in_profile(conn, pid, role_code)
                if not role or role["base_role"] == "owner":
                    raise ApiError(400, "Cargo inválido.")
                member_updates["role_code"] = role_code
                # Mantém um fallback global coerente para versões antigas e relatórios legados.
                user_updates["role_code"] = role["base_role"]
                user_updates["custom_role_code"] = None if role_code == role["base_role"] else role_code
            if "team_id" in data:
                team_id = int(data.get("team_id") or 0) or None
                if team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND profile_id=? AND active=1", (team_id, pid)).fetchone():
                    raise ApiError(400, "Equipe inválida.")
                member_updates["team_id"] = team_id
            if "active" in data:
                member_updates["active"] = 1 if bool(data.get("active")) else 0
            if is_platform_owner(actor) and "is_contractor" in data:
                contractor = 1 if bool(data.get("is_contractor")) else 0
                member_updates["is_contractor"] = contractor
                if contractor:
                    conn.execute("UPDATE profile_users SET is_contractor=0 WHERE profile_id=? AND user_id<>?", (pid, user_id))
                    conn.execute("UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?", (utc_now(), user_id, pid))
                    conn.execute("UPDATE business_profiles SET contractor_user_id=?,updated_at=? WHERE id=?", (user_id, utc_now(), pid))
                elif target["is_contractor"]:
                    conn.execute("UPDATE business_profiles SET contractor_user_id=NULL,updated_at=? WHERE id=?", (utc_now(), pid))
            if not user_updates and not member_updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            now = utc_now()
            if user_updates:
                user_updates["updated_at"] = now
                assignments = ",".join(f"{key}=?" for key in user_updates)
                try:
                    conn.execute(f"UPDATE users SET {assignments} WHERE id=?", [*user_updates.values(), user_id])
                except sqlite3.IntegrityError:
                    raise ApiError(409, "Este e-mail já está em uso.")
            if member_updates:
                member_updates["updated_at"] = now
                assignments = ",".join(f"{key}=?" for key in member_updates)
                conn.execute(f"UPDATE profile_users SET {assignments} WHERE profile_id=? AND user_id=?", [*member_updates.values(), pid, user_id])
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(actor["id"], "profile_user.update", "user", user_id, {"profile_id": pid, "fields": list(user_updates) + list(member_updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Usuário atualizado no perfil."})

    # ------------------------- acessos da plataforma -------------------------
    def require_platform_owner(self: Any) -> dict[str, Any]:
        actor, _, _ = self.require_user()
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da Plataforma pode administrar estes acessos.")
        return actor

    def platform_global_audit(actor_id: int, action: str, entity_type: str, entity_id: Any, details: Any, ip: str | None) -> None:
        with db_connect() as conn:
            conn.execute(
                """INSERT INTO audit_logs(profile_id,user_id,action,entity_type,entity_id,details,ip_address,created_at)
                   VALUES(NULL,?,?,?,?,?,?,?)""",
                (actor_id, action, entity_type, str(entity_id), ns["json_dumps"](details or {}), ip, utc_now()),
            )

    def api_platform_access(self: Any) -> None:
        self.require_platform_owner()
        with db_connect() as conn:
            role_rows = conn.execute("SELECT * FROM platform_roles ORDER BY is_owner DESC,is_system DESC,name").fetchall()
            permission_rows = conn.execute(
                "SELECT role_code,permission_code FROM platform_role_permissions WHERE allowed=1 ORDER BY permission_code"
            ).fetchall()
            users = conn.execute(
                """SELECT u.id,u.name,u.email,u.phone,u.active,u.must_change_password,u.last_login_at,u.created_at,
                   COALESCE(u.platform_role_code,CASE WHEN u.role_code='owner' THEN 'owner' END) AS platform_role_code,
                   pr.name AS platform_role_name,pr.is_owner
                   FROM users u
                   LEFT JOIN platform_roles pr ON pr.code=COALESCE(u.platform_role_code,CASE WHEN u.role_code='owner' THEN 'owner' END)
                   WHERE COALESCE(u.platform_role_code,CASE WHEN u.role_code='owner' THEN 'owner' END) IS NOT NULL
                   ORDER BY u.active DESC,pr.is_owner DESC,u.name"""
            ).fetchall()
            profiles = [dict(row) for row in conn.execute(
                "SELECT id,name,business_type,active FROM business_profiles ORDER BY active DESC,name"
            ).fetchall()]
            membership_rows = conn.execute(
                """SELECT pu.user_id,p.id AS profile_id,p.name AS profile_name
                   FROM profile_users pu JOIN business_profiles p ON p.id=pu.profile_id
                   JOIN users u ON u.id=pu.user_id
                   WHERE pu.active=1 AND COALESCE(u.platform_role_code,'')<>''
                   ORDER BY p.name"""
            ).fetchall()
        role_permissions: dict[str, list[str]] = {}
        for row in permission_rows:
            role_permissions.setdefault(str(row["role_code"]), []).append(str(row["permission_code"]))
        memberships: dict[int, list[dict[str, Any]]] = {}
        for row in membership_rows:
            memberships.setdefault(int(row["user_id"]), []).append(
                {"id": int(row["profile_id"]), "name": row["profile_name"]}
            )
        role_items = []
        for row in role_rows:
            item = dict(row)
            item["active"] = bool(item["active"])
            item["is_system"] = bool(item["is_system"])
            item["is_owner"] = bool(item["is_owner"])
            item["permissions"] = sorted(role_permissions.get(item["code"], []))
            role_items.append(item)
        user_items = []
        for row in users:
            item = dict(row)
            item["active"] = bool(item["active"])
            item["must_change_password"] = bool(item["must_change_password"])
            item["is_owner"] = bool(item.get("is_owner"))
            item["profiles"] = memberships.get(int(item["id"]), [])
            user_items.append(item)
        self.send_json(200, {
            "ok": True,
            "roles": role_items,
            "permissions": [
                {"code": code, "module": module, "description": description}
                for code, module, description in PLATFORM_PERMISSIONS
            ],
            "users": user_items,
            "profiles": profiles,
        })

    def api_platform_role_create(self: Any, actor: dict[str, Any]) -> None:
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da Plataforma pode criar cargos globais.")
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        raw_code = re.sub(r"[^a-z0-9_]+", "_", str(data.get("code") or name).lower()).strip("_")
        code = raw_code[:64]
        if len(name) < 2 or not code or code == "owner":
            raise ApiError(400, "Nome ou código do cargo inválido.")
        valid = {item[0] for item in PLATFORM_PERMISSIONS}
        selected = sorted({str(item) for item in (data.get("permissions") or []) if str(item) in valid})
        now = utc_now()
        with db_connect() as conn:
            try:
                conn.execute(
                    """INSERT INTO platform_roles(code,name,description,is_system,is_owner,active,created_at,updated_at)
                       VALUES(?,?,?,0,0,1,?,?)""",
                    (code, name, str(data.get("description") or "").strip(), now, now),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe um cargo da plataforma com este nome ou código.")
            conn.executemany(
                "INSERT INTO platform_role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                [(code, permission) for permission in selected],
            )
        platform_global_audit(
            actor["id"], "platform_role.create", "platform_role", code,
            {"name": name}, self.client_ip()
        )
        self.send_json(201, {"ok": True, "code": code, "message": "Cargo da plataforma criado."})

    def api_platform_role_update(self: Any, actor: dict[str, Any], role_code: str) -> None:
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da Plataforma pode alterar cargos globais.")
        data = self.read_json()
        with db_connect() as conn:
            role = conn.execute("SELECT * FROM platform_roles WHERE code=?", (role_code,)).fetchone()
            if not role:
                raise ApiError(404, "Cargo da plataforma não encontrado.")
            if role["is_owner"]:
                raise ApiError(400, "O cargo Dono da Plataforma é protegido.")
            updates: dict[str, Any] = {}
            if "name" in data:
                name = str(data.get("name") or "").strip()
                if len(name) < 2:
                    raise ApiError(400, "Nome inválido.")
                updates["name"] = name
            if "description" in data:
                updates["description"] = str(data.get("description") or "").strip()
            if "active" in data:
                active = 1 if bool(data.get("active")) else 0
                if not active and conn.execute(
                    "SELECT COUNT(*) FROM users WHERE platform_role_code=? AND active=1", (role_code,)
                ).fetchone()[0]:
                    raise ApiError(400, "Transfira ou desative os funcionários antes de desativar este cargo.")
                updates["active"] = active
            selected = None
            if "permissions" in data:
                valid = {item[0] for item in PLATFORM_PERMISSIONS}
                selected = sorted({str(item) for item in (data.get("permissions") or []) if str(item) in valid})
            if not updates and selected is None:
                raise ApiError(400, "Nenhuma alteração enviada.")
            if updates:
                updates["updated_at"] = utc_now()
                assignments = ",".join(f"{key}=?" for key in updates)
                conn.execute(f"UPDATE platform_roles SET {assignments} WHERE code=?", [*updates.values(), role_code])
            if selected is not None:
                conn.execute("DELETE FROM platform_role_permissions WHERE role_code=?", (role_code,))
                conn.executemany(
                    "INSERT INTO platform_role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                    [(role_code, permission) for permission in selected],
                )
        platform_global_audit(
            actor["id"], "platform_role.update", "platform_role", role_code,
            {"fields": list(updates)}, self.client_ip()
        )
        self.send_json(200, {"ok": True, "message": "Cargo da plataforma atualizado."})

    def validate_platform_profiles(conn: sqlite3.Connection, profile_ids: Any) -> list[int]:
        ids = sorted({int(item) for item in (profile_ids or []) if str(item).isdigit() and int(item) > 0})
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        found = {
            int(row[0]) for row in conn.execute(
                f"SELECT id FROM business_profiles WHERE id IN ({placeholders}) AND active=1", ids
            ).fetchall()
        }
        if found != set(ids):
            raise ApiError(400, "Um ou mais perfis selecionados são inválidos ou inativos.")
        return ids

    def api_platform_user_create(self: Any, actor: dict[str, Any]) -> None:
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da Plataforma pode criar estes funcionários.")
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        email = ns["normalize_email"](data.get("email") or "")
        password = str(data.get("password") or "")
        role_code = str(data.get("platform_role_code") or "").strip()
        if len(name) < 3 or "@" not in email:
            raise ApiError(400, "Nome ou e-mail inválido.")
        error = ns["validate_password"](password)
        if error:
            raise ApiError(400, error)
        now = utc_now()
        with db_connect() as conn:
            role = conn.execute(
                "SELECT * FROM platform_roles WHERE code=? AND active=1", (role_code,)
            ).fetchone()
            if not role:
                raise ApiError(400, "Cargo da plataforma inválido ou inativo.")
            if conn.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone():
                raise ApiError(409, "Este e-mail já está em uso.")
            profiles = [] if role["is_owner"] else validate_platform_profiles(conn, data.get("profile_ids"))
            if not role["is_owner"] and not profiles:
                raise ApiError(400, "Selecione ao menos um perfil para este funcionário.")
            base_role = "owner" if role["is_owner"] else "manager"
            cur = conn.execute(
                """INSERT INTO users(name,email,password_hash,role_code,platform_role_code,active,must_change_password,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,?,?,?)""",
                (
                    name, email, ns["hash_password"](password), base_role, role_code,
                    1 if data.get("must_change_password", True) else 0, now, now,
                ),
            )
            user_id = int(cur.lastrowid)
            for profile_id in profiles:
                conn.execute(
                    """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,'manager',NULL,0,1,?,?)""",
                    (profile_id, user_id, now, now),
                )
        platform_global_audit(
            actor["id"], "platform_user.create", "user", user_id,
            {"role": role_code, "profiles": profiles}, self.client_ip()
        )
        self.send_json(201, {"ok": True, "id": user_id, "message": "Funcionário da plataforma criado."})

    def api_platform_user_update(self: Any, actor: dict[str, Any], user_id: int) -> None:
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da Plataforma pode alterar estes funcionários.")
        data = self.read_json()
        with db_connect() as conn:
            target = conn.execute(
                """SELECT u.*,COALESCE(u.platform_role_code,CASE WHEN u.role_code='owner' THEN 'owner' END) AS effective_platform_role
                   FROM users u WHERE u.id=?""",
                (user_id,),
            ).fetchone()
            if not target or not target["effective_platform_role"]:
                raise ApiError(404, "Funcionário da plataforma não encontrado.")
            role_code = str(data.get("platform_role_code") or target["effective_platform_role"]).strip()
            role = conn.execute(
                "SELECT * FROM platform_roles WHERE code=? AND active=1", (role_code,)
            ).fetchone()
            if not role:
                raise ApiError(400, "Cargo da plataforma inválido ou inativo.")
            active = 1 if bool(data.get("active", target["active"])) else 0
            current_is_owner = target["effective_platform_role"] == "owner"
            becoming_owner = bool(role["is_owner"])
            owner_count = conn.execute(
                """SELECT COUNT(*) FROM users
                   WHERE active=1 AND COALESCE(platform_role_code,CASE WHEN role_code='owner' THEN 'owner' END)='owner'"""
            ).fetchone()[0]
            if current_is_owner and (not becoming_owner or not active) and owner_count <= 1:
                raise ApiError(400, "O último Dono ativo não pode ser removido ou desativado.")
            profiles = [] if becoming_owner else validate_platform_profiles(conn, data.get("profile_ids"))
            if not becoming_owner and not profiles:
                raise ApiError(400, "Selecione ao menos um perfil para este funcionário.")
            updates: dict[str, Any] = {
                "role_code": "owner" if becoming_owner else "manager",
                "platform_role_code": role_code,
                "active": active,
                "must_change_password": 1 if bool(data.get("must_change_password", target["must_change_password"])) else 0,
                "updated_at": utc_now(),
            }
            if "name" in data:
                name = str(data.get("name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome inválido.")
                updates["name"] = name
            if "email" in data:
                email = ns["normalize_email"](data.get("email") or "")
                if "@" not in email:
                    raise ApiError(400, "E-mail inválido.")
                updates["email"] = email
            if data.get("password"):
                error = ns["validate_password"](str(data["password"]))
                if error:
                    raise ApiError(400, error)
                updates["password_hash"] = ns["hash_password"](str(data["password"]))
            assignments = ",".join(f"{key}=?" for key in updates)
            try:
                conn.execute(f"UPDATE users SET {assignments} WHERE id=?", [*updates.values(), user_id])
            except sqlite3.IntegrityError:
                raise ApiError(409, "Este e-mail já está em uso.")
            conn.execute("DELETE FROM profile_users WHERE user_id=?", (user_id,))
            for profile_id in profiles:
                conn.execute(
                    """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,'manager',NULL,0,1,?,?)""",
                    (profile_id, user_id, utc_now(), utc_now()),
                )
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        platform_global_audit(
            actor["id"], "platform_user.update", "user", user_id,
            {"role": role_code, "profiles": profiles}, self.client_ip()
        )
        self.send_json(200, {"ok": True, "message": "Funcionário da plataforma atualizado."})

    # ------------------------- equipes -------------------------
    def api_teams_list(self: Any) -> None:
        actor, _, _ = self.require_user()
        if not (has_permission(actor, "teams.view") or has_permission(actor, "teams.manage")):
            raise ApiError(403, "Sem permissão para visualizar equipes.")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT t.*,u.name AS manager_name,
                   (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=t.profile_id AND pu.team_id=t.id AND pu.active=1) AS members
                   FROM teams t LEFT JOIN users u ON u.id=t.manager_id
                   WHERE t.profile_id=? ORDER BY t.active DESC,t.name""",
                (pid,),
            ).fetchall()
        self.send_json(200, {"ok": True, "teams": [dict(row) for row in rows]})

    def api_team_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "teams.manage"):
            raise ApiError(403, "Sem permissão para administrar equipes.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        manager_id = int(data.get("manager_id") or 0) or None
        target = max(0, int(data.get("monthly_target") or 0))
        if len(name) < 2:
            raise ApiError(400, "Nome da equipe inválido.")
        with db_connect() as conn:
            if manager_id:
                manager = conn.execute(
                    """SELECT r.base_role,pu.is_contractor FROM profile_users pu JOIN roles r ON r.code=pu.role_code
                       WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                    (pid, manager_id),
                ).fetchone()
                if not manager or (manager["base_role"] not in {"manager"} and not manager["is_contractor"]):
                    raise ApiError(400, "Gestor inválido para este perfil.")
            now = utc_now()
            try:
                cur = conn.execute(
                    """INSERT INTO teams(profile_id,name,manager_id,monthly_target,active,created_at,updated_at)
                       VALUES(?,?,?,?,1,?,?)""",
                    (pid, name, manager_id, target, now, now),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe uma equipe com este nome.")
        audit(actor["id"], "team.create", "team", cur.lastrowid, {"profile_id": pid, "name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": "Equipe criada."})

    def api_team_update(self: Any, actor: dict[str, Any], team_id: int) -> None:
        if not has_permission(actor, "teams.manage"):
            raise ApiError(403, "Sem permissão para administrar equipes.")
        pid = current_profile_id(actor)
        data = self.read_json()
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM teams WHERE id=? AND profile_id=?", (team_id, pid)).fetchone()
            if not current:
                raise ApiError(404, "Equipe não encontrada.")
            updates: dict[str, Any] = {}
            for field in ("name", "monthly_target", "active"):
                if field in data:
                    if field == "name":
                        value = str(data.get(field) or "").strip()
                        if len(value) < 2:
                            raise ApiError(400, "Nome inválido.")
                    elif field == "monthly_target":
                        value = max(0, int(data.get(field) or 0))
                    else:
                        value = 1 if bool(data.get(field)) else 0
                    updates[field] = value
            if "manager_id" in data:
                manager_id = int(data.get("manager_id") or 0) or None
                if manager_id and not conn.execute("SELECT 1 FROM profile_users WHERE profile_id=? AND user_id=? AND active=1", (pid, manager_id)).fetchone():
                    raise ApiError(400, "Gestor inválido.")
                updates["manager_id"] = manager_id
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            updates["updated_at"] = utc_now()
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE teams SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), team_id, pid])
        audit(actor["id"], "team.update", "team", team_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Equipe atualizada."})

    # ------------------------- planos e catálogos -------------------------
    def api_plans_list(self: Any, query: dict[str, list[str]]) -> None:
        actor, _, _ = self.require_user()
        pid = current_profile_id(actor)
        include_all = (query.get("all") or [""])[0] == "1" and (
            has_permission(actor, "plans.manage") or has_permission(actor, "plans.view")
        )
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT * FROM plans WHERE profile_id=? " + ("" if include_all else "AND active=1 ") + "ORDER BY sort_order,name",
                (pid,),
            ).fetchall()
        self.send_json(200, {"ok": True, "plans": [dict(row) for row in rows]})

    def api_plan_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "plans.manage"):
            raise ApiError(403, "Sem permissão para administrar planos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        if len(name) < 2:
            raise ApiError(400, "Nome do plano inválido.")
        now = utc_now()
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO plans(profile_id,provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                (pid, str(data.get("provider") or "").strip(), str(data.get("service") or "").strip(), name,
                 str(data.get("speed") or "").strip(), float(data.get("price") or 0), str(data.get("benefits") or "").strip(),
                 str(data.get("uf_list") or "").strip(), int(data.get("sort_order") or 0), now, now),
            )
        audit(actor["id"], "plan.create", "plan", cur.lastrowid, {"profile_id": pid, "name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": "Plano criado."})

    def api_plan_update(self: Any, actor: dict[str, Any], plan_id: int) -> None:
        if not has_permission(actor, "plans.manage"):
            raise ApiError(403, "Sem permissão para administrar planos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        allowed = {"provider", "service", "name", "speed", "price", "benefits", "uf_list", "sort_order", "active"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            raise ApiError(400, "Nenhuma alteração enviada.")
        if "price" in updates:
            updates["price"] = float(updates["price"] or 0)
        if "sort_order" in updates:
            updates["sort_order"] = int(updates["sort_order"] or 0)
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updates["updated_at"] = utc_now()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM plans WHERE id=? AND profile_id=?", (plan_id, pid)).fetchone():
                raise ApiError(404, "Plano não encontrado.")
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE plans SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), plan_id, pid])
        audit(actor["id"], "plan.update", "plan", plan_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Plano atualizado."})

    def profile_catalog_categories(conn: sqlite3.Connection, profile_id: int) -> set[str] | None:
        row = conn.execute("SELECT business_type FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
        business_type = str(row["business_type"] if row else "custom")
        if business_type == "custom":
            return None
        template = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["custom"])
        return set(template.get("catalog_labels", {})) | set(template.get("catalogs", {}))

    def api_catalogs(self: Any, query: dict[str, list[str]]) -> None:
        actor, _, _ = self.require_user()
        pid = current_profile_id(actor)
        include_all = (query.get("all") or [""])[0] == "1" and (
            has_permission(actor, "catalogs.manage") or has_permission(actor, "catalogs.view")
        )
        with db_connect() as conn:
            allowed = profile_catalog_categories(conn, pid)
            filters = ["profile_id=?"]
            params: list[Any] = [pid]
            if not include_all:
                filters.append("active=1")
            if allowed is not None:
                if not allowed:
                    self.send_json(200, {"ok": True, "catalogs": {}})
                    return
                placeholders = ",".join("?" for _ in allowed)
                filters.append(f"category IN ({placeholders})")
                params.extend(sorted(allowed))
            rows = conn.execute(
                f"SELECT * FROM catalog_items WHERE {' AND '.join(filters)} ORDER BY category,sort_order,label",
                params,
            ).fetchall()
        catalogs: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            catalogs.setdefault(item["category"], []).append(item)
        self.send_json(200, {"ok": True, "catalogs": catalogs})

    def api_catalog_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "catalogs.manage"):
            raise ApiError(403, "Sem permissão para administrar catálogos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        category = str(data.get("category") or "").strip()
        label = str(data.get("label") or "").strip()
        with db_connect() as category_conn:
            allowed_categories = profile_catalog_categories(category_conn, pid)
        if allowed_categories is not None and category not in allowed_categories:
            raise ApiError(400, "Esta categoria não pertence ao preset do perfil atual.")
        raw_code = str(data.get("code") or label).strip().lower()
        code = re.sub(r"[^a-z0-9_]+", "_", raw_code).strip("_")
        if not category or len(label) < 1 or not code:
            raise ApiError(400, "Categoria, código e rótulo são obrigatórios.")
        # Evita colisões globais do esquema legado.
        stored_code = code
        with db_connect() as conn:
            if conn.execute("SELECT 1 FROM catalog_items WHERE category=? AND code=?", (category, stored_code)).fetchone():
                stored_code = f"p{pid}_{code}"
            now = utc_now()
            cur = conn.execute(
                """INSERT INTO catalog_items(profile_id,category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,'{}',?,?)""",
                (pid, category, stored_code, label, int(data.get("sort_order") or 0), now, now),
            )
        audit(actor["id"], "catalog.create", "catalog", cur.lastrowid, {"profile_id": pid, "category": category}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "code": stored_code, "message": "Opção criada."})

    def api_catalog_update(self: Any, actor: dict[str, Any], item_id: int) -> None:
        if not has_permission(actor, "catalogs.manage"):
            raise ApiError(403, "Sem permissão para administrar catálogos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        allowed = {"label", "sort_order", "active"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            raise ApiError(400, "Nenhuma alteração enviada.")
        if "sort_order" in updates:
            updates["sort_order"] = int(updates["sort_order"] or 0)
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updates["updated_at"] = utc_now()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM catalog_items WHERE id=? AND profile_id=?", (item_id, pid)).fetchone():
                raise ApiError(404, "Opção não encontrada.")
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE catalog_items SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), item_id, pid])
        audit(actor["id"], "catalog.update", "catalog", item_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Opção atualizada."})

    # ------------------------- cargos do perfil -------------------------
    def permission_available_for_profile(code: str, modules: set[str]) -> bool:
        if code in {"backups.manage"}:
            return False
        if code in {"plans.view", "plans.manage"}:
            return bool({"plans", "services_catalog"} & modules)
        if code == "export.data":
            return "sales" in modules
        required = permission_modules.get(code)
        return not required or required in modules

    def available_profile_permission_codes(actor: dict[str, Any]) -> set[str]:
        modules = set(actor.get("profile_modules") or [])
        return {code for code, _, _ in ns["PERMISSIONS"] if permission_available_for_profile(code, modules)}

    def api_roles(self: Any) -> None:
        actor, _, _ = self.require_user()
        if not (has_permission(actor, "roles.manage") or has_permission(actor, "roles.view")):
            raise ApiError(403, "Sem permissão para visualizar cargos.")
        pid = current_profile_id(actor)
        valid_permissions = available_profile_permission_codes(actor)
        with db_connect() as conn:
            roles = conn.execute(
                """SELECT r.*,
                   (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=? AND pu.role_code=r.code) AS users_count,
                   (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=? AND pu.role_code=r.code AND pu.active=1) AS active_users_count
                   FROM roles r WHERE r.profile_id=? ORDER BY r.name""",
                (pid, pid, pid),
            ).fetchall()
            base_roles = conn.execute(
                "SELECT * FROM roles WHERE is_system=1 AND code IN ('manager','bko','seller') ORDER BY name"
            ).fetchall()
            role_codes = [row["code"] for row in roles] + [row["code"] for row in base_roles]
            if role_codes:
                placeholders = ",".join("?" for _ in role_codes)
                permission_rows = conn.execute(
                    f"SELECT role_code,permission_code,allowed FROM role_permissions WHERE allowed=1 AND role_code IN ({placeholders})",
                    role_codes,
                ).fetchall()
            else:
                permission_rows = []
            permission_rows_all = conn.execute("SELECT * FROM permissions ORDER BY module,description").fetchall()
        role_map: dict[str, list[str]] = {}
        for row in permission_rows:
            if row["permission_code"] in valid_permissions:
                role_map.setdefault(row["role_code"], []).append(row["permission_code"])
        role_items = []
        for row in roles:
            item = dict(row)
            item["permissions"] = sorted(role_map.get(item["code"], []))
            role_items.append(item)
        base_items = []
        for row in base_roles:
            item = dict(row)
            inherited = set(role_map.get(item["code"], []))
            for profile_role in role_items:
                if profile_role.get("base_role") == item["code"]:
                    inherited.update(profile_role.get("permissions") or [])
            item["permissions"] = sorted(inherited)
            base_items.append(item)
        permissions = [dict(row) for row in permission_rows_all if row["code"] in valid_permissions]
        self.send_json(200, {"ok": True, "roles": role_items, "base_roles": base_items, "permissions": permissions, "role_permissions": role_map})

    def api_role_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "roles.manage"):
            raise ApiError(403, "Sem permissão para administrar cargos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        base_role = str(data.get("base_role") or "seller").strip()
        if len(name) < 2 or base_role not in {"manager", "bko", "seller"}:
            raise ApiError(400, "Nome ou cargo-base inválido.")
        raw_code = re.sub(r"[^a-z0-9_]+", "_", str(data.get("code") or name).lower()).strip("_")
        code = raw_code[:80]
        valid = available_profile_permission_codes(actor)
        selected = sorted({str(item) for item in (data.get("permissions") or []) if str(item) in valid})
        now = utc_now()
        with db_connect() as conn:
            if conn.execute("SELECT 1 FROM roles WHERE code=?", (code,)).fetchone():
                code = f"p{pid}_{raw_code}"[:80]
            try:
                conn.execute(
                    """INSERT INTO roles(code,name,description,base_role,is_system,active,created_at,updated_at,profile_id)
                       VALUES(?,?,?,?,0,1,?,?,?)""",
                    (code, name, str(data.get("description") or "").strip(), base_role, now, now, pid),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe um cargo com este nome ou código.")
            conn.executemany(
                "INSERT INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                [(code, permission) for permission in selected],
            )
        audit(actor["id"], "role.create", "role", code, {"profile_id": pid, "name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "code": code, "message": "Cargo criado no perfil."})

    def api_role_update(self: Any, actor: dict[str, Any], role_code: str) -> None:
        if not has_permission(actor, "roles.manage"):
            raise ApiError(403, "Sem permissão para administrar cargos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        with db_connect() as conn:
            role = conn.execute("SELECT * FROM roles WHERE code=?", (role_code,)).fetchone()
            if not role:
                raise ApiError(404, "Cargo não encontrado.")
            if role["is_system"]:
                if role_code == "owner":
                    raise ApiError(400, "O cargo Dono possui acesso total e não pode ser limitado.")
                if not is_platform_owner(actor):
                    raise ApiError(403, "O Contratante cria cargos próprios; cargos nativos só podem ser alterados pelo Dono.")
            elif int(role["profile_id"] or 0) != pid:
                raise ApiError(403, "Este cargo pertence a outro perfil.")
            updates: dict[str, Any] = {}
            if not role["is_system"]:
                if "name" in data:
                    name = str(data.get("name") or "").strip()
                    if len(name) < 2:
                        raise ApiError(400, "Nome inválido.")
                    updates["name"] = name
                if "description" in data:
                    updates["description"] = str(data.get("description") or "").strip()
                if "base_role" in data:
                    base = str(data.get("base_role") or "").strip()
                    if base not in {"manager", "bko", "seller"}:
                        raise ApiError(400, "Cargo-base inválido.")
                    updates["base_role"] = base
                if "active" in data:
                    active = 1 if bool(data.get("active")) else 0
                    if not active and conn.execute("SELECT COUNT(*) FROM profile_users WHERE profile_id=? AND role_code=? AND active=1", (pid, role_code)).fetchone()[0]:
                        raise ApiError(400, "Transfira os usuários antes de desativar este cargo.")
                    updates["active"] = active
            selected = None
            if "permissions" in data:
                valid = available_profile_permission_codes(actor)
                selected = sorted({str(item) for item in (data.get("permissions") or []) if str(item) in valid})
            if not updates and selected is None:
                raise ApiError(400, "Nenhuma alteração enviada.")
            if updates:
                updates["updated_at"] = utc_now()
                assignments = ",".join(f"{key}=?" for key in updates)
                conn.execute(f"UPDATE roles SET {assignments} WHERE code=?", [*updates.values(), role_code])
            if selected is not None:
                conn.execute("DELETE FROM role_permissions WHERE role_code=?", (role_code,))
                conn.executemany("INSERT INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)", [(role_code, item) for item in selected])
        audit(actor["id"], "role.update", "role", role_code, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Cargo atualizado."})

    # ------------------------- vendas -------------------------
    def api_sale_create(self: Any, user: dict[str, Any]) -> None:
        if not has_permission(user, "sales.create"):
            raise ApiError(403, "Sem permissão para cadastrar vendas.")
        pid = current_profile_id(user)
        data = self.read_json()
        client_name = str(data.get("client_name") or "").strip()
        phone = ns["normalize_mobile_phone"](data.get("phone") or "")
        plan_id = int(data.get("plan_id") or 0)
        if len(client_name) < 3 or not phone or not plan_id:
            raise ApiError(400, "Cliente, celular brasileiro válido e plano são obrigatórios.")
        with db_connect() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE id=? AND profile_id=? AND active=1", (plan_id, pid)).fetchone()
            if not plan:
                raise ApiError(400, "Plano inválido ou pertencente a outro perfil.")
            seller_id = user["id"]
            if has_permission(user, "sales.all") and data.get("seller_id"):
                seller_id = int(data["seller_id"])
            seller = conn.execute(
                """SELECT pu.user_id AS id,pu.team_id,pu.active,r.base_role FROM profile_users pu JOIN roles r ON r.code=pu.role_code
                   WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                (pid, seller_id),
            ).fetchone()
            if not seller or seller["base_role"] not in {"seller", "manager"}:
                raise ApiError(400, "Vendedor inválido para este perfil.")
            fields = self.sale_general_values(data)
            if not fields["cpf_cnpj"]:
                raise ApiError(400, "CPF ou CNPJ é obrigatório para cadastrar a venda.")
            now = utc_now()
            cur = conn.execute(
                """INSERT INTO sales(
                    profile_id,person_type,client_name,cpf_cnpj,birth_date,mother_name,phone,contact_phone,email,
                    cep,address,address_number,complement,neighborhood,city,uf,property_type,
                    plan_id,plan_name_snapshot,plan_price_snapshot,provider,service,
                    payment_method,due_day,channel,suggested_date,suggested_period,notes,
                    seller_id,team_id,status,activation_status,biometric_status,installation_status,
                    created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'nova',
                    'aguardando_ativacao','biometria_pendente','aguardando_instalacao',?,?)""",
                (
                    pid, fields["person_type"], client_name, fields["cpf_cnpj"], fields["birth_date"], fields["mother_name"],
                    phone, fields["contact_phone"], fields["email"], fields["cep"], fields["address"], fields["address_number"],
                    fields["complement"], fields["neighborhood"], fields["city"], fields["uf"], fields["property_type"],
                    plan_id, plan["name"], plan["price"], plan["provider"], plan["service"], fields["payment_method"],
                    fields["due_day"], fields["channel"], fields["suggested_date"], fields["suggested_period"], fields["notes"],
                    seller_id, seller["team_id"], now, now,
                ),
            )
            sale_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO sale_history(sale_id,user_id,event_type,details,created_at) VALUES(?,?,'created',?,?)",
                (sale_id, user["id"], "Venda cadastrada", now),
            )
        audit(user["id"], "sale.create", "sale", sale_id, {"profile_id": pid, "client": client_name}, self.client_ip())
        self.trigger_webhook("sale.created", {"sale_id": sale_id, "client_name": client_name})
        self.send_json(201, {"ok": True, "id": sale_id, "message": "Venda cadastrada."})

    def api_sale_update(self: Any, user: dict[str, Any], sale_id: int) -> None:
        pid = current_profile_id(user)
        data = self.read_json()
        with db_connect() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=? AND profile_id=?", (sale_id, pid)).fetchone()
            if not sale:
                raise ApiError(404, "Venda não encontrada neste perfil.")
            if data.get("plan_id") and not conn.execute("SELECT 1 FROM plans WHERE id=? AND profile_id=? AND active=1", (int(data["plan_id"]), pid)).fetchone():
                raise ApiError(400, "Plano inválido para este perfil.")
            if data.get("seller_id"):
                membership = conn.execute("SELECT team_id FROM profile_users WHERE profile_id=? AND user_id=? AND active=1", (pid, int(data["seller_id"]))).fetchone()
                if not membership:
                    raise ApiError(400, "Vendedor inválido para este perfil.")
                conn.execute("UPDATE users SET team_id=? WHERE id=?", (membership["team_id"], int(data["seller_id"])))
        return original_sale_update(self, user, sale_id)

    def api_sale_workflow(self: Any, user: dict[str, Any], sale_id: int) -> None:
        pid = current_profile_id(user)
        data = self.read_json()
        with db_connect() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=? AND profile_id=?", (sale_id, pid)).fetchone()
            if not sale:
                raise ApiError(404, "Venda não encontrada neste perfil.")
            if data.get("bko_user_id"):
                target = int(data["bko_user_id"])
                member = conn.execute(
                    """SELECT r.base_role FROM profile_users pu JOIN roles r ON r.code=pu.role_code
                       WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                    (pid, target),
                ).fetchone()
                if not member or member["base_role"] not in {"bko", "manager"}:
                    raise ApiError(400, "Responsável BKO inválido para este perfil.")
                conn.execute("UPDATE users SET role_code=? WHERE id=?", (member["base_role"], target))
        return original_sale_workflow(self, user, sale_id)

    # ------------------------- ranking e análise -------------------------
    def api_ranking(self: Any, query: dict[str, list[str]]) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "ranking.all") or has_permission(user, "ranking.own")):
            raise ApiError(403, "Sem permissão para visualizar o ranking.")
        pid = current_profile_id(user)
        period = (query.get("period") or ["month"])[0]
        prefix = date.today().strftime("%Y-%m") if period == "month" else None
        date_clause = "AND substr(s.created_at,1,7)=?" if prefix else ""
        params: list[Any] = [pid]
        if prefix:
            params.append(prefix)
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id,u.name,COALESCE(t.name,'Sem equipe') AS team_name,
                    COUNT(s.id) AS total,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed,
                    SUM(CASE WHEN s.status='cancelada' THEN 1 ELSE 0 END) AS cancelled,
                    COALESCE(SUM(s.plan_price_snapshot),0) AS revenue
                    FROM profile_users pu JOIN users u ON u.id=pu.user_id
                    JOIN roles r ON r.code=pu.role_code
                    LEFT JOIN teams t ON t.id=pu.team_id AND t.profile_id=pu.profile_id
                    LEFT JOIN sales s ON s.seller_id=u.id AND s.profile_id=pu.profile_id {date_clause}
                    WHERE pu.profile_id=? AND pu.active=1 AND r.base_role='seller'
                    GROUP BY u.id,u.name,t.name""",
                ([prefix, pid] if prefix else [pid]),
            ).fetchall()
        ranking = []
        for row in rows:
            item = dict(row)
            total = item["total"] or 0
            installed = item["installed"] or 0
            item["conversion"] = round(installed * 100 / total, 1) if total else 0
            item["points"] = installed * 100 + total * 10 - (item["cancelled"] or 0) * 5
            ranking.append(item)
        ranking.sort(key=lambda item: (item["points"], item["installed"], item["total"]), reverse=True)
        for index, item in enumerate(ranking, 1):
            item["position"] = index
        if not has_permission(user, "ranking.all"):
            ranking = [item for item in ranking if item["id"] == user["id"]]
        self.send_json(200, {"ok": True, "period": period, "ranking": ranking})

    def api_daily_analysis(self: Any, query: dict[str, list[str]]) -> None:
        user = self.require_permission("daily.view")
        pid = current_profile_id(user)
        selected = (query.get("date") or [local_today()])[0]
        if not ns["validate_iso_date"](selected, False):
            raise ApiError(400, "Data inválida.")
        with db_connect() as conn:
            teams = conn.execute(
                """SELECT COALESCE(t.name,'Sem equipe') AS team_name,COUNT(s.id) AS sales,
                   SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed,
                   SUM(CASE WHEN s.status='cancelada' THEN 1 ELSE 0 END) AS cancelled
                   FROM sales s LEFT JOIN teams t ON t.id=s.team_id AND t.profile_id=s.profile_id
                   WHERE s.profile_id=? AND substr(s.created_at,1,10)=?
                   GROUP BY COALESCE(t.name,'Sem equipe') ORDER BY sales DESC""",
                (pid, selected),
            ).fetchall()
            sellers = conn.execute(
                """SELECT u.name AS seller_name,COALESCE(t.name,'Sem equipe') AS team_name,COUNT(s.id) AS sales,
                   SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed
                   FROM sales s JOIN users u ON u.id=s.seller_id
                   LEFT JOIN teams t ON t.id=s.team_id AND t.profile_id=s.profile_id
                   WHERE s.profile_id=? AND substr(s.created_at,1,10)=?
                   GROUP BY u.id,u.name,t.name ORDER BY sales DESC,u.name""",
                (pid, selected),
            ).fetchall()
        self.send_json(200, {"ok": True, "date": selected, "teams": [dict(row) for row in teams], "sellers": [dict(row) for row in sellers]})

    # ------------------------- caixa -------------------------
    def api_cash(self: Any, query: dict[str, list[str]]) -> None:
        user = self.require_permission("cash.view")
        pid = current_profile_id(user)
        date_from = (query.get("date_from") or [""])[0]
        date_to = (query.get("date_to") or [""])[0]
        filters = ["profile_id=?", "active=1"]
        params: list[Any] = [pid]
        if date_from:
            filters.append("transaction_date>=?")
            params.append(date_from)
        if date_to:
            filters.append("transaction_date<=?")
            params.append(date_to)
        where = " AND ".join(filters)
        with db_connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM cash_transactions WHERE {where} ORDER BY transaction_date DESC,id DESC LIMIT 1000",
                params,
            ).fetchall()
            summary = conn.execute(
                f"""SELECT
                   COALESCE(SUM(CASE WHEN transaction_type='entry' THEN amount ELSE 0 END),0) AS entries,
                   COALESCE(SUM(CASE WHEN transaction_type='exit' THEN amount ELSE 0 END),0) AS exits
                   FROM cash_transactions WHERE {where}""",
                params,
            ).fetchone()
        entries = float(summary["entries"] or 0)
        exits = float(summary["exits"] or 0)
        self.send_json(200, {"ok": True, "summary": {"entries": entries, "exits": exits, "balance": entries - exits}, "transactions": [dict(row) for row in rows]})

    def api_cash_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "cash.manage"):
            raise ApiError(403, "Sem permissão para administrar o caixa.")
        pid = current_profile_id(actor)
        data = self.read_json()
        transaction_type = str(data.get("transaction_type") or "").strip()
        category = str(data.get("category") or "").strip()
        description = str(data.get("description") or "").strip()
        amount = float(data.get("amount") or 0)
        transaction_date = str(data.get("transaction_date") or local_today()).strip()
        if transaction_type not in {"entry", "exit"} or not category or len(description) < 2 or amount <= 0:
            raise ApiError(400, "Tipo, categoria, descrição e valor positivo são obrigatórios.")
        if not ns["validate_iso_date"](transaction_date, False):
            raise ApiError(400, "Data inválida.")
        now = utc_now()
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO cash_transactions
                   (profile_id,transaction_type,category,description,amount,transaction_date,payment_method,notes,created_by,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                (pid, transaction_type, category, description, amount, transaction_date,
                 str(data.get("payment_method") or "").strip() or None,
                 str(data.get("notes") or "").strip()[:1000] or None,
                 actor["id"], now, now),
            )
        audit(actor["id"], "cash.create", "cash_transaction", cur.lastrowid, {"profile_id": pid, "type": transaction_type, "amount": amount}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": "Lançamento criado."})

    def api_cash_update(self: Any, actor: dict[str, Any], transaction_id: int) -> None:
        if not has_permission(actor, "cash.manage"):
            raise ApiError(403, "Sem permissão para administrar o caixa.")
        pid = current_profile_id(actor)
        data = self.read_json()
        allowed = {"transaction_type", "category", "description", "amount", "transaction_date", "payment_method", "notes", "active"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            raise ApiError(400, "Nenhuma alteração enviada.")
        if "transaction_type" in updates and updates["transaction_type"] not in {"entry", "exit"}:
            raise ApiError(400, "Tipo de lançamento inválido.")
        if "amount" in updates:
            updates["amount"] = float(updates["amount"] or 0)
            if updates["amount"] <= 0:
                raise ApiError(400, "O valor deve ser positivo.")
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updates["updated_at"] = utc_now()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM cash_transactions WHERE id=? AND profile_id=?", (transaction_id, pid)).fetchone():
                raise ApiError(404, "Lançamento não encontrado.")
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE cash_transactions SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), transaction_id, pid])
        audit(actor["id"], "cash.update", "cash_transaction", transaction_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Lançamento atualizado."})

    # ------------------------- registros dos presets -------------------------
    def record_config(user: dict[str, Any], module: str) -> dict[str, Any]:
        business_type = str(user.get("profile_type") or "custom")
        template = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["custom"])
        config = template.get("records", {}).get(module)
        if not config or module not in set(user.get("profile_modules", [])):
            raise ApiError(404, "Módulo não disponível neste perfil.")
        return config

    def can_view_record_module(user: dict[str, Any], module: str) -> bool:
        return is_platform_owner(user) or bool(user.get("is_contractor")) or has_permission(user, f"{module}.view") or has_permission(user, f"{module}.manage")

    def can_manage_record_module(user: dict[str, Any], module: str) -> bool:
        return is_platform_owner(user) or has_permission(user, f"{module}.manage")

    def serialize_record(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["data"] = _parse_json(item.pop("data_json", "{}"), {})
        item["active"] = bool(item.get("active"))
        return item

    def api_profile_records(self: Any, query: dict[str, list[str]]) -> None:
        actor, _, _ = self.require_user()
        module = str((query.get("module") or [""])[0]).strip()
        config = record_config(actor, module)
        if not can_view_record_module(actor, module):
            raise ApiError(403, "Sem permissão para visualizar este módulo.")
        pid = current_profile_id(actor)
        include_all = (query.get("all") or [""])[0] == "1" and can_manage_record_module(actor, module)
        search = str((query.get("search") or [""])[0]).strip()
        filters = ["r.profile_id=?", "r.module_code=?"]
        params: list[Any] = [pid, module]
        if not include_all:
            filters.append("r.active=1")
        if search:
            filters.append("(r.title LIKE ? OR r.subtitle LIKE ? OR r.notes LIKE ? OR r.data_json LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term, term])
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT r.*,u.name AS assigned_user_name
                    FROM profile_records r LEFT JOIN users u ON u.id=r.assigned_user_id
                    WHERE {' AND '.join(filters)}
                    ORDER BY CASE WHEN r.due_date IS NULL OR r.due_date='' THEN 1 ELSE 0 END,r.due_date DESC,r.id DESC
                    LIMIT 1500""",
                params,
            ).fetchall()
            status_rows = conn.execute(
                """SELECT COALESCE(NULLIF(status,''),'sem_status') AS status,COUNT(*) AS total
                   FROM profile_records WHERE profile_id=? AND module_code=? AND active=1
                   GROUP BY COALESCE(NULLIF(status,''),'sem_status') ORDER BY total DESC""",
                (pid, module),
            ).fetchall()
        self.send_json(200, {
            "ok": True,
            "module": module,
            "config": config,
            "records": [serialize_record(row) for row in rows],
            "summary": {"total": sum(int(row["total"]) for row in status_rows), "by_status": [dict(row) for row in status_rows]},
            "can_manage": can_manage_record_module(actor, module),
        })

    def normalize_record_payload(data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        title = str(data.get("title") or "").strip()
        if len(title) < 2:
            raise ApiError(400, f"Informe o nome ou identificação de {str(config.get('singular') or 'registro').lower()}.")
        uses_amount = bool(config.get("amount_label") is not False and config.get("amount_label"))
        amount = float(data.get("amount") or 0) if uses_amount else 0.0
        if amount < 0:
            raise ApiError(400, "O valor não pode ser negativo.")
        uses_due = bool(config.get("due_label") is not False and config.get("due_label"))
        due_date = (str(data.get("due_date") or "").strip() or None) if uses_due else None
        if due_date and not ns["validate_iso_date"](due_date, False):
            raise ApiError(400, "Data inválida.")
        raw_fields = data.get("data") if isinstance(data.get("data"), dict) else {}
        fields: dict[str, Any] = {}
        for field in config.get("fields", []):
            key = str(field.get("key") or "").strip()
            if not key:
                continue
            value = raw_fields.get(key)
            field_type = str(field.get("type") or "text")
            empty = value is None or value == "" or value == []
            if field.get("required") and empty:
                raise ApiError(400, f"O campo {field.get('label') or key} é obrigatório.")
            if empty:
                fields[key] = None
                continue
            if field_type in {"record", "plan"}:
                try:
                    fields[key] = int(value)
                except (TypeError, ValueError):
                    raise ApiError(400, f"Referência inválida em {field.get('label') or key}.")
            elif field_type == "number":
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ApiError(400, f"Número inválido em {field.get('label') or key}.")
                if field.get("min") is not None and number < float(field["min"]):
                    raise ApiError(400, f"O campo {field.get('label') or key} está abaixo do mínimo permitido.")
                if field.get("max") is not None and number > float(field["max"]):
                    raise ApiError(400, f"O campo {field.get('label') or key} excede o máximo permitido.")
                fields[key] = number
            else:
                fields[key] = str(value).strip()[:4000]
        return {
            "title": title,
            "subtitle": str(data.get("subtitle") or "").strip()[:240] if config.get("subtitle_label") is not False else "",
            "status": str(data.get("status") or "").strip()[:80],
            "amount": amount,
            "assigned_user_id": int(data.get("assigned_user_id") or 0) or None if config.get("assigned_label") is not False else None,
            "due_date": due_date,
            "notes": str(data.get("notes") or "").strip()[:4000],
            "fields": fields,
            "data_json": _json(fields),
        }

    def validate_record_custom_fields(conn: sqlite3.Connection, profile_id: int, config: dict[str, Any], fields: dict[str, Any]) -> None:
        for field in config.get("fields", []):
            key = str(field.get("key") or "")
            value = fields.get(key)
            if value in (None, "", []):
                continue
            field_type = str(field.get("type") or "text")
            if field_type == "record":
                module = str(field.get("module") or "")
                row = conn.execute(
                    "SELECT id,status FROM profile_records WHERE id=? AND profile_id=? AND module_code=? AND active=1",
                    (int(value), profile_id, module),
                ).fetchone()
                if not row:
                    raise ApiError(400, f"A referência informada em {field.get('label') or key} não pertence a este perfil.")
            elif field_type == "plan":
                if not conn.execute("SELECT 1 FROM plans WHERE id=? AND profile_id=? AND active=1", (int(value), profile_id)).fetchone():
                    raise ApiError(400, f"O serviço informado em {field.get('label') or key} não pertence a este perfil.")
            elif field_type == "catalog":
                category = str(field.get("category") or "")
                if not conn.execute(
                    "SELECT 1 FROM catalog_items WHERE profile_id=? AND category=? AND code=? AND active=1",
                    (profile_id, category, str(value)),
                ).fetchone():
                    raise ApiError(400, f"A opção informada em {field.get('label') or key} não pertence ao catálogo deste perfil.")

    def validate_record_assignee(conn: sqlite3.Connection, profile_id: int, user_id: int | None) -> None:
        if user_id and not conn.execute(
            "SELECT 1 FROM profile_users WHERE profile_id=? AND user_id=? AND active=1", (profile_id, user_id)
        ).fetchone():
            raise ApiError(400, "Responsável inválido para este perfil.")

    def api_profile_record_create(self: Any, actor: dict[str, Any]) -> None:
        data = self.read_json()
        module = str(data.get("module") or "").strip()
        config = record_config(actor, module)
        if not can_manage_record_module(actor, module):
            raise ApiError(403, "Sem permissão para criar registros neste módulo.")
        pid = current_profile_id(actor)
        values = normalize_record_payload(data, config)
        now = utc_now()
        with db_connect() as conn:
            validate_record_assignee(conn, pid, values["assigned_user_id"])
            validate_record_custom_fields(conn, pid, config, values["fields"])
            cur = conn.execute(
                """INSERT INTO profile_records
                   (profile_id,module_code,title,subtitle,status,amount,assigned_user_id,due_date,notes,data_json,active,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?,?)""",
                (pid, module, values["title"], values["subtitle"], values["status"], values["amount"],
                 values["assigned_user_id"], values["due_date"], values["notes"], values["data_json"], actor["id"], now, now),
            )
        audit(actor["id"], "profile_record.create", module, cur.lastrowid, {"profile_id": pid, "title": values["title"]}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": f"{config.get('singular','Registro')} criado."})

    def api_profile_record_update(self: Any, actor: dict[str, Any], record_id: int) -> None:
        data = self.read_json()
        module = str(data.get("module") or "").strip()
        config = record_config(actor, module)
        if not can_manage_record_module(actor, module):
            raise ApiError(403, "Sem permissão para alterar registros neste módulo.")
        pid = current_profile_id(actor)
        values = normalize_record_payload(data, config)
        values["active"] = 1 if bool(data.get("active", True)) else 0
        values["updated_at"] = utc_now()
        with db_connect() as conn:
            current = conn.execute(
                "SELECT id FROM profile_records WHERE id=? AND profile_id=? AND module_code=?", (record_id, pid, module)
            ).fetchone()
            if not current:
                raise ApiError(404, "Registro não encontrado.")
            validate_record_assignee(conn, pid, values["assigned_user_id"])
            validate_record_custom_fields(conn, pid, config, values["fields"])
            conn.execute(
                """UPDATE profile_records SET title=?,subtitle=?,status=?,amount=?,assigned_user_id=?,due_date=?,notes=?,data_json=?,active=?,updated_at=?
                   WHERE id=? AND profile_id=? AND module_code=?""",
                (values["title"], values["subtitle"], values["status"], values["amount"], values["assigned_user_id"],
                 values["due_date"], values["notes"], values["data_json"], values["active"], values["updated_at"], record_id, pid, module),
            )
        audit(actor["id"], "profile_record.update", module, record_id, {"profile_id": pid}, self.client_ip())
        self.send_json(200, {"ok": True, "message": f"{config.get('singular','Registro')} atualizado."})

    def generic_dashboard(self: Any, user: dict[str, Any]) -> None:
        pid = current_profile_id(user)
        template = PROFILE_TEMPLATES.get(str(user.get("profile_type") or "custom"), PROFILE_TEMPLATES["custom"])
        modules = [module for module in template.get("records", {}) if module in set(user.get("profile_modules", []))]
        cards: list[dict[str, Any]] = []
        recent: list[dict[str, Any]] = []
        with db_connect() as conn:
            for module in modules:
                config = template["records"][module]
                row = conn.execute(
                    """SELECT COUNT(*) AS total,
                       SUM(CASE WHEN due_date IS NOT NULL AND due_date<>'' AND due_date<? AND active=1 THEN 1 ELSE 0 END) AS overdue,
                       COALESCE(SUM(CASE WHEN active=1 THEN amount ELSE 0 END),0) AS amount
                       FROM profile_records WHERE profile_id=? AND module_code=? AND active=1""",
                    (local_today(), pid, module),
                ).fetchone()
                cards.append({"module": module, "label": config.get("label", module), "total": int(row["total"] or 0),
                              "overdue": int(row["overdue"] or 0), "amount": float(row["amount"] or 0)})
            if modules:
                placeholders = ",".join("?" for _ in modules)
                rows = conn.execute(
                    f"""SELECT r.*,u.name AS assigned_user_name FROM profile_records r
                        LEFT JOIN users u ON u.id=r.assigned_user_id
                        WHERE r.profile_id=? AND r.module_code IN ({placeholders}) AND r.active=1
                        ORDER BY r.updated_at DESC,r.id DESC LIMIT 12""",
                    [pid, *modules],
                ).fetchall()
                recent = [serialize_record(row) for row in rows]
        self.send_json(200, {
            "ok": True,
            "profile_type": str(user.get("profile_type") or "custom"),
            "generic": True,
            "preset": public_template(str(user.get("profile_type") or "custom")),
            "cards": cards,
            "recent": recent,
        })

    # ------------------------- dashboard por tipo -------------------------
    def api_dashboard(self: Any) -> None:
        user = self.require_permission("dashboard.view")
        if user.get("profile_type") == "cash_control":
            pid = current_profile_id(user)
            today = local_today()
            month = today[:7]
            with db_connect() as conn:
                summary = conn.execute(
                    """SELECT
                       COALESCE(SUM(CASE WHEN transaction_type='entry' AND active=1 THEN amount ELSE 0 END),0) AS entries,
                       COALESCE(SUM(CASE WHEN transaction_type='exit' AND active=1 THEN amount ELSE 0 END),0) AS exits,
                       COALESCE(SUM(CASE WHEN transaction_type='entry' AND active=1 AND substr(transaction_date,1,7)=? THEN amount ELSE 0 END),0) AS month_entries,
                       COALESCE(SUM(CASE WHEN transaction_type='exit' AND active=1 AND substr(transaction_date,1,7)=? THEN amount ELSE 0 END),0) AS month_exits
                       FROM cash_transactions WHERE profile_id=?""",
                    (month, month, pid),
                ).fetchone()
                recent = conn.execute(
                    "SELECT * FROM cash_transactions WHERE profile_id=? AND active=1 ORDER BY transaction_date DESC,id DESC LIMIT 8",
                    (pid,),
                ).fetchall()
            entries = float(summary["entries"] or 0)
            exits = float(summary["exits"] or 0)
            self.send_json(200, {
                "ok": True,
                "profile_type": "cash_control",
                "cash": {
                    "entries": entries,
                    "exits": exits,
                    "balance": entries - exits,
                    "month_entries": float(summary["month_entries"] or 0),
                    "month_exits": float(summary["month_exits"] or 0),
                },
                "recent_transactions": [dict(row) for row in recent],
            })
            return
        if user.get("profile_type") != "internet_sales":
            return generic_dashboard(self, user)
        return original_dashboard(self)

    # ------------------------- auditoria e integrações por perfil -------------------------
    def api_audit(self: Any, query: dict[str, list[str]]) -> None:
        user = self.require_permission("audit.view")
        pid = current_profile_id(user)
        limit = min(1000, max(1, int((query.get("limit") or ["300"])[0])))
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT a.*,u.name AS user_name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id
                   WHERE a.profile_id=? ORDER BY a.id DESC LIMIT ?""",
                (pid, limit),
            ).fetchall()
        self.send_json(200, {"ok": True, "logs": [dict(row) for row in rows]})

    def profile_setting_rows(profile_id: int, keys: dict[str, bool]) -> dict[str, dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT key,value,secret,updated_at FROM profile_settings WHERE profile_id=? AND key IN (%s)" % ",".join("?" for _ in keys),
                (profile_id, *keys.keys()),
            ).fetchall()
        return {row["key"]: dict(row) for row in rows}

    def api_integrations_get(self: Any) -> None:
        actor, _, _ = self.require_user()
        if not (has_permission(actor, "integrations.manage") or has_permission(actor, "integrations.view")):
            raise ApiError(403, "Sem permissão para visualizar integrações.")
        pid = current_profile_id(actor)
        saved = profile_setting_rows(pid, self.INTEGRATION_KEYS)
        result: dict[str, Any] = {}
        for key, secret in self.INTEGRATION_KEYS.items():
            row = saved.get(key)
            result[key] = {
                "configured": bool(row and row["value"]),
                "value": "••••••••" if secret and row and row["value"] else (row["value"] if row else ""),
            }
        ai_status = ns["public_ai_status"](
            provider_override=result.get("ai_provider", {}).get("value") or "",
            groq_model_override=result.get("groq_model", {}).get("value") or "",
            openai_model_override=result.get("openai_model", {}).get("value") or "",
        )
        result["ai"] = ai_status
        result["groq"] = ai_status.get("providers", {}).get("groq", {})
        result["openai"] = ai_status.get("providers", {}).get("openai", {})
        self.send_json(200, {"ok": True, "integrations": result, "notes": {"scope": "Estas configurações pertencem somente ao perfil atual."}})

    def api_integrations_update(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "integrations.manage"):
            raise ApiError(403, "Sem permissão para administrar integrações.")
        pid = current_profile_id(actor)
        data = self.read_json()
        changed = []
        now = utc_now()
        with db_connect() as conn:
            for key, secret in self.INTEGRATION_KEYS.items():
                if key not in data:
                    continue
                value = str(data.get(key) or "").strip()
                if value == "••••••••":
                    continue
                if data.get(f"clear_{key}"):
                    value = ""
                if value and key in {"powerbi_embed_url", "generic_webhook_url", "evolution_api_url"} and not value.lower().startswith(("http://", "https://")):
                    raise ApiError(400, f"A URL de {key} precisa começar com http:// ou https://.")
                conn.execute(
                    """INSERT INTO profile_settings(profile_id,key,value,secret,updated_by,updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(profile_id,key) DO UPDATE SET value=excluded.value,secret=excluded.secret,
                       updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (pid, key, value, 1 if secret else 0, actor["id"], now),
                )
                changed.append(key)
        audit(actor["id"], "integrations.update", "settings", pid, {"keys": changed}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Integrações do perfil atualizadas."})

    def api_powerbi_get(self: Any) -> None:
        actor = self.require_permission("powerbi.view")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            row = conn.execute("SELECT value FROM profile_settings WHERE profile_id=? AND key='powerbi_embed_url'", (pid,)).fetchone()
        self.send_json(200, {"ok": True, "embed_url": row["value"] if row else ""})

    def trigger_webhook(self: Any, event: str, payload: dict[str, Any]) -> None:
        profile_id = getattr(REQUEST_CONTEXT, "profile_id", None)
        if not profile_id:
            return original_trigger_webhook(self, event, payload)
        with db_connect() as conn:
            row = conn.execute("SELECT value FROM profile_settings WHERE profile_id=? AND key='generic_webhook_url'", (profile_id,)).fetchone()
        if not row or not row["value"]:
            return
        # Reusa o mecanismo original colocando temporariamente a URL no contexto global seria inseguro;
        # envia diretamente com o mesmo formato.
        import urllib.request
        import threading as _threading
        body = json.dumps({"event": event, "app": ns["APP_NAME"], "version": ns["APP_VERSION"], "timestamp": utc_now(), "profile_id": profile_id, "data": payload}, ensure_ascii=False).encode("utf-8")
        def send() -> None:
            try:
                request = urllib.request.Request(row["value"], data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=6) as response:
                    ns["log"](f"Webhook {event} perfil {profile_id}: HTTP {response.status}")
            except Exception as exc:
                ns["log"](f"Webhook {event} perfil {profile_id} falhou: {exc}")
        _threading.Thread(target=send, daemon=True).start()

    # ------------------------- IA por perfil -------------------------
    def ai_settings_overrides(self: Any) -> dict[str, str]:
        user, _, _ = self.require_user()
        pid = current_profile_id(user)
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT key,value FROM profile_settings WHERE profile_id=? AND key IN ('ai_provider','groq_model','openai_model')",
                (pid,),
            ).fetchall()
        saved = {str(row["key"]): str(row["value"] or "").strip() for row in rows}
        return {"provider": saved.get("ai_provider", ""), "groq_model": saved.get("groq_model", ""), "openai_model": saved.get("openai_model", "")}

    def record_ai_usage(self: Any, *, user_id: int, sale_id: int | None, status: str,
                        provider: str = "", model: str = "", response_id: str = "",
                        fallback_used: bool = False, question_length: int = 0,
                        usage: dict[str, Any] | None = None, error_code: str = "") -> None:
        usage = usage or {}
        profile_id = getattr(REQUEST_CONTEXT, "profile_id", None)
        try:
            with db_connect() as conn:
                conn.execute(
                    """INSERT INTO ai_usage_logs
                    (profile_id,user_id,sale_id,response_id,provider,model,fallback_used,question_length,input_tokens,output_tokens,status,error_code,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (profile_id, user_id, sale_id, response_id or None, provider or None, model or None,
                     1 if fallback_used else 0, max(0, int(question_length)),
                     max(0, int(usage.get("input_tokens") or 0)), max(0, int(usage.get("output_tokens") or 0)),
                     status, error_code or None, utc_now()),
                )
        except Exception as exc:
            ns["log"](f"Falha ao registrar uso da IA: {exc}")

    original_build_ai_context = Handler._build_ai_context

    def build_ai_context(self: Any, user: dict[str, Any], sale_id: int | None = None) -> dict[str, Any]:
        if user.get("profile_type") != "cash_control":
            context = original_build_ai_context(self, user, sale_id)
            context["perfil"] = {"nome": user.get("profile_name"), "tipo": user.get("profile_type")}
            return context
        pid = current_profile_id(user)
        with db_connect() as conn:
            summary = conn.execute(
                """SELECT
                   COALESCE(SUM(CASE WHEN transaction_type='entry' AND active=1 THEN amount ELSE 0 END),0) AS entradas,
                   COALESCE(SUM(CASE WHEN transaction_type='exit' AND active=1 THEN amount ELSE 0 END),0) AS saidas,
                   COUNT(*) AS quantidade
                   FROM cash_transactions WHERE profile_id=?""",
                (pid,),
            ).fetchone()
            categories = conn.execute(
                """SELECT category,
                   COALESCE(SUM(CASE WHEN transaction_type='entry' THEN amount ELSE 0 END),0) AS entradas,
                   COALESCE(SUM(CASE WHEN transaction_type='exit' THEN amount ELSE 0 END),0) AS saidas,
                   COUNT(*) AS quantidade
                   FROM cash_transactions WHERE profile_id=? AND active=1
                   GROUP BY category ORDER BY quantidade DESC LIMIT 30""",
                (pid,),
            ).fetchall()
            recent = conn.execute(
                """SELECT transaction_type,category,description,amount,transaction_date,payment_method
                   FROM cash_transactions WHERE profile_id=? AND active=1
                   ORDER BY transaction_date DESC,id DESC LIMIT 20""",
                (pid,),
            ).fetchall()
        entries = float(summary["entradas"] or 0)
        exits = float(summary["saidas"] or 0)
        return {
            "data_atual": local_today(),
            "perfil": {"nome": user.get("profile_name"), "tipo": "controle_de_caixa"},
            "usuario": {"cargo": user.get("role_name")},
            "indicadores_financeiros": {"entradas": entries, "saidas": exits, "saldo": entries - exits, "lancamentos": int(summary["quantidade"] or 0)},
            "categorias": [dict(row) for row in categories],
            "lancamentos_recentes": [dict(row) for row in recent],
        }

    Handler._ai_settings_overrides = ai_settings_overrides
    Handler._record_ai_usage = record_ai_usage
    Handler._build_ai_context = build_ai_context

    # ------------------------- rotas -------------------------
    def route_get(self: Any) -> None:
        parsed = ns["urlparse"](self.path)
        path = parsed.path.rstrip("/") or "/"
        query = ns["parse_qs"](parsed.query)
        if path == "/api/profiles":
            return self.api_profiles()
        if path == "/api/platform-access":
            return self.api_platform_access()
        if path == "/api/cash":
            return self.api_cash(query)
        if path == "/api/profile-records":
            return self.api_profile_records(query)
        return original_route_get(self)

    def route_write(self: Any, method: str) -> None:
        parsed = ns["urlparse"](self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in {"/api/setup", "/api/login", "/api/logout"}:
            return original_route_write(self, method)
        user, csrf, _ = self.require_user()
        self.check_csrf(csrf)
        if method == "POST" and path == "/api/profiles":
            return self.api_profile_create(user)
        if method == "POST" and path == "/api/platform-roles":
            return self.api_platform_role_create(user)
        if method == "PUT" and path.startswith("/api/platform-roles/"):
            return self.api_platform_role_update(user, path.rsplit("/", 1)[1])
        if method == "POST" and path == "/api/platform-users":
            return self.api_platform_user_create(user)
        if method == "PUT" and path.startswith("/api/platform-users/"):
            return self.api_platform_user_update(user, int(path.rsplit("/", 1)[1]))
        if method == "PUT" and path.startswith("/api/profiles/") and path != "/api/profiles/switch":
            return self.api_profile_update_business(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/profiles/switch":
            return self.api_profile_switch(user)
        if method == "POST" and path == "/api/cash":
            return self.api_cash_create(user)
        if method == "PUT" and path.startswith("/api/cash/"):
            return self.api_cash_update(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/profile-records":
            return self.api_profile_record_create(user)
        if method == "PUT" and path.startswith("/api/profile-records/"):
            return self.api_profile_record_update(user, int(path.rsplit("/", 1)[1]))
        return original_route_write(self, method)

    # Instala métodos e sobrescritas.
    Handler.route_get = route_get
    Handler.route_write = route_write
    Handler.api_profiles = api_profiles
    Handler.require_platform_owner = require_platform_owner
    Handler.api_platform_access = api_platform_access
    Handler.api_platform_role_create = api_platform_role_create
    Handler.api_platform_role_update = api_platform_role_update
    Handler.api_platform_user_create = api_platform_user_create
    Handler.api_platform_user_update = api_platform_user_update
    Handler.api_profile_create = api_profile_create
    Handler.api_profile_update_business = api_profile_update_business
    Handler.api_profile_switch = api_profile_switch
    Handler.api_users_list = api_users_list
    Handler.api_user_create = api_user_create
    Handler.api_user_update = api_user_update
    Handler.api_teams_list = api_teams_list
    Handler.api_team_create = api_team_create
    Handler.api_team_update = api_team_update
    Handler.api_plans_list = api_plans_list
    Handler.api_plan_create = api_plan_create
    Handler.api_plan_update = api_plan_update
    Handler.api_catalogs = api_catalogs
    Handler.api_catalog_create = api_catalog_create
    Handler.api_catalog_update = api_catalog_update
    Handler.api_roles = api_roles
    Handler.api_role_create = api_role_create
    Handler.api_role_update = api_role_update
    Handler.api_sale_create = api_sale_create
    Handler.api_sale_update = api_sale_update
    Handler.api_sale_workflow = api_sale_workflow
    Handler.api_ranking = api_ranking
    Handler.api_daily_analysis = api_daily_analysis
    Handler.api_cash = api_cash
    Handler.api_cash_create = api_cash_create
    Handler.api_cash_update = api_cash_update
    Handler.api_profile_records = api_profile_records
    Handler.api_profile_record_create = api_profile_record_create
    Handler.api_profile_record_update = api_profile_record_update
    Handler.api_dashboard = api_dashboard
    Handler.api_audit = api_audit
    Handler.api_integrations_get = api_integrations_get
    Handler.api_integrations_update = api_integrations_update
    Handler.api_powerbi_get = api_powerbi_get
    Handler.trigger_webhook = trigger_webhook

