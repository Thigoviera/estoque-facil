"""Cria o banco de dados com dados de exemplo de um minimercado.

Uso:  python seed.py
Gera 45 dias de movimentações simuladas para que o painel e o
relatório de reposição tenham dados reais para exibir.
"""
import random
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from app import create_app
from db import get_db, init_db

CATEGORIAS = [
    ("Bebidas", "Refrigerantes, sucos e águas"),
    ("Mercearia", "Grãos, massas e enlatados"),
    ("Limpeza", "Produtos de limpeza doméstica"),
    ("Higiene", "Higiene pessoal"),
    ("Laticínios", "Leites, iogurtes e queijos"),
]
FORNECEDORES = [
    ("Distribuidora Paulista Ltda.", "12.345.678/0001-90", "(11) 3456-7890", "vendas@distpaulista.com.br"),
    ("Atacado Bom Preço", "98.765.432/0001-10", "(11) 2345-6789", "pedidos@bompreco.com.br"),
    ("Laticínios Serra Azul", "45.678.123/0001-55", "(11) 4567-8901", "comercial@serraazul.com.br"),
]
# sku, nome, categoria, fornecedor, unidade, custo, venda, mínimo, saída média/dia
PRODUTOS = [
    ("BEB-001", "Refrigerante cola 2 L", 1, 1, "un", 6.20, 9.99, 24, 6),
    ("BEB-002", "Água mineral 500 ml", 1, 1, "un", 0.90, 2.50, 48, 14),
    ("BEB-003", "Suco de laranja 1 L", 1, 2, "un", 4.10, 7.49, 12, 3),
    ("MER-001", "Arroz tipo 1 5 kg", 2, 2, "pct", 19.50, 27.90, 15, 4),
    ("MER-002", "Feijão carioca 1 kg", 2, 2, "pct", 5.80, 8.99, 20, 5),
    ("MER-003", "Macarrão espaguete 500 g", 2, 2, "pct", 2.90, 4.79, 20, 4),
    ("MER-004", "Óleo de soja 900 ml", 2, 1, "un", 5.40, 7.99, 18, 4),
    ("MER-005", "Café torrado 500 g", 2, 1, "pct", 14.20, 21.90, 10, 3),
    ("LIM-001", "Detergente líquido 500 ml", 3, 2, "un", 1.70, 2.99, 24, 3),
    ("LIM-002", "Sabão em pó 1 kg", 3, 2, "cx", 9.80, 15.90, 10, 2),
    ("LIM-003", "Água sanitária 2 L", 3, 1, "un", 3.90, 6.49, 12, 2),
    ("HIG-001", "Papel higiênico 12 rolos", 4, 2, "pct", 15.90, 23.90, 10, 2),
    ("HIG-002", "Sabonete 90 g", 4, 1, "un", 1.40, 2.59, 30, 4),
    ("LAT-001", "Leite integral 1 L", 5, 3, "un", 3.80, 5.69, 36, 10),
    ("LAT-002", "Iogurte natural 170 g", 5, 3, "un", 1.90, 3.49, 20, 5),
    ("LAT-003", "Queijo muçarela kg", 5, 3, "kg", 32.00, 49.90, 4, 1),
]
DIAS = 45


def popular():
    random.seed(42)  # dados sempre iguais a cada execução
    init_db()
    db = get_db()
    db.executemany(
        "INSERT INTO usuarios (nome, email, senha_hash, perfil) VALUES (?,?,?,?)",
        [("Administrador", "admin@estoque.com", generate_password_hash("admin123"), "admin"),
         ("Operador de Caixa", "operador@estoque.com", generate_password_hash("operador123"), "operador")],
    )
    db.executemany("INSERT INTO categorias (nome, descricao) VALUES (?,?)", CATEGORIAS)
    db.executemany("INSERT INTO fornecedores (nome, cnpj, telefone, email) VALUES (?,?,?,?)", FORNECEDORES)

    inicio = datetime.now() - timedelta(days=DIAS)
    for i, (sku, nome, cat, forn, un, custo, venda, minimo, media) in enumerate(PRODUTOS, start=1):
        db.execute(
            """INSERT INTO produtos (sku, nome, categoria_id, fornecedor_id, unidade,
                   preco_custo, preco_venda, estoque_minimo) VALUES (?,?,?,?,?,?,?,?)""",
            (sku, nome, cat, forn, un, custo, venda, minimo),
        )
        saldo = 0
        movs = []

        def mov(tipo, qtd, quando, motivo, usuario):
            movs.append((i, usuario, tipo, qtd, motivo, quando.strftime("%Y-%m-%d %H:%M:%S")))

        compra = media * 15 + minimo
        mov("entrada", compra, inicio.replace(hour=8, minute=5), "Estoque inicial", 1)
        saldo += compra
        # alguns produtos deixam de ser repostos nos últimos dias -> ficam críticos
        para_de_repor = i % 4 == 0
        for d in range(1, DIAS + 1):
            dia = inicio + timedelta(days=d)
            qtd = max(0, round(random.gauss(media, media * 0.35)))
            qtd = min(qtd, saldo)
            if qtd:
                mov("saida", qtd, dia.replace(hour=random.randint(9, 19), minute=random.randint(0, 59)),
                    "Venda balcão", 2)
                saldo -= qtd
            ultimos_dias = d > DIAS - 12
            if saldo <= minimo + media * 8 and not (para_de_repor and ultimos_dias):
                reposicao = media * 16
                mov("entrada", reposicao, dia.replace(hour=20, minute=30),
                    f"NF {random.randint(10000, 99999)}", 1)
                saldo += reposicao
        db.executemany(
            "INSERT INTO movimentacoes (produto_id, usuario_id, tipo, quantidade, motivo, data)"
            " VALUES (?,?,?,?,?,?)", movs)
        db.execute("UPDATE produtos SET quantidade = ? WHERE id = ?", (saldo, i))
    db.commit()


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        popular()
        print("Banco criado com dados de exemplo.")
        print("Login: admin@estoque.com / admin123  (ou operador@estoque.com / operador123)")
