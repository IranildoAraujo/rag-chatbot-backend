# rag_api/utils.py
import chromadb
import google.generativeai as genai
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# --- ChromaDB Client ---
_chroma_client = None

def get_chroma_client():
    """Retorna uma instância singleton do cliente ChromaDB."""
    global _chroma_client
    if _chroma_client is None:
        try:
            logger.info(f"Conectando ao ChromaDB em {settings.CHROMA_HOST}:{settings.CHROMA_PORT}")
            _chroma_client = chromadb.HttpClient(
                host=settings.CHROMA_HOST,
                port=settings.CHROMA_PORT
            )
            # Teste rápido de conexão (opcional)
            _chroma_client.heartbeat()
            logger.info("Conexão com ChromaDB bem-sucedida.")
        except Exception as e:
            logger.error(f"Falha ao conectar ao ChromaDB: {e}", exc_info=True)
            # Você pode querer lançar a exceção ou retornar None dependendo da sua estratégia de erro
            raise ConnectionError(f"Não foi possível conectar ao ChromaDB: {e}") from e
    return _chroma_client

# --- Gemini Configuration ---
_gemini_initialized = False
_gemini_model = None
_gemini_embedding_model = None # Guardar referência ao modelo de embedding

def initialize_gemini():
    """Configura a API do Gemini."""
    global _gemini_initialized, _gemini_model, _gemini_embedding_model
    if not _gemini_initialized:
        if settings.GOOGLE_API_KEY:
            try:
                logger.info("Configurando a API do Google Generative AI...")
                genai.configure(api_key=settings.GOOGLE_API_KEY)
                # Instanciar o modelo de geração
                _gemini_model = genai.GenerativeModel(settings.GEMINI_MODEL_NAME)
                # Instanciar o modelo de embedding (importante para RAG)
                # Não instanciamos diretamente, usamos genai.embed_content
                _gemini_embedding_model = settings.GEMINI_EMBEDDING_MODEL # Guardamos o nome/referência
                _gemini_initialized = True
                logger.info(f"Modelo Gemini '{settings.GEMINI_MODEL_NAME}' e embedding '{settings.GEMINI_EMBEDDING_MODEL}' prontos.")
            except Exception as e:
                logger.error(f"Falha ao configurar o Gemini: {e}", exc_info=True)
                # Lidar com o erro - talvez impedir o início da aplicação ou retornar um estado de erro
        else:
            logger.warning("API Key do Google não configurada. Funcionalidades do Gemini estarão desabilitadas.")

def get_gemini_model():
    """Retorna o modelo generativo do Gemini inicializado."""
    if not _gemini_initialized:
        initialize_gemini()
    if not _gemini_model:
         raise RuntimeError("Modelo Gemini não inicializado. Verifique a API Key e logs.")
    return _gemini_model

def get_embedding_model_name():
    """Retorna o nome/identificador do modelo de embedding."""
    if not _gemini_initialized:
        initialize_gemini()
    if not _gemini_embedding_model:
        raise RuntimeError("Modelo de embedding Gemini não configurado.")
    return _gemini_embedding_model

# Função de Embedding específica para Gemini (usada tanto na ingestão quanto na consulta)
def embed_text_gemini(text_or_texts, task_type="retrieval_document"):
    """Gera embeddings para texto(s) usando o modelo Gemini configurado."""
    if not _gemini_initialized:
        initialize_gemini()
    if not _gemini_embedding_model:
        raise RuntimeError("Modelo de embedding Gemini não configurado.")

    try:
        # Adapta a chamada se for um único texto ou uma lista
        if isinstance(text_or_texts, str):
            result = genai.embed_content(
                model=get_embedding_model_name(),
                content=text_or_texts,
                task_type=task_type # retrieval_document, retrieval_query, similarity, etc.
            )
            return result['embedding']
        elif isinstance(text_or_texts, list):
             # O batching pode ser mais eficiente, mas a API pode ter limites.
             # A API atual parece processar listas diretamente no 'content'.
            result = genai.embed_content(
                model=get_embedding_model_name(),
                content=text_or_texts,
                task_type=task_type
            )
            return result['embedding'] # Retorna uma lista de embeddings
        else:
            raise TypeError("Input deve ser uma string ou uma lista de strings.")
    except Exception as e:
        logger.error(f"Erro ao gerar embedding Gemini para task '{task_type}': {e}", exc_info=True)
        raise

# Inicializa o Gemini quando o módulo é carregado (ou sob demanda)
# initialize_gemini() # Pode ser chamado aqui ou na inicialização do Django (apps.py)