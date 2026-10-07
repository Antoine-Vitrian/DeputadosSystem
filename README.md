# Radar Legislativo

MVP de transparência legislativa com Django, Django REST Framework e dados públicos.

## Requisitos

- Python 3.13+
- PostgreSQL opcional (SQLite é usado por padrão no desenvolvimento)

## Executar

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 manage.py migrate
py -3.13 manage.py runserver
```

Abra `http://127.0.0.1:8000/`.

## Dados

Para testar a interface sem dados externos:

```powershell
py -3.13 manage.py seed_mock
```

Os registros são identificados como `MOCK` e não representam fatos reais.

Para importar a página mais recente de projetos e a lista atual de deputados:

```powershell
py -3.13 manage.py sync_camara
```

Para atualizar os dados legislativos diariamente e as notícias a cada hora:

```powershell
py -3.13 manage.py sync_camara_diario
py -3.13 manage.py sync_noticias
```

Agende `sync_camara_diario` uma vez por dia e `sync_noticias` a cada hora no Agendador de Tarefas do Windows. A página inicial também atualiza o feed na primeira visita após uma hora.

Para importar mais páginas ou despesas explicitamente:

```powershell
py -3.13 manage.py sync_camara --max-pages 5
py -3.13 manage.py sync_camara_diario --com-despesas
```

Para carregar as votações nominais de um ano inteiro e completar o contexto exibido nas páginas de detalhe:

```powershell
py -3.13 manage.py sync_votacoes_ano --ano 2026
py -3.13 manage.py atualizar_contexto_votacoes
py -3.13 manage.py atualizar_contexto_projetos
```

A fonte é a API oficial de Dados Abertos: https://dadosabertos.camara.leg.br/
As notícias vêm exclusivamente do RSS oficial do Poder360: https://www.poder360.com.br/feed/

## Rotas principais

- `/` homepage
- `/dashboard/` indicadores
- `/parlamentares/` parlamentares
- `/votacoes/` últimas votações; busca por intervalo desde 2023
- `/projetos/<id>/` resumo de uma proposição
- `/pesquisa/` busca global
- `/entenda/` regras da eleição e o que é PL, PEC, emenda e os outros tipos
- `/entrar/` tela de login
- `/api/v1/` API para clientes web e mobile
- `/admin/` administração Django

## PostgreSQL

Defina `DATABASE_URL` antes de iniciar, por exemplo:

```text
postgresql://usuario:senha@localhost:5432/radar_legislativo
```

## Princípios de dados

- Indicadores são descritivos e não classificam parlamentares.
- Cada importação registra a fonte dos dados.
- Dados MOCK nunca são misturados silenciosamente aos dados oficiais.
- Novas instituições devem entrar por adaptadores em `legislature/management/commands/` ou em uma camada `services` dedicada.
