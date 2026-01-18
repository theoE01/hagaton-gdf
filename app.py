import os
import sqlite3
from flask import Flask

from models import db
from routes.public import public_bp
from routes.upload import upload_bp
from routes.admin import admin_bp
from chat_routes import chat_bp


def _ensure_sqlite_columns(db_path: str):
    """MVP migration: adiciona colunas novas sem usar Alembic.
    Evita quebrar o app caso o database.db já exista.
    """
    if not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        def has_col(table: str, col: str) -> bool:
            cur.execute(f"PRAGMA table_info({table})")
            return any(row[1] == col for row in cur.fetchall())

        # user
        if has_col("user", "id"):
            if not has_col("user", "created_at"):
                cur.execute("ALTER TABLE user ADD COLUMN created_at DATETIME")

        # submission
        if has_col("submission", "id"):
            if not has_col("submission", "status"):
                cur.execute("ALTER TABLE submission ADD COLUMN status VARCHAR(30) DEFAULT 'recebido'")
            if not has_col("submission", "created_at"):
                cur.execute("ALTER TABLE submission ADD COLUMN created_at DATETIME")

        # file
        if has_col("file", "id"):
            for col, sql in [
                ("original_name", "ALTER TABLE file ADD COLUMN original_name VARCHAR(255)"),
                ("mime_type", "ALTER TABLE file ADD COLUMN mime_type VARCHAR(120)"),
                ("size_bytes", "ALTER TABLE file ADD COLUMN size_bytes INTEGER"),
                ("sha256", "ALTER TABLE file ADD COLUMN sha256 VARCHAR(64)"),
                ("uploaded_at", "ALTER TABLE file ADD COLUMN uploaded_at DATETIME"),
            ]:
                if not has_col("file", col):
                    cur.execute(sql)

        conn.commit()
    finally:
        conn.close()


app = Flask(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "chave-super-secreta")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Uploads (padrão do sistema)
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "static", "uploads")

# Uploads específicos do chat (Capivara)
app.config["CHAT_UPLOAD_FOLDER"] = os.path.join(app.config["UPLOAD_FOLDER"], "chat")

# Garante que as pastas existam
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["CHAT_UPLOAD_FOLDER"], exist_ok=True)

# (1) migra sqlite (se existir)
_ensure_sqlite_columns(DB_PATH)

# (2) inicializa ORM
db.init_app(app)

# Blueprints
app.register_blueprint(public_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(chat_bp)

# Cria tabelas ausentes
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)  # em produção: debug=False
