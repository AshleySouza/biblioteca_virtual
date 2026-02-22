import os
import secrets
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import conectar, criar_tabelas
from models import Livro
from services import adicionar_livro, atualizar_livro, buscar_por_titulo, listar_livros, remover_livro

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-insecure-change-me")

criar_tabelas()

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


class Usuario(UserMixin):
    def __init__(self, user_id, nome, email, tipo):
        self.id = user_id
        self.nome = nome
        self.email = email
        self.tipo = tipo


@login_manager.user_loader
def load_user(user_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if user:
        return Usuario(user["id"], user["nome"], user["email"], user["tipo"])
    return None


def _migrar_senhas_legadas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT id, senha FROM usuarios")
    usuarios = cursor.fetchall()

    atualizados = []
    for usuario in usuarios:
        senha = usuario["senha"]
        if not senha.startswith(("pbkdf2:", "scrypt:")):
            atualizados.append((generate_password_hash(senha), usuario["id"]))

    if atualizados:
        cursor.executemany("UPDATE usuarios SET senha = ? WHERE id = ?", atualizados)
        conn.commit()

    conn.close()


_migrar_senhas_legadas()


def _listar_livros_do_usuario(usuario_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM livros
        WHERE usuario_id = ?
        AND disponivel = 0
        """,
        (usuario_id,),
    )
    livros = cursor.fetchall()
    conn.close()
    return livros


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": _csrf_token()}


@app.before_request
def validate_csrf():
    _csrf_token()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        sent_token = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
        if not sent_token or not secrets.compare_digest(session["csrf_token"], sent_token):
            abort(400, description="CSRF token invalido.")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        senha = request.form["senha"]

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
        user = cursor.fetchone()

        if not user:
            conn.close()
            flash("Email ou senha invalidos.", "danger")
            return render_template("login.html")

        senha_armazenada = user["senha"]
        senha_valida = False

        if senha_armazenada.startswith(("pbkdf2:", "scrypt:")):
            senha_valida = check_password_hash(senha_armazenada, senha)
        else:
            senha_valida = secrets.compare_digest(senha_armazenada, senha)
            if senha_valida:
                nova_hash = generate_password_hash(senha)
                cursor.execute("UPDATE usuarios SET senha = ? WHERE id = ?", (nova_hash, user["id"]))
                conn.commit()

        conn.close()

        if senha_valida:
            usuario = Usuario(user["id"], user["nome"], user["email"], user["tipo"])
            login_user(usuario)
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))

        flash("Email ou senha invalidos.", "danger")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logout realizado!", "info")
    return redirect(url_for("login"))


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nome = request.form["nome"].strip()
        email = request.form["email"].strip().lower()
        senha = request.form["senha"]
        senha_hash = generate_password_hash(senha)

        conn = conectar()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO usuarios (nome, email, senha, tipo) VALUES (?, ?, ?, ?)",
                (nome, email, senha_hash, "usuario"),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            flash("Ja existe usuario com esse email.", "warning")
            return render_template("registro.html")

        conn.close()
        flash("Usuario cadastrado com sucesso!", "success")
        return redirect(url_for("login"))

    return render_template("registro.html")


@app.route("/")
@login_required
def index():
    if current_user.tipo == "admin":
        termo = request.args.get("busca", "").strip()
        livros = buscar_por_titulo(termo) if termo else listar_livros()
        return render_template("index.html", livros=livros)

    livros = _listar_livros_do_usuario(current_user.id)
    return render_template("meus_livros.html", livros=livros)


@app.route("/meus-livros")
@login_required
def meus_livros():
    livros = _listar_livros_do_usuario(current_user.id)
    return render_template("meus_livros.html", livros=livros)


@app.route("/usuarios")
@login_required
def usuarios():
    if current_user.tipo != "admin":
        flash("Acesso restrito ao administrador!", "danger")
        return redirect(url_for("index"))

    termo = request.args.get("q", "").strip()
    pagina = request.args.get("page", 1, type=int)
    por_pagina = 8

    conn = conectar()
    cursor = conn.cursor()

    filtros = []
    params = []
    if termo:
        filtros.append("(nome LIKE ? OR email LIKE ?)")
        like = f"%{termo}%"
        params.extend([like, like])

    where_clause = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    total_query = f"SELECT COUNT(*) AS total FROM usuarios {where_clause}"
    cursor.execute(total_query, params)
    total = cursor.fetchone()["total"]

    total_paginas = max((total + por_pagina - 1) // por_pagina, 1)
    pagina = max(1, min(pagina, total_paginas))
    offset = (pagina - 1) * por_pagina

    dados_query = f"""
        SELECT id, nome, email, tipo
        FROM usuarios
        {where_clause}
        ORDER BY nome
        LIMIT ? OFFSET ?
    """
    cursor.execute(dados_query, [*params, por_pagina, offset])
    lista_usuarios = cursor.fetchall()
    conn.close()

    return render_template(
        "usuarios.html",
        usuarios=lista_usuarios,
        q=termo,
        pagina=pagina,
        total_paginas=total_paginas,
        total=total,
    )


@app.route("/usuarios/<int:id_usuario>/tipo", methods=["POST"])
@login_required
def atualizar_tipo_usuario(id_usuario):
    if current_user.tipo != "admin":
        flash("Acesso restrito ao administrador!", "danger")
        return redirect(url_for("index"))

    novo_tipo = request.form.get("tipo", "").strip()
    if novo_tipo not in {"admin", "usuario"}:
        flash("Tipo de usuario invalido.", "danger")
        return redirect(url_for("usuarios"))

    if id_usuario == current_user.id:
        flash("Nao e permitido alterar o proprio tipo de conta.", "warning")
        return redirect(url_for("usuarios"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT id, tipo FROM usuarios WHERE id = ?", (id_usuario,))
    usuario_alvo = cursor.fetchone()
    if not usuario_alvo:
        conn.close()
        flash("Usuario nao encontrado.", "warning")
        return redirect(url_for("usuarios"))

    tipo_atual = usuario_alvo["tipo"]
    if tipo_atual == novo_tipo:
        conn.close()
        flash("Nenhuma alteracao foi necessaria.", "info")
        return redirect(url_for("usuarios"))

    if tipo_atual == "admin" and novo_tipo == "usuario":
        cursor.execute("SELECT COUNT(*) AS total FROM usuarios WHERE tipo = 'admin'")
        total_admins = cursor.fetchone()["total"]
        if total_admins <= 1:
            conn.close()
            flash("Nao e possivel remover o ultimo administrador.", "danger")
            return redirect(url_for("usuarios"))

    cursor.execute("UPDATE usuarios SET tipo = ? WHERE id = ?", (novo_tipo, id_usuario))
    conn.commit()
    conn.close()

    flash("Tipo de usuario atualizado com sucesso.", "success")
    return redirect(url_for("usuarios"))


@app.route("/adicionar", methods=["GET", "POST"])
@login_required
def adicionar():
    if current_user.tipo != "admin":
        flash("Acesso restrito ao administrador!", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        titulo = request.form["titulo"].strip()
        autor = request.form["autor"].strip()
        ano = int(request.form["ano"])

        livro = Livro(titulo, autor, ano)
        adicionar_livro(livro)

        flash("Livro adicionado com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("adicionar.html")


@app.route("/editar/<int:id_livro>", methods=["GET", "POST"])
@login_required
def editar(id_livro):
    if current_user.tipo != "admin":
        flash("Acesso restrito ao administrador!", "danger")
        return redirect(url_for("index"))

    livros = listar_livros()
    livro = next((l for l in livros if l["id"] == id_livro), None)

    if not livro:
        flash("Livro nao encontrado!", "warning")
        return redirect(url_for("index"))

    if request.method == "POST":
        atualizar_livro(
            id_livro,
            request.form["titulo"].strip(),
            request.form["autor"].strip(),
            int(request.form["ano"]),
        )
        flash("Livro atualizado com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("editar.html", livro=livro)


@app.route("/remover/<int:id_livro>", methods=["POST"])
@login_required
def remover(id_livro):
    if current_user.tipo != "admin":
        flash("Acesso restrito ao administrador!", "danger")
        return redirect(url_for("index"))

    remover_livro(id_livro)
    flash("Livro removido com sucesso!", "success")
    return redirect(url_for("index"))


@app.route("/emprestar/<int:id_livro>", methods=["GET", "POST"])
@login_required
def emprestar(id_livro):
    if current_user.tipo != "admin":
        flash("Apenas admin pode emprestar livros!", "danger")
        return redirect(url_for("index"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT disponivel FROM livros WHERE id = ?", (id_livro,))
    livro = cursor.fetchone()

    if not livro:
        flash("Livro nao encontrado!", "warning")
        conn.close()
        return redirect(url_for("index"))

    if livro["disponivel"] == 0:
        flash("Livro ja esta emprestado!", "warning")
        conn.close()
        return redirect(url_for("index"))

    if request.method == "POST":
        usuario_id = request.form["usuario_id"]
        data_devolucao = datetime.now() + timedelta(days=7)

        cursor.execute(
            """
            UPDATE livros
            SET disponivel = 0,
                usuario_id = ?,
                data_devolucao = ?
            WHERE id = ?
            """,
            (usuario_id, data_devolucao.strftime("%d/%m/%Y"), id_livro),
        )

        conn.commit()
        conn.close()

        flash("Livro emprestado com sucesso!", "success")
        return redirect(url_for("index"))

    cursor.execute(
        """
        SELECT id, nome
        FROM usuarios
        WHERE tipo = 'usuario'
        ORDER BY nome
        """
    )
    usuarios_disponiveis = cursor.fetchall()
    conn.close()

    return render_template("emprestar.html", usuarios=usuarios_disponiveis, id_livro=id_livro)


@app.route("/devolver/<int:id_livro>", methods=["POST"])
@login_required
def devolver(id_livro):
    if current_user.tipo != "admin":
        flash("Apenas admin pode registrar devolucao!", "danger")
        return redirect(url_for("index"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT disponivel FROM livros WHERE id = ?", (id_livro,))
    livro = cursor.fetchone()

    if not livro:
        flash("Livro nao encontrado!", "warning")
        conn.close()
        return redirect(url_for("index"))

    if livro["disponivel"] == 1:
        flash("Livro ja esta disponivel!", "warning")
        conn.close()
        return redirect(url_for("index"))

    cursor.execute(
        """
        UPDATE livros
        SET disponivel = 1,
            usuario_id = NULL,
            data_devolucao = NULL
        WHERE id = ?
        """,
        (id_livro,),
    )

    conn.commit()
    conn.close()

    flash("Livro devolvido com sucesso!", "success")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1")
