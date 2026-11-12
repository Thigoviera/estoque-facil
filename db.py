"""Acesso ao banco de dados SQLite.

Uma conexão é aberta por requisição (guardada em ``flask.g``) e fechada
automaticamente ao final dela. As chaves estrangeiras são ativadas em
toda conexão, pois o SQLite as deixa desligadas por padrão.
"""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def get_db() -> sqlite3.Connection:
    """Retorna a conexão da requisição atual, criando-a se necessário."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row  # permite acessar colunas pelo nome
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_erro=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    """Cria (ou recria) todas as tabelas a partir de schema.sql."""
    get_db().executescript(SCHEMA.read_text(encoding="utf-8"))


def init_app(app) -> None:
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """flask init-db  -> cria o banco vazio."""
        init_db()
        print("Banco de dados criado.")
