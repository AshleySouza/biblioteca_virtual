import importlib
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from flask import get_flashed_messages
from werkzeug.security import generate_password_hash

import database


class BibliotecaAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._db_path = os.path.join(cls._tmpdir.name, "test_biblioteca.db")

        database.DATABASE = cls._db_path

        import app as app_module

        cls.app_module = importlib.reload(app_module)
        cls.app = cls.app_module.app
        cls.app.config.update(TESTING=True)

    @classmethod
    def tearDownClass(cls):
        cls._tmpdir.cleanup()

    def setUp(self):
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

        database.DATABASE = self._db_path
        self.app_module.criar_tabelas()
        self._seed_data()
        self.client = self.app.test_client()

    def _seed_data(self):
        conn = database.conectar()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO usuarios (id, nome, email, senha, tipo) VALUES (?, ?, ?, ?, ?)",
            (1, "Admin", "admin@local.test", generate_password_hash("admin123"), "admin"),
        )
        cursor.execute(
            "INSERT INTO usuarios (id, nome, email, senha, tipo) VALUES (?, ?, ?, ?, ?)",
            (2, "Usuario", "user@local.test", generate_password_hash("user123"), "usuario"),
        )

        cursor.execute(
            """
            INSERT INTO livros (id, titulo, autor, ano, disponivel, usuario_id, data_devolucao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "Python Limpo", "Autor A", 2024, 1, None, None),
        )
        cursor.execute(
            """
            INSERT INTO livros (id, titulo, autor, ano, disponivel, usuario_id, data_devolucao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (2, "Flask Pratico", "Autor B", 2023, 0, 2, "25/02/2026"),
        )

        conn.commit()
        conn.close()

    def _csrf_from(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1)

    def _login(self, email, senha):
        token = self._csrf_from("/login")
        return self.client.post(
            "/login",
            data={"email": email, "senha": senha, "csrf_token": token},
            follow_redirects=True,
        )

    def test_login_success(self):
        response = self._login("admin@local.test", "admin123")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Login realizado com sucesso", response.data)

    def test_post_without_csrf_returns_400(self):
        response = self.client.post("/login", data={"email": "admin@local.test", "senha": "admin123"})
        self.assertEqual(response.status_code, 400)

    def test_admin_accesses_usuarios(self):
        self._login("admin@local.test", "admin123")
        response = self.client.get("/usuarios?q=user&page=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"user@local.test", response.data)

    def test_usuario_cannot_access_admin_screen(self):
        self._login("user@local.test", "user123")
        response = self.client.get("/usuarios", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Acesso restrito ao administrador", response.data)

    def test_admin_can_update_user_role(self):
        self._login("admin@local.test", "admin123")
        token = self._csrf_from("/usuarios")

        response = self.client.post(
            "/usuarios/2/tipo",
            data={"tipo": "admin", "csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Tipo de usuario atualizado com sucesso", response.data)

        conn = database.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT tipo FROM usuarios WHERE id = 2")
        tipo = cursor.fetchone()["tipo"]
        conn.close()
        self.assertEqual(tipo, "admin")

    def test_remover_livro_requer_post(self):
        self._login("admin@local.test", "admin123")
        response = self.client.get("/remover/1")
        self.assertEqual(response.status_code, 405)

    def test_admin_can_remove_livro_with_csrf(self):
        self._login("admin@local.test", "admin123")
        token = self._csrf_from("/")

        response = self.client.post(
            "/remover/1",
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Livro removido com sucesso", response.data)

        conn = database.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM livros WHERE id = 1")
        total = cursor.fetchone()["total"]
        conn.close()
        self.assertEqual(total, 0)

    def test_admin_can_emprestar_livro_with_csrf(self):
        self._login("admin@local.test", "admin123")
        token = self._csrf_from("/emprestar/1")

        response = self.client.post(
            "/emprestar/1",
            data={"usuario_id": 2, "csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Livro emprestado com sucesso", response.data)

        conn = database.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT disponivel, usuario_id, data_devolucao FROM livros WHERE id = 1")
        livro = cursor.fetchone()
        conn.close()

        self.assertEqual(livro["disponivel"], 0)
        self.assertEqual(livro["usuario_id"], 2)
        self.assertIsNotNone(livro["data_devolucao"])

    def test_admin_can_devolver_livro_with_csrf(self):
        self._login("admin@local.test", "admin123")
        token = self._csrf_from("/")

        response = self.client.post(
            "/devolver/2",
            data={"csrf_token": token},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Livro devolvido com sucesso", response.data)

        conn = database.conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT disponivel, usuario_id, data_devolucao FROM livros WHERE id = 2")
        livro = cursor.fetchone()
        conn.close()

        self.assertEqual(livro["disponivel"], 1)
        self.assertIsNone(livro["usuario_id"])
        self.assertIsNone(livro["data_devolucao"])

    def test_nao_permite_remover_ultimo_admin(self):
        class DummyAdmin:
            id = 999
            tipo = "admin"

        with self.app.test_request_context("/usuarios/1/tipo", method="POST", data={"tipo": "usuario"}):
            with patch.object(self.app_module, "current_user", DummyAdmin()):
                response = self.app_module.atualizar_tipo_usuario.__wrapped__(1)
                mensagens = get_flashed_messages(with_categories=False)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(any("ultimo administrador" in mensagem for mensagem in mensagens))


if __name__ == "__main__":
    unittest.main()
