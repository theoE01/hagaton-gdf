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




### Possiveis consultas atraves do Capivarinha:

1) Perguntas por protocolo / caso específico

“Analise o protocolo XXXX e me diga categoria, prioridade, tags e resumo.”

“Esse protocolo tem risco alto? Justifique com base em texto + OCR + ASR.”

“Quais são os pontos-chave desse caso?”

“Esse caso precisa de mais dados? O que está faltando?”

“O OCR detectou alguma placa, endereço, data, número? Resuma.”

“A transcrição do áudio/vídeo diz o quê? Faça um resumo objetivo.”

“Esse conteúdo parece denúncia ou reclamação? Qual a melhor categoria?”

“Sugira o setor responsável e uma ação recomendada para esse caso.”

2) Perguntas sobre conteúdo de mídia (imagem/áudio/vídeo)

“Mostre o teor do conteúdo da imagem do protocolo XXXX (OCR).”

“Liste as frases principais encontradas no OCR e indique se tem localização.”

“Resuma a fala do áudio/vídeo do protocolo XXXX (ASR).”

“Existe ameaça, xingamento, assédio ou conteúdo sensível no áudio/vídeo? Classifique.”

“A mídia é prova forte ou fraca? Justifique.”

3) Perguntas gerenciais (visão do admin)

“Quais são os protocolos críticos na última semana?”

“Quais categorias mais aparecem hoje e quais estão crescendo?”

“Quais tipos de envio são mais comuns: texto, imagem, áudio, vídeo?”

“Qual a distribuição anônimo vs identificado?”

“Quais status estão acumulando (ex.: recebido, em análise, resolvido)?”

“Existe tendência de aumento de denúncias?”

“Quais são os top 10 protocolos por prioridade?”

“Liste 3 problemas recorrentes e recomendações objetivas.”

4) Pedidos de gráficos (reais, com dataset)

Use sempre “gráfico” + o que você quer medir:

“Gere um gráfico por status.”

“Gere um gráfico por tipo (texto/imagem/áudio/vídeo).”

“Gere um gráfico por modo (anônimo vs identificado).”

“Gere um gráfico de tendência de submissions por dia.”

“Gere gráficos do sistema (os principais).”

“Para o protocolo XXXX, gere gráfico de evidências (texto/OCR/ASR).”

“Para a submission 123, gere gráfico de arquivos por tipo e tamanho por tipo.”

5) Consultas de auditoria e qualidade

“Quantos casos estão com baixa confiança de classificação?”

“Quais análises falharam (tags falha_ia)?”

“Quais protocolos têm mídia mas não têm OCR/ASR gerado?”

“Onde há indício de informação insuficiente (necessita_mais_dados=true)?”