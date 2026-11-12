-- =============================================================
-- EstoqueFácil - Esquema do banco de dados (SQLite)
-- Modelo relacional normalizado (3FN) para controle de estoque
-- =============================================================

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS movimentacoes;
DROP TABLE IF EXISTS produtos;
DROP TABLE IF EXISTS fornecedores;
DROP TABLE IF EXISTS categorias;
DROP TABLE IF EXISTS usuarios;

-- Usuários que acessam o sistema
CREATE TABLE usuarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    nome        TEXT    NOT NULL,
    email       TEXT    NOT NULL UNIQUE,
    senha_hash  TEXT    NOT NULL,
    perfil      TEXT    NOT NULL DEFAULT 'operador'
                CHECK (perfil IN ('admin', 'operador')),
    criado_em   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Categorias de produtos (ex.: Bebidas, Limpeza)
CREATE TABLE categorias (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT    NOT NULL UNIQUE,
    descricao  TEXT
);

-- Fornecedores dos produtos
CREATE TABLE fornecedores (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    nome      TEXT    NOT NULL,
    cnpj      TEXT    UNIQUE,
    telefone  TEXT,
    email     TEXT
);

-- Produtos controlados no estoque
CREATE TABLE produtos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT    NOT NULL UNIQUE,
    nome            TEXT    NOT NULL,
    categoria_id    INTEGER REFERENCES categorias(id) ON DELETE SET NULL,
    fornecedor_id   INTEGER REFERENCES fornecedores(id) ON DELETE SET NULL,
    unidade         TEXT    NOT NULL DEFAULT 'un',
    preco_custo     REAL    NOT NULL DEFAULT 0 CHECK (preco_custo >= 0),
    preco_venda     REAL    NOT NULL DEFAULT 0 CHECK (preco_venda >= 0),
    estoque_minimo  INTEGER NOT NULL DEFAULT 0 CHECK (estoque_minimo >= 0),
    quantidade      INTEGER NOT NULL DEFAULT 0 CHECK (quantidade >= 0),
    ativo           INTEGER NOT NULL DEFAULT 1,
    criado_em       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Histórico de entradas e saídas (rastreabilidade)
CREATE TABLE movimentacoes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id  INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
    usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    tipo        TEXT    NOT NULL CHECK (tipo IN ('entrada', 'saida')),
    quantidade  INTEGER NOT NULL CHECK (quantidade > 0),
    motivo      TEXT,
    data        TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_mov_produto_data ON movimentacoes (produto_id, data);
CREATE INDEX idx_produtos_categoria ON produtos (categoria_id);
