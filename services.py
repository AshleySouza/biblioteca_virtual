from database import conectar


def adicionar_livro(livro):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO livros (titulo, autor, ano, disponivel)
        VALUES (?, ?, ?, ?)
    """, (livro.titulo, livro.autor, livro.ano, int(livro.disponivel)))

    conn.commit()
    conn.close()


def listar_livros():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM livros")
    colunas = [col[0] for col in cursor.description]
    dados = cursor.fetchall()

    conn.close()

    return [dict(zip(colunas, linha)) for linha in dados]


def buscar_por_titulo(titulo):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM livros
        WHERE titulo LIKE ?
    """, (f"%{titulo}%",))

    colunas = [col[0] for col in cursor.description]
    dados = cursor.fetchall()

    conn.close()

    return [dict(zip(colunas, linha)) for linha in dados]


def buscar_por_id(id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM livros WHERE id = ?", (id,))
    colunas = [col[0] for col in cursor.description]
    dado = cursor.fetchone()

    conn.close()

    if dado:
        return dict(zip(colunas, dado))
    return None


def atualizar_livro(id, novo_titulo, novo_autor, novo_ano):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE livros
        SET titulo = ?, autor = ?, ano = ?
        WHERE id = ?
    """, (novo_titulo, novo_autor, novo_ano, id))

    conn.commit()
    conn.close()


def remover_livro(id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM livros WHERE id = ?", (id,))

    conn.commit()
    conn.close()

 #regra de negocio 

def alterar_disponibilidade(id, status):
    conn = conectar()
    cursor = conn.cursor()

    # Verifica estado atual
    cursor.execute("SELECT disponivel FROM livros WHERE id = ?", (id,))
    resultado = cursor.fetchone()

    if not resultado:
        conn.close()
        return False, "Livro não encontrado"

    estado_atual = resultado[0]

    if estado_atual == int(status):
        conn.close()
        return False, "Operação inválida"

    cursor.execute("""
        UPDATE livros
        SET disponivel = ?
        WHERE id = ?
    """, (int(status), id))

    conn.commit()
    conn.close()

    return True, "Atualizado com sucesso"