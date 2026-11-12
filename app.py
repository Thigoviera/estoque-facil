"""EstoqueFácil - sistema web de controle de estoque para pequenos comércios.

Aplicação Flask organizada no padrão MVC:
  * Model      -> schema.sql + db.py + services.py (dados e regras de negócio)
  * View       -> templates/ (HTML com Jinja2) + static/ (CSS e JavaScript)
  * Controller -> as rotas definidas neste arquivo

Para executar:
    pip install -r requirements.txt
    python seed.py          # cria o banco com dados de exemplo
    flask --app app run     # abre em http://127.0.0.1:5000
Usuário de teste: admin@estoque.com / admin123
"""
import csv
import io
import os
import secrets
import sqlite3
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db
from db import get_db
from services import (EstoqueError, indicadores, registrar_movimentacao,
                      relatorio_reposicao)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao"),
        DATABASE=os.path.join(app.root_path, "estoque.db"),
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    registrar_seguranca(app)
    registrar_filtros(app)
    registrar_rotas(app)
    return app


# ----------------------------------------------------------------------
# Segurança: sessão de login, perfis e proteção contra CSRF
# ----------------------------------------------------------------------
def login_obrigatorio(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.usuario is None:
            return redirect(url_for("login", proximo=request.path))
        return view(*args, **kwargs)
    return wrapper


def somente_admin(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.usuario is None or g.usuario["perfil"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def registrar_seguranca(app: Flask) -> None:
    @app.before_request
    def carregar_usuario():
        uid = session.get("usuario_id")
        g.usuario = None
        if uid is not None:
            g.usuario = get_db().execute(
                "SELECT id, nome, email, perfil FROM usuarios WHERE id = ?", (uid,)
            ).fetchone()

    @app.before_request
    def verificar_csrf():
        # Todo formulário enviado por POST precisa devolver o token da sessão.
        if request.method == "POST" and not app.config.get("TESTING_SEM_CSRF"):
            token = session.get("csrf_token")
            if not token or request.form.get("csrf_token") != token:
                abort(400, description="Token de segurança inválido. Recarregue a página.")

    @app.context_processor
    def injetar_csrf():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return {"csrf_token": session["csrf_token"]}


def registrar_filtros(app: Flask) -> None:
    @app.template_filter("moeda")
    def moeda(valor):
        valor = valor or 0
        texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {texto}"

    @app.template_filter("data_br")
    def data_br(texto):
        # "2026-11-11 20:30:00" -> "11/11/2026 20:30"
        if not texto:
            return ""
        d, _, h = texto.partition(" ")
        a, m, dia = d.split("-")
        return f"{dia}/{m}/{a} {h[:5]}".strip()


# ----------------------------------------------------------------------
# Funções auxiliares de formulário
# ----------------------------------------------------------------------
def inteiro(campo: str, padrao=None, minimo=0):
    valor = request.form.get(campo, "").strip()
    if valor == "":
        return padrao
    try:
        numero = int(valor)
    except ValueError:
        raise EstoqueError(f"O campo \"{campo.replace('_', ' ')}\" deve ser um número inteiro.")
    if numero < minimo:
        raise EstoqueError(f"O campo \"{campo.replace('_', ' ')}\" não pode ser menor que {minimo}.")
    return numero


def decimal(campo: str) -> float:
    """Aceita tanto "1234.56" quanto o formato brasileiro "1.234,56"."""
    valor = request.form.get(campo, "").strip()
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    if valor == "":
        return 0.0
    try:
        numero = float(valor)
    except ValueError:
        raise EstoqueError(f"O campo \"{campo.replace('_', ' ')}\" deve ser um valor numérico.")
    if numero < 0:
        raise EstoqueError(f"O campo \"{campo.replace('_', ' ')}\" não pode ser negativo.")
    return round(numero, 2)


def opcoes():
    """Listas usadas nos <select> dos formulários."""
    banco = get_db()
    return {
        "categorias": banco.execute("SELECT id, nome FROM categorias ORDER BY nome").fetchall(),
        "fornecedores": banco.execute("SELECT id, nome FROM fornecedores ORDER BY nome").fetchall(),
    }


# ----------------------------------------------------------------------
# Rotas (controladores)
# ----------------------------------------------------------------------
def registrar_rotas(app: Flask) -> None:

    # ---------------- Autenticação ----------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            senha = request.form.get("senha", "")
            usuario = get_db().execute(
                "SELECT * FROM usuarios WHERE email = ?", (email,)
            ).fetchone()
            if usuario and check_password_hash(usuario["senha_hash"], senha):
                csrf = session.get("csrf_token")
                session.clear()  # evita fixação de sessão
                session["usuario_id"] = usuario["id"]
                session["csrf_token"] = csrf or secrets.token_hex(16)
                destino = request.args.get("proximo", "")
                return redirect(destino if destino.startswith("/") else url_for("painel"))
            flash("E-mail ou senha incorretos.", "erro")
        return render_template("login.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        flash("Sessão encerrada.", "ok")
        return redirect(url_for("login"))

    # ---------------- Painel ----------------
    @app.route("/")
    @login_obrigatorio
    def painel():
        banco = get_db()
        ultimas = banco.execute(
            """SELECT m.*, p.nome AS produto, u.nome AS usuario
                 FROM movimentacoes m
                 JOIN produtos p ON p.id = m.produto_id
                 LEFT JOIN usuarios u ON u.id = m.usuario_id
                ORDER BY m.data DESC, m.id DESC LIMIT 8"""
        ).fetchall()
        alertas = [s for s in relatorio_reposicao() if s.precisa_comprar][:6]
        return render_template("painel.html", ind=indicadores(),
                               ultimas=ultimas, alertas=alertas)

    # ---------------- Produtos ----------------
    @app.route("/produtos")
    @login_obrigatorio
    def produtos():
        busca = request.args.get("q", "").strip()
        categoria = request.args.get("categoria", type=int)
        sql = """SELECT p.*, c.nome AS categoria, f.nome AS fornecedor
                   FROM produtos p
                   LEFT JOIN categorias c ON c.id = p.categoria_id
                   LEFT JOIN fornecedores f ON f.id = p.fornecedor_id
                  WHERE p.ativo = 1"""
        params: list = []
        if busca:
            sql += " AND (p.nome LIKE ? OR p.sku LIKE ?)"
            params += [f"%{busca}%", f"%{busca}%"]
        if categoria:
            sql += " AND p.categoria_id = ?"
            params.append(categoria)
        sql += " ORDER BY p.nome"
        lista = get_db().execute(sql, params).fetchall()
        return render_template("produtos/lista.html", produtos=lista, busca=busca,
                               categoria=categoria, **opcoes())

    @app.route("/produtos/novo", methods=["GET", "POST"])
    @app.route("/produtos/<int:produto_id>/editar", methods=["GET", "POST"])
    @login_obrigatorio
    def produto_form(produto_id=None):
        banco = get_db()
        produto = None
        if produto_id:
            produto = banco.execute(
                "SELECT * FROM produtos WHERE id = ? AND ativo = 1", (produto_id,)
            ).fetchone() or abort(404)

        if request.method == "POST":
            try:
                dados = {
                    "sku": request.form.get("sku", "").strip().upper(),
                    "nome": request.form.get("nome", "").strip(),
                    "categoria_id": inteiro("categoria_id"),
                    "fornecedor_id": inteiro("fornecedor_id"),
                    "unidade": request.form.get("unidade", "un").strip() or "un",
                    "preco_custo": decimal("preco_custo"),
                    "preco_venda": decimal("preco_venda"),
                    "estoque_minimo": inteiro("estoque_minimo", 0),
                }
                if not dados["sku"] or not dados["nome"]:
                    raise EstoqueError("Código (SKU) e nome são obrigatórios.")
                if produto is None:
                    inicial = inteiro("quantidade_inicial", 0)
                    with banco:
                        cur = banco.execute(
                            """INSERT INTO produtos (sku, nome, categoria_id, fornecedor_id,
                                   unidade, preco_custo, preco_venda, estoque_minimo)
                               VALUES (:sku, :nome, :categoria_id, :fornecedor_id,
                                   :unidade, :preco_custo, :preco_venda, :estoque_minimo)""",
                            dados,
                        )
                    if inicial:
                        registrar_movimentacao(cur.lastrowid, "entrada", inicial,
                                               "Estoque inicial", g.usuario["id"])
                    flash(f"Produto \"{dados['nome']}\" cadastrado.", "ok")
                else:
                    with banco:
                        banco.execute(
                            """UPDATE produtos SET sku=:sku, nome=:nome,
                                   categoria_id=:categoria_id, fornecedor_id=:fornecedor_id,
                                   unidade=:unidade, preco_custo=:preco_custo,
                                   preco_venda=:preco_venda, estoque_minimo=:estoque_minimo
                               WHERE id=:id""",
                            {**dados, "id": produto_id},
                        )
                    flash(f"Produto \"{dados['nome']}\" atualizado.", "ok")
                return redirect(url_for("produtos"))
            except EstoqueError as erro:
                flash(str(erro), "erro")
            except sqlite3.IntegrityError:
                flash("Já existe um produto com esse código (SKU).", "erro")
        return render_template("produtos/form.html", produto=produto,
                               form=request.form, **opcoes())

    @app.route("/produtos/<int:produto_id>")
    @login_obrigatorio
    def produto_detalhe(produto_id):
        banco = get_db()
        produto = banco.execute(
            """SELECT p.*, c.nome AS categoria, f.nome AS fornecedor
                 FROM produtos p
                 LEFT JOIN categorias c ON c.id = p.categoria_id
                 LEFT JOIN fornecedores f ON f.id = p.fornecedor_id
                WHERE p.id = ?""", (produto_id,)
        ).fetchone() or abort(404)
        historico = banco.execute(
            """SELECT m.*, u.nome AS usuario FROM movimentacoes m
                 LEFT JOIN usuarios u ON u.id = m.usuario_id
                WHERE m.produto_id = ? ORDER BY m.data DESC, m.id DESC""", (produto_id,)
        ).fetchall()
        return render_template("produtos/detalhe.html", produto=produto, historico=historico)

    @app.route("/produtos/<int:produto_id>/excluir", methods=["POST"])
    @somente_admin
    def produto_excluir(produto_id):
        # Exclusão lógica: o produto some das listas mas o histórico é mantido.
        banco = get_db()
        with banco:
            banco.execute("UPDATE produtos SET ativo = 0 WHERE id = ?", (produto_id,))
        flash("Produto removido do catálogo (o histórico foi mantido).", "ok")
        return redirect(url_for("produtos"))

    # ---------------- Categorias e fornecedores ----------------
    def cadastro_simples(tabela, fk, campos, titulo, template):
        """Gera as rotas de listagem/criação/exclusão de tabelas simples."""

        @login_obrigatorio
        def listar():
            banco = get_db()
            if request.method == "POST":
                valores = {c: request.form.get(c, "").strip() or None for c in campos}
                if not valores["nome"]:
                    flash("O nome é obrigatório.", "erro")
                else:
                    try:
                        with banco:
                            banco.execute(
                                f"INSERT INTO {tabela} ({', '.join(campos)}) "
                                f"VALUES ({', '.join('?' for _ in campos)})",
                                list(valores.values()),
                            )
                        flash(f"{titulo} \"{valores['nome']}\" cadastrado(a).", "ok")
                        return redirect(request.path)
                    except sqlite3.IntegrityError:
                        flash(f"Já existe um(a) {titulo.lower()} com esses dados.", "erro")
            itens = banco.execute(
                f"""SELECT t.*, (SELECT COUNT(*) FROM produtos p
                                  WHERE p.{fk} = t.id
                                    AND p.ativo = 1) AS total_produtos
                      FROM {tabela} t ORDER BY t.nome"""
            ).fetchall()
            return render_template(template, itens=itens, form=request.form)

        @somente_admin
        def excluir(item_id):
            banco = get_db()
            with banco:
                banco.execute(f"DELETE FROM {tabela} WHERE id = ?", (item_id,))
            flash(f"{titulo} excluído(a). Os produtos ligados a ele(a) ficaram sem vínculo.", "ok")
            return redirect(url_for(tabela))

        app.add_url_rule(f"/{tabela}", tabela, listar, methods=["GET", "POST"])
        app.add_url_rule(f"/{tabela}/<int:item_id>/excluir", f"{tabela}_excluir",
                         excluir, methods=["POST"])

    cadastro_simples("categorias", "categoria_id", ["nome", "descricao"],
                     "Categoria", "categorias.html")
    cadastro_simples("fornecedores", "fornecedor_id", ["nome", "cnpj", "telefone", "email"],
                     "Fornecedor", "fornecedores.html")

    # ---------------- Movimentações ----------------
    @app.route("/movimentacoes")
    @login_obrigatorio
    def movimentacoes():
        tipo = request.args.get("tipo", "")
        sql = """SELECT m.*, p.nome AS produto, p.sku, u.nome AS usuario
                   FROM movimentacoes m
                   JOIN produtos p ON p.id = m.produto_id
                   LEFT JOIN usuarios u ON u.id = m.usuario_id"""
        params = []
        if tipo in ("entrada", "saida"):
            sql += " WHERE m.tipo = ?"
            params.append(tipo)
        sql += " ORDER BY m.data DESC, m.id DESC LIMIT 200"
        lista = get_db().execute(sql, params).fetchall()
        return render_template("movimentacoes/lista.html", movimentacoes=lista, tipo=tipo)

    @app.route("/movimentacoes/nova", methods=["GET", "POST"])
    @login_obrigatorio
    def movimentacao_nova():
        banco = get_db()
        if request.method == "POST":
            try:
                produto_id = inteiro("produto_id")
                if not produto_id:
                    raise EstoqueError("Selecione um produto.")
                saldo = registrar_movimentacao(
                    produto_id,
                    request.form.get("tipo", ""),
                    inteiro("quantidade", 0, minimo=1),
                    request.form.get("motivo", "").strip(),
                    g.usuario["id"],
                )
                flash(f"Movimentação registrada. Novo saldo: {saldo}.", "ok")
                return redirect(url_for("movimentacoes"))
            except EstoqueError as erro:
                flash(str(erro), "erro")
        lista = banco.execute(
            "SELECT id, sku, nome, quantidade, unidade FROM produtos WHERE ativo = 1 ORDER BY nome"
        ).fetchall()
        return render_template("movimentacoes/form.html", produtos=lista, form=request.form,
                               produto_sel=request.args.get("produto", type=int))

    # ---------------- Relatório de reposição ----------------
    @app.route("/relatorios/reposicao")
    @login_obrigatorio
    def relatorio():
        somente = request.args.get("todos") != "1"
        itens = relatorio_reposicao(somente_criticos=somente)
        if request.args.get("formato") == "csv":
            saida = io.StringIO()
            escritor = csv.writer(saida, delimiter=";")
            escritor.writerow(["SKU", "Produto", "Fornecedor", "Saldo", "Estoque mínimo",
                               "Ponto de pedido", "Consumo/dia", "Cobertura (dias)",
                               "Comprar", "Custo estimado"])
            for s in itens:
                escritor.writerow([s.sku, s.nome, s.fornecedor or "", s.quantidade,
                                   s.estoque_minimo, s.ponto_pedido,
                                   str(s.consumo_diario).replace(".", ","),
                                   "" if s.dias_cobertura is None else str(s.dias_cobertura).replace(".", ","),
                                   s.sugerido, f"{s.custo_estimado:.2f}".replace(".", ",")])
            return Response("﻿" + saida.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition":
                                     "attachment; filename=reposicao.csv"})
        total = sum(s.custo_estimado for s in itens)
        return render_template("relatorio.html", itens=itens, total=total, somente=somente)

    # ---------------- Usuários (somente administrador) ----------------
    @app.route("/usuarios", methods=["GET", "POST"])
    @somente_admin
    def usuarios():
        banco = get_db()
        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            email = request.form.get("email", "").strip().lower()
            senha = request.form.get("senha", "")
            perfil = request.form.get("perfil", "operador")
            if not nome or "@" not in email or len(senha) < 6:
                flash("Preencha nome, e-mail válido e senha com pelo menos 6 caracteres.", "erro")
            elif perfil not in ("admin", "operador"):
                flash("Perfil inválido.", "erro")
            else:
                try:
                    with banco:
                        banco.execute(
                            "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (?,?,?,?)",
                            (nome, email, generate_password_hash(senha), perfil),
                        )
                    flash(f"Usuário {nome} criado.", "ok")
                    return redirect(url_for("usuarios"))
                except sqlite3.IntegrityError:
                    flash("Já existe um usuário com esse e-mail.", "erro")
        lista = banco.execute(
            "SELECT id, nome, email, perfil, criado_em FROM usuarios ORDER BY nome"
        ).fetchall()
        return render_template("usuarios.html", usuarios=lista, form=request.form)

    # ---------------- API REST (JSON) ----------------
    @app.route("/api/produtos")
    @login_obrigatorio
    def api_produtos():
        linhas = get_db().execute(
            """SELECT p.id, p.sku, p.nome, p.quantidade, p.estoque_minimo, p.unidade,
                      p.preco_venda, c.nome AS categoria
                 FROM produtos p LEFT JOIN categorias c ON c.id = p.categoria_id
                WHERE p.ativo = 1 ORDER BY p.nome"""
        ).fetchall()
        return jsonify([dict(l) for l in linhas])

    @app.route("/api/alertas")
    @login_obrigatorio
    def api_alertas():
        return jsonify([
            {"sku": s.sku, "nome": s.nome, "saldo": s.quantidade,
             "estoque_minimo": s.estoque_minimo, "sugerido": s.sugerido}
            for s in relatorio_reposicao() if s.precisa_comprar
        ])

    # ---------------- Páginas de erro ----------------
    @app.errorhandler(403)
    def proibido(_):
        return render_template("erro.html", codigo=403,
                               mensagem="Você não tem permissão para esta ação."), 403

    @app.errorhandler(404)
    def nao_encontrado(_):
        return render_template("erro.html", codigo=404,
                               mensagem="Página ou registro não encontrado."), 404

    @app.errorhandler(400)
    def requisicao_invalida(e):
        return render_template("erro.html", codigo=400, mensagem=e.description), 400


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
