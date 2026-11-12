# EstoqueFácil

Sistema web de controle de estoque para pequenos comércios, desenvolvido para o
Projeto Integrador de Programação WEB (CST em Análise e Desenvolvimento de Sistemas, Unisa).

## Funcionalidades

- Login com senha criptografada (hash) e dois perfis: **administrador** e **operador**
- Cadastro de produtos, categorias e fornecedores
- Registro de **entradas** e **saídas**, com bloqueio de saída maior que o saldo
- Histórico completo de movimentações por produto (quem, quando, quanto e por quê)
- Painel com indicadores: valor em estoque, itens abaixo do mínimo, entradas e saídas do mês
- **Relatório de reposição** com consumo médio, ponto de pedido e quantidade sugerida de compra, exportável em CSV
- API JSON (`/api/produtos` e `/api/alertas`)
- Proteção contra CSRF em todos os formulários e consultas SQL parametrizadas (contra SQL Injection)
- Layout responsivo (funciona no celular)

## Tecnologias

| Camada | Tecnologia |
|---|---|
| Back-end | Python 3.11+ e Flask 3 |
| Banco de dados | SQLite (SQL relacional) |
| Front-end | HTML5, CSS3 e JavaScript puro, com templates Jinja2 |
| Testes | pytest (13 testes automatizados) |

## Como executar

```bash
# 1. Instalar as dependências
pip install -r requirements.txt

# 2. Criar o banco com dados de exemplo (16 produtos, 45 dias de movimentações)
python seed.py

# 3. Iniciar o servidor
flask --app app run
```

Acesse http://127.0.0.1:5000

| Perfil | E-mail | Senha |
|---|---|---|
| Administrador | admin@estoque.com | admin123 |
| Operador | operador@estoque.com | operador123 |

Para começar com o banco vazio, use `flask --app app init-db` e crie o primeiro usuário pelo `seed.py` (ou adapte-o).

## Testes

```bash
python -m pytest -v
```

## Estrutura do projeto (padrão MVC)

```
estoque-web/
├── app.py              # Controladores: rotas, autenticação, CSRF, API
├── services.py         # Regras de negócio: movimentação, ponto de pedido, reposição
├── db.py               # Conexão com o banco SQLite
├── schema.sql          # Modelo de dados (tabelas, chaves e restrições)
├── seed.py             # Dados de exemplo
├── templates/          # Visões (HTML + Jinja2)
├── static/css, js/     # Estilo e comportamento no navegador
└── tests/test_app.py   # Testes automatizados
```

## Regras de reposição

- **Consumo médio diário** = saídas dos últimos 30 dias ÷ 30
- **Ponto de pedido** = consumo médio × prazo de reposição (7 dias) + estoque mínimo
- **Quantidade sugerida** (quando o saldo atinge o ponto de pedido) = consumo médio × 30 + estoque mínimo − saldo atual

Os parâmetros ficam no início de `services.py`.
