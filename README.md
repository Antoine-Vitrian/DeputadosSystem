# Radar Legislativo

MVP de transparência legislativa com Django, Django REST Framework e dados públicos oficiais.

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

## Executar com Docker

É necessário ter o Docker Desktop instalado e em execução. No PowerShell, primeiro entre na pasta do projeto. Se ainda não houver um `.env` na raiz, crie-o copiando o exemplo; o comando abaixo preserva qualquer `.env` já configurado. Depois, suba a aplicação e o PostgreSQL:

```powershell
Set-Location "$HOME\Desktop\pessoal\analise_deputados"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up --build
```

Quando a aplicação estiver pronta, abra `http://localhost:8080/`. A porta 8080 no computador encaminha para a porta 8000 do Django no contêiner, evitando conflito com outro servidor local que já usa a porta 8000. O Compose espera o PostgreSQL ficar saudável e aplica as migrações do Django antes de iniciar o servidor.

Para executar em segundo plano e acompanhar os logs:

```powershell
docker compose up --build -d
docker compose logs -f web
```

Para parar os serviços:

```powershell
docker compose down
```

O banco fica armazenado no volume `postgres_data` e é preservado ao parar os serviços. Para apagar também o banco e todos os dados persistidos, use `docker compose down --volumes`.

Para popular o banco com dados fictícios de demonstração:

```powershell
docker compose exec web python manage.py seed_mock
```

O `.env.example` contém valores apenas para desenvolvimento local. Antes de expor o sistema, configure uma `DJANGO_SECRET_KEY` forte e privada, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS` com os domínios autorizados e uma senha segura para o PostgreSQL; mantenha `DATABASE_URL` coerente com as credenciais do banco.

## Deploy no Render

Crie um serviço **Web Service** com runtime Python e configure:

- **Build Command:** `pip install -r requirements.txt && python manage.py collectstatic --no-input`
- **Start Command:** `python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`

Adicione as variáveis de ambiente ao serviço:

- `DJANGO_SECRET_KEY`: uma chave secreta forte e exclusiva para produção
- `DJANGO_DEBUG`: `0`
- `DJANGO_ALLOWED_HOSTS`: `.onrender.com`
- `DATABASE_URL`: URL de conexão do PostgreSQL

O banco também pode ficar no Supabase, mantendo o Django hospedado no Render. No Supabase, abra **Connect → Session pooler** e copie a URL de conexão. Para o deploy, defina essa URL como `DATABASE_URL` no Render e confirme que ela usa `sslmode=require`. O serviço do Render e o projeto Supabase devem estar em regiões próximas para reduzir a latência.

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

Agende `sync_camara_diario` uma vez por dia e `sync_noticias` a cada hora no Agendador de Tarefas do Windows. A página inicial atualiza as notícias a cada hora e as páginas de início e votações atualizam os dados recentes da Câmara automaticamente quando a última sincronização tem mais de uma hora.

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
A nota acumulada exibida no perfil do parlamentar vem do Ranking dos Políticos: https://ranking.org.br/; a consulta é armazenada em cache por seis horas e vinculada ao perfil somente após validar o nome público.

## Rotas principais

- `/` início com notícias e atividade legislativa recente
- `/dashboard/` indicadores
- `/parlamentares/` parlamentares atuais ou deputados de um ano selecionado (2010 até o ano atual); cada perfil consulta o histórico de proposições e permite filtrar por tipo, ano e mês
- `/votacoes/` últimas 10 votações nominais; busca no acervo por intervalo desde 2010
- `/projetos/<id>/` resumo de uma proposição
- `/pesquisa/` busca global
- `/entenda/` regras da eleição e o que é PL, PEC, emenda e os outros tipos
- `/entrar/` aviso de login temporariamente indisponível
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
