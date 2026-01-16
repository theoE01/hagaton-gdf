pip install flask
pip install flask-sqlalchemy
pip install cryptography
pip install werkzeug
pip install python-dotenv




HAGATON GDF/
│
├── app.py
├── models.py
├── database.db
│
├── routes/
│   ├── public.py
│   ├── upload.py
│   └── admin.py
│
├── templates/
│   ├── index.html
│   ├── upload.html
│   ├── admin.html
│   └── admin_login.html
│
├── static/
│   └── uploads/
│
└── venv/


pra rodar o projeto:
comando no terminal =  python app.py



👤 Funcionalidades
Usuário

Cadastro público ou anônimo

Geração de protocolo único

Envio de:

Textos

Imagens

Áudios

Vídeos

Upload múltiplo com validação

Admin

Login protegido

Filtros por:

Público / Anônimo

Tipo de arquivo

Preview de arquivos

Download direto

🔐 Segurança

Criptografia de CPF e RG com cryptography (Fernet)

Validação de:

Extensão de arquivos

Tamanho máximo (10MB)

Sessão protegida no painel admin

🛠 Tecnologias Utilizadas

Python

Flask

Flask-SQLAlchemy

SQLite

Cryptography

HTML5
