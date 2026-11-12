"""Regras de negócio do estoque.

Ficam separadas das rotas para que possam ser testadas isoladamente e
reaproveitadas tanto pelas páginas HTML quanto pela API JSON.
"""
import math
from dataclasses import dataclass

from db import get_db

DIAS_ANALISE = 30      # janela usada para calcular o consumo médio
PRAZO_REPOSICAO = 7    # dias que o fornecedor leva para entregar (lead time)
DIAS_COBERTURA = 30    # por quantos dias a compra sugerida deve durar


class EstoqueError(ValueError):
    """Erro de regra de negócio (mensagem pronta para mostrar ao usuário)."""


def registrar_movimentacao(produto_id: int, tipo: str, quantidade: int,
                           motivo: str, usuario_id: int | None) -> int:
    """Registra uma entrada ou saída e atualiza o saldo do produto.

    As duas operações (inserir a movimentação e alterar a quantidade)
    acontecem na mesma transação: ou as duas são gravadas, ou nenhuma.
    Retorna o novo saldo do produto.
    """
    if tipo not in ("entrada", "saida"):
        raise EstoqueError("Tipo de movimentação inválido.")
    if not isinstance(quantidade, int) or quantidade <= 0:
        raise EstoqueError("A quantidade deve ser um número inteiro maior que zero.")

    db = get_db()
    produto = db.execute(
        "SELECT id, nome, quantidade, ativo FROM produtos WHERE id = ?",
        (produto_id,),
    ).fetchone()
    if produto is None or not produto["ativo"]:
        raise EstoqueError("Produto não encontrado ou inativo.")

    delta = quantidade if tipo == "entrada" else -quantidade
    novo_saldo = produto["quantidade"] + delta
    if novo_saldo < 0:
        raise EstoqueError(
            f"Saldo insuficiente: há {produto['quantidade']} unidade(s) de "
            f"\"{produto['nome']}\" e a saída pedida é de {quantidade}."
        )

    with db:  # abre a transação; faz commit no fim ou rollback se der erro
        db.execute(
            "INSERT INTO movimentacoes (produto_id, usuario_id, tipo, quantidade, motivo)"
            " VALUES (?, ?, ?, ?, ?)",
            (produto_id, usuario_id, tipo, quantidade, motivo or None),
        )
        db.execute(
            "UPDATE produtos SET quantidade = ? WHERE id = ?",
            (novo_saldo, produto_id),
        )
    return novo_saldo


@dataclass
class Sugestao:
    id: int
    sku: str
    nome: str
    categoria: str | None
    fornecedor: str | None
    quantidade: int
    estoque_minimo: int
    consumo_diario: float
    dias_cobertura: float | None
    ponto_pedido: int
    sugerido: int
    custo_estimado: float

    @property
    def critico(self) -> bool:
        """Saldo no estoque mínimo ou abaixo dele."""
        return self.quantidade <= self.estoque_minimo

    @property
    def precisa_comprar(self) -> bool:
        """Saldo chegou ao ponto de pedido."""
        return self.quantidade <= self.ponto_pedido


def calcular_ponto_pedido(estoque_minimo: int, consumo_diario: float) -> int:
    """Ponto de pedido = consumo médio diário x prazo de reposição + estoque de segurança.

    Quando o saldo chega a esse nível, é hora de comprar: o que resta
    precisa durar até a mercadoria chegar, sem consumir a margem de segurança.
    O estoque mínimo cadastrado faz o papel de estoque de segurança.
    """
    return math.ceil(round(consumo_diario * PRAZO_REPOSICAO + estoque_minimo, 6))


def calcular_sugestao(quantidade: int, estoque_minimo: int,
                      consumo_diario: float) -> int:
    """Quantidade a comprar quando o saldo atinge o ponto de pedido.

        sugerido = teto(consumo_diario * DIAS_COBERTURA + estoque_minimo - quantidade)

    A compra cobre DIAS_COBERTURA dias de consumo e recompõe o estoque de
    segurança. Retorna 0 se o produto ainda não chegou ao ponto de pedido.
    """
    if quantidade > calcular_ponto_pedido(estoque_minimo, consumo_diario):
        return 0
    necessidade = consumo_diario * DIAS_COBERTURA + estoque_minimo - quantidade
    return max(0, math.ceil(round(necessidade, 6)))


def relatorio_reposicao(somente_criticos: bool = False) -> list[Sugestao]:
    """Lista os produtos ativos com consumo médio e sugestão de compra."""
    linhas = get_db().execute(
        f"""
        SELECT p.id, p.sku, p.nome, p.quantidade, p.estoque_minimo, p.preco_custo,
               c.nome AS categoria, f.nome AS fornecedor,
               COALESCE(SUM(CASE WHEN m.tipo = 'saida' THEN m.quantidade END), 0)
                   AS saidas_periodo
          FROM produtos p
          LEFT JOIN categorias c   ON c.id = p.categoria_id
          LEFT JOIN fornecedores f ON f.id = p.fornecedor_id
          LEFT JOIN movimentacoes m
                 ON m.produto_id = p.id
                AND m.data >= datetime('now', 'localtime', '-{DIAS_ANALISE} days')
         WHERE p.ativo = 1
         GROUP BY p.id
         ORDER BY p.nome
        """
    ).fetchall()

    resultado = []
    for r in linhas:
        consumo = r["saidas_periodo"] / DIAS_ANALISE
        sugerido = calcular_sugestao(r["quantidade"], r["estoque_minimo"], consumo)
        item = Sugestao(
            id=r["id"], sku=r["sku"], nome=r["nome"], categoria=r["categoria"],
            fornecedor=r["fornecedor"], quantidade=r["quantidade"],
            estoque_minimo=r["estoque_minimo"], consumo_diario=round(consumo, 2),
            dias_cobertura=round(r["quantidade"] / consumo, 1) if consumo else None,
            ponto_pedido=calcular_ponto_pedido(r["estoque_minimo"], consumo),
            sugerido=sugerido, custo_estimado=round(sugerido * r["preco_custo"], 2),
        )
        if not somente_criticos or item.critico or item.precisa_comprar:
            resultado.append(item)
    # Os mais urgentes primeiro: críticos, depois menor cobertura em dias
    resultado.sort(key=lambda s: (not s.critico,
                                  s.dias_cobertura if s.dias_cobertura is not None else 1e9))
    return resultado


def indicadores() -> dict:
    """Números exibidos no painel inicial."""
    db = get_db()
    totais = db.execute(
        """
        SELECT COUNT(*) AS produtos,
               COALESCE(SUM(quantidade), 0) AS unidades,
               COALESCE(SUM(quantidade * preco_custo), 0) AS valor_custo,
               COALESCE(SUM(CASE WHEN quantidade <= estoque_minimo THEN 1 END), 0)
                   AS abaixo_minimo
          FROM produtos WHERE ativo = 1
        """
    ).fetchone()
    mov_mes = db.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN tipo='entrada' THEN quantidade END), 0) AS entradas,
               COALESCE(SUM(CASE WHEN tipo='saida'   THEN quantidade END), 0) AS saidas
          FROM movimentacoes
         WHERE data >= datetime('now', 'localtime', '-30 days')
        """
    ).fetchone()
    return {**dict(totais), **dict(mov_mes)}
