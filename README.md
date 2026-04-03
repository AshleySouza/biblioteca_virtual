# Biblioteca Virtual

Projeto Flask simples para gerenciamento de biblioteca, com autenticação, cadastro de usuários, empréstimos e devoluções.

## Como executar localmente

1. Crie e ative um ambiente virtual:
   - Windows: `python -m venv venv` e `venv\Scripts\activate`
2. Instale as dependências:
   - `pip install -r requirements.txt`
3. Execute o aplicativo:
   - `python app.py`
4. Acesse em `http://127.0.0.1:5000`

## Testes

Execute os testes com:

```bash
python -m unittest discover -s tests -p 'test_*.py'
```

## Observações

- O banco de dados SQLite padrão é `biblioteca.db`.
- O arquivo `biblioteca.db` está ignorado pelo `.gitignore`.
- Configure `SECRET_KEY` como variável de ambiente em produção.
