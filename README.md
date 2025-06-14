# RAG_API

Projeto backend em Django. 

## Comunicado

Essas instruções permitirão que você obtenha uma cópia do projeto em operação na sua máquina local para fins de desenvolvimento e teste.

## Ativação do ambiente virtual:

```
python3.12 -m venv .venv
```

```
source .venv/bin/activate
```

## Instale as bibliotecas:

```
pip install -r requirements.txt
```

## No arquivo `.env` da API adicione sua API Key gerada no Gemini:

```
GOOGLE_API_KEY=#############################
```

## Instalação do ChromaDB em docker:

### Estrutura do diretório docker do chromaDB:
```
chroma-docker/
├── .env               
├── Dockerfile         
└── docker-compose.yml
```

###  `.env` do ChromaDB:

```
# Configurações do ChromaDB
CHROMA_HOST=0.0.0.0
CHROMA_PORT=8900
CHROMA_PERSIST_DIR=/data

# Configurações do Nginx
NGINX_PORT=89
PROXY_USER=admin
PROXY_PASSWORD=Sua_senha
```

### `Dockerfile`:

```
FROM python:3.12-slim

# Instala ChromaDB e dependências
RUN pip install chromadb

# Cria diretório para dados
RUN mkdir -p /data

# Expõe a porta padrão (será sobrescrita via .env)
EXPOSE ${CHROMA_PORT}

# Comando de inicialização
CMD ["sh", "-c", "chroma run --path ${CHROMA_PERSIST_DIR} --host ${CHROMA_HOST} --port ${CHROMA_PORT}"]
```

### `docker-compose.yml`:

```
services:
  chroma:
    build: .
    container_name: chroma-server
    env_file: 
      - .env
    volumes:
      - ./chroma_data:/data
    ports:
      - "8900:8900"
    networks:
      - chroma-net

  nginx-proxy:
    image: nginx
    container_name: nginx-proxy
    ports:
      - "89:89"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./htpasswd:/etc/nginx/.htpasswd
    depends_on:
      - chroma
    networks:
      - chroma-net

networks:
  chroma-net:
    driver: bridge
```

### `nginx.conf`:

```
events {}

http {
    server {
        listen 89;
        server_name _;

        location /api/v2/ {
            proxy_pass http://chroma:8900/api/v2/;  # Redireciona para v2
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            
            auth_basic "Restricted Area";
            auth_basic_user_file /etc/nginx/.htpasswd;
        }
    }
}
```

Gere o arquivo `htpasswd` (para autenticação):

```bash
echo "${PROXY_USER}:$(openssl passwd -apr1 ${PROXY_PASSWORD})" > htpasswd
```

ou já com p usuário e a senha:

```bash
echo "admin:$(openssl passwd -apr1 Sua_senha)" > htpasswd
```

### Como Usar?

1. **Inicie a criação do banco de dado vetorial**:

```bash
docker-compose up -d
```

   - O `.env` será carregado automaticamente pelo `docker-compose.yml`.

2. **Inicie a aplicação**:

```python
python manage.py runserver
```
