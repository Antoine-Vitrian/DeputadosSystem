# Radar Legislativo

MVP de transparência legislativa com Django, Django REST Framework e dados públicos oficiais

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

O Docker Compose inicia dois containers: `web` (Django, que também serve o frontend) e `db` (PostgreSQL 17). É necessário ter o Docker Desktop instalado e em execução no Windows, ou Docker Engine e o plugin Docker Compose no Linux.

### 1. Abra um terminal na pasta do projeto

No PowerShell:

```powershell
Set-Location "$HOME\Desktop\pessoal\analise_deputados"
```

No Ubuntu/WSL, se o projeto estiver na pasta `Desktop\pessoal\analise_deputados` do Windows, substitua `NOME_DO_USUARIO` pelo nome da pasta do seu usuário em `C:\Users`:

```bash
cd /mnt/c/Users/NOME_DO_USUARIO/Desktop/pessoal/analise_deputados
```

Confirme que está na pasta que contém `Dockerfile` e `compose.yaml`:

```text
Dockerfile
compose.yaml
```

### 2. Configure o ambiente

Se ainda não existir um `.env` na raiz, copie o exemplo. No PowerShell:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

No Ubuntu/WSL:

```bash
if [ ! -f .env ]; then cp .env.example .env; fi
```

Abra `.env` (`notepad .env` no PowerShell ou `nano .env` no Ubuntu) e configure `POSTGRES_PASSWORD` com uma senha sua. Use a mesma senha em `DATABASE_URL`. Exemplo de formato:

```dotenv
POSTGRES_DB=radar_legislativo
POSTGRES_USER=postgres
POSTGRES_PASSWORD=escolha-uma-senha
DATABASE_URL=postgres://postgres:escolha-uma-senha@db:5432/radar_legislativo
```

Mantenha também `DJANGO_SECRET_KEY`, `DJANGO_DEBUG` e `DJANGO_ALLOWED_HOSTS` no arquivo. Para desenvolvimento local, os valores de `.env.example` permitem acessar pelo endereço local; não use a chave ou senha de exemplo em um serviço exposto publicamente. O hostname `db` na `DATABASE_URL` é o nome do serviço PostgreSQL dentro do Compose; não troque por `localhost`.

Se a senha tiver caracteres especiais, codifique-os para URL dentro de `DATABASE_URL` (por exemplo, `@` como `%40`). Se já existir um volume PostgreSQL com dados, mantenha as credenciais que foram usadas quando esse banco foi criado; mudar `.env` não altera automaticamente a senha dentro de um banco existente.

### 3. Construa e inicie a aplicação e o banco

```bash
docker compose up --build -d
```

O comando constrói a imagem do Django e inicia os dois containers em segundo plano. O Compose espera o PostgreSQL ficar saudável; em seguida, o container `web` aplica as migrações do Django e inicia o Gunicorn.

### 4. Confira o estado e acesse o sistema

```bash
docker compose ps
docker compose logs --tail 50 web
```

Confirme que `db` aparece como `healthy` e `web` como `Up`. A aplicação fica disponível em <http://localhost:8080/>. A porta `8080` do computador encaminha para a porta `8000` do Django no container. O endpoint da API também fica disponível em <http://localhost:8080/api/v1/>.

Para acompanhar os logs ao vivo:

```bash
docker compose logs -f web
```

Para conferir os logs do PostgreSQL:

```powershell
docker compose logs -f db
```

### Dados e operações úteis

O banco começa vazio. Para inserir dados fictícios de demonstração:

```powershell
docker compose exec web python manage.py seed_mock
```

Para importar dados oficiais da Câmara e notícias (requer acesso à internet):

```powershell
docker compose exec web python manage.py sync_camara
docker compose exec web python manage.py sync_noticias
```

Na página inicial, o feed de notícias é atualizado no Poder360 quando já passou uma hora desde a última sincronização; se a fonte estiver indisponível, as notícias salvas continuam sendo exibidas. As páginas de parlamentares e votações usam os dados salvos no PostgreSQL e não esperam pela Câmara para abrir. A página de votação carrega votos individuais e detalhes somente quando uma votação é aberta.

```powershell
docker compose exec web python manage.py sync_parlamentares
docker compose exec web python manage.py sync_camara_diario
```

O workflow `Atualizar dados da Câmara` no GitHub Actions executa `sync_camara_diario` a cada hora e `sync_parlamentares` diariamente, sem precisar contratar Cron Jobs do Render. Para habilitá-lo, adicione `DATABASE_URL` em **GitHub → Settings → Secrets and variables → Actions → New repository secret**. Use uma URL externa do PostgreSQL acessível pelo GitHub Actions, com SSL habilitado quando exigido pelo provedor. Workflows agendados rodam a partir da branch padrão do repositório; faça merge para `main` para ativar o agendamento. Também é possível iniciá-lo manualmente em **Actions → Atualizar dados da Câmara → Run workflow**. Rode-o manualmente uma vez para preencher os dados iniciais.

Para parar os serviços sem apagar o banco:

```powershell
docker compose down
```

Os dados do PostgreSQL ficam no volume `postgres_data` e são preservados por `docker compose down`. Para iniciar novamente, use `docker compose up -d`. Para reconstruir a aplicação depois de alterar o código, use `docker compose up --build -d`.

**Atenção:** `docker compose down --volumes` remove o volume do banco e apaga os dados persistidos. Use somente se quiser apagar o banco intencionalmente.

Se um serviço não iniciar, confira `docker compose ps` e `docker compose logs db` ou `docker compose logs web`. Verifique também se o `.env` existe e se a senha em `POSTGRES_PASSWORD` corresponde à senha incluída em `DATABASE_URL`.

O Docker Hub armazena imagens, mas não inicia os containers. Para executar o sistema completo localmente, use os comandos do Compose acima; eles iniciam tanto a aplicação quanto o PostgreSQL.

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

Para atualizar os dados fora das requisições das páginas:

```powershell
py -3.13 manage.py sync_parlamentares
py -3.13 manage.py sync_camara_diario
```

O workflow `Atualizar dados da Câmara` no GitHub Actions executa `sync_parlamentares` diariamente e `sync_camara_diario` a cada hora (UTC). Configure o secret `DATABASE_URL` no repositório GitHub e use a URL externa do PostgreSQL. Workflows agendados só rodam na branch padrão; faça merge dessas alterações para `main` para habilitar as execuções periódicas. A sincronização atualiza o banco em segundo plano; as páginas mostram os dados salvos sem esperar pela API da Câmara. A lista exibe as dez votações nominais mais recentes; votos individuais e detalhes completos são carregados ao abrir uma votação. Para preencher os dados imediatamente, execute os comandos manualmente uma vez pelo Render Shell ou inicie o workflow em **Actions → Atualizar dados da Câmara → Run workflow**.

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
