# rag_api/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, parsers
from django.conf import settings
import logging

from .serializers import (
    IngestSerializer,
    QuerySerializer,
    RagResponseSerializer,
    FileUploadSerializer,
)
from .utils import (
    get_chroma_client,
    get_gemini_model,
    embed_text_gemini,
    initialize_gemini,
)
from .file_processing import extract_text_from_file, simple_chunker, generate_chunk_ids

logger = logging.getLogger(__name__)

# Tentar inicializar Gemini ao carregar as views
try:
    initialize_gemini()
except Exception as e:
    logger.critical(f"Falha CRÍTICA ao inicializar Gemini na view: {e}", exc_info=True)


class IngestView(APIView):
    # ... (docstring) ...
    def post(self, request, *args, **kwargs):
        serializer = IngestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        documents_data = validated_data["documents"]

        try:
            chroma_client = get_chroma_client()
            collection = chroma_client.get_or_create_collection(
                name=settings.CHROMA_COLLECTION_NAME,
            )

            ids = []
            texts = []
            metadatas_prepared = []  # Lista para metadados validados

            for doc in documents_data:
                ids.append(doc["id"])
                texts.append(doc["text"])
                metadata = doc.get("metadata")  # Pega o metadado, pode ser None ou {}

                # *** INÍCIO DA CORREÇÃO ***
                # Validar e preparar o metadado individualmente
                if not metadata:  # Se for None ou um dicionário vazio {}
                    logger.warning(
                        f"Documento '{doc['id']}' sem metadados ou com metadados vazios. Usando default."
                    )
                    # Fornecer um metadado padrão NÃO VAZIO
                    metadatas_prepared.append({"source": "unknown"})
                else:
                    # O metadado existe e não é vazio, usar ele
                    metadatas_prepared.append(metadata)
                # *** FIM DA CORREÇÃO ***

            if (
                not ids
            ):  # Segurança extra, caso documents_data esteja vazio (embora o serializer deva pegar)
                return Response(
                    {"message": "Nenhum documento para processar."},
                    status=status.HTTP_200_OK,
                )

            logger.info(f"Gerando embeddings para {len(texts)} documentos...")
            embeddings = embed_text_gemini(texts, task_type="retrieval_document")
            logger.info("Embeddings gerados.")

            logger.info(
                f"Adicionando {len(ids)} documentos à coleção '{settings.CHROMA_COLLECTION_NAME}'..."
            )
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas_prepared,  # Usar a lista preparada
            )
            logger.info("Documentos adicionados com sucesso.")

            return Response(
                {"message": f"{len(ids)} documentos adicionados com sucesso."},
                status=status.HTTP_201_CREATED,
            )

        except ConnectionError as e:
            logger.error(f"Erro de conexão com ChromaDB: {e}", exc_info=True)
            return Response(
                {"error": "Não foi possível conectar ao ChromaDB."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as e:  # Capturar especificamente o ValueError de metadados
            logger.error(
                f"Erro de validação durante a ingestão (possivelmente metadados): {e}",
                exc_info=True,
            )
            # Retornar um erro mais específico para o cliente
            return Response(
                {"error": f"Erro de validação de dados para ChromaDB: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Erro durante a ingestão: {e}", exc_info=True)
            return Response(
                {"error": f"Ocorreu um erro interno: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class RagQueryView(APIView):
    """
    Endpoint para fazer uma pergunta e obter uma resposta RAG.
    Recebe um POST com:
    {
        "query": "Qual a capital da França?",
        "top_k": 3  // Opcional, default=3
    }
    Retorna:
    {
        "query": "Qual a capital da França?",
        "retrieved_context": ["Contexto 1...", "Contexto 2..."],
        "answer": "A capital da França é Paris.",
        "model_used": "gemini-1.5-flash"
    }
    """

    def post(self, request, *args, **kwargs):
        serializer = QuerySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_data = serializer.validated_data
        user_query = validated_data["query"]
        top_k = validated_data["top_k"]

        try:
            # 1. Obter Cliente ChromaDB e Coleção
            chroma_client = get_chroma_client()
            try:
                collection = chroma_client.get_collection(
                    name=settings.CHROMA_COLLECTION_NAME
                )
            except Exception as e:  # Pode ser ValueError se a coleção não existe
                logger.error(
                    f"Coleção ChromaDB '{settings.CHROMA_COLLECTION_NAME}' não encontrada: {e}"
                )
                return Response(
                    {
                        "error": f"A coleção de dados '{settings.CHROMA_COLLECTION_NAME}' não foi encontrada. Faça a ingestão de dados primeiro."
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            # 2. Gerar Embedding para a Query usando Gemini
            # task_type="retrieval_query" é importante para a busca RAG
            logger.info(f"Gerando embedding para a query: '{user_query}'")
            query_embedding = embed_text_gemini(user_query, task_type="retrieval_query")
            logger.info("Embedding da query gerado.")

            # 3. Buscar Documentos Relevantes no ChromaDB
            logger.info(f"Buscando {top_k} documentos relevantes no ChromaDB...")
            results = collection.query(
                query_embeddings=[
                    query_embedding
                ],  # A API espera uma lista de embeddings
                n_results=top_k,
                include=["documents"],  # Incluir o texto dos documentos nos resultados
            )
            logger.info(
                f"Busca no ChromaDB concluída. Encontrados {len(results.get('documents', [[]])[0])} resultados."
            )

            retrieved_documents = results.get("documents", [[]])[
                0
            ]  # A estrutura é [[doc1, doc2,...]]

            if not retrieved_documents:
                logger.warning(
                    "Nenhum documento relevante encontrado no ChromaDB para a query."
                )
                # Você pode optar por responder diretamente com Gemini sem contexto,
                # ou retornar uma mensagem indicando que não há contexto.
                # Vamos prosseguir e deixar Gemini tentar responder sem contexto específico.
                context_string = (
                    "Nenhum contexto relevante encontrado na base de dados."
                )
            else:
                context_string = "\n\n".join(retrieved_documents)

            # 4. Construir o Prompt para Gemini
            prompt = f"""Com base APENAS no contexto fornecido abaixo, responda à pergunta do usuário. Se o contexto não contiver a resposta, diga que você não sabe com base nas informações disponíveis.

Contexto:
---
{context_string}
---

Pergunta: {user_query}

Resposta:"""

            # 5. Gerar Resposta com Gemini
            logger.info("Gerando resposta com o modelo Gemini...")
            gemini_model = get_gemini_model()
            try:
                response = gemini_model.generate_content(prompt)
                answer = response.text
                logger.info("Resposta gerada pelo Gemini.")
            except Exception as e:
                logger.error(f"Erro ao chamar a API do Gemini: {e}", exc_info=True)
                # Tentar obter mais detalhes do erro, se disponíveis
                error_details = getattr(e, "message", str(e))
                # Verificar se há 'prompt_feedback' no erro (útil para bloqueios de conteúdo)
                prompt_feedback = getattr(response, "prompt_feedback", None)
                if prompt_feedback:
                    error_details += f" | Feedback do Prompt: {prompt_feedback}"

                return Response(
                    {"error": f"Erro ao gerar resposta com Gemini: {error_details}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            # 6. Formatar e Retornar a Resposta da API
            response_data = {
                "query": user_query,
                "retrieved_context": retrieved_documents,
                "answer": answer,
                "model_used": settings.GEMINI_MODEL_NAME,
            }
            response_serializer = RagResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)  # Validar saída

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ConnectionError as e:
            logger.error(f"Erro de conexão com ChromaDB: {e}", exc_info=True)
            return Response(
                {"error": "Não foi possível conectar ao ChromaDB."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except RuntimeError as e:  # Erro de inicialização do Gemini/Embedding
            logger.error(f"Erro de configuração/runtime: {e}", exc_info=True)
            return Response(
                {"error": f"Erro interno de configuração: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            logger.error(f"Erro inesperado durante a consulta RAG: {e}", exc_info=True)
            return Response(
                {"error": f"Ocorreu um erro interno inesperado: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class FileUploadIngestView(APIView):
    """
    Endpoint para fazer upload de um arquivo (.txt, .pdf, .docx, .xlsx),
    extrair texto, dividir em chunks, gerar embeddings e adicionar ao ChromaDB.
    Use um request POST com multipart/form-data, com o arquivo no campo 'file'.
    """

    parser_classes = [parsers.MultiPartParser]  # Habilita o recebimento de arquivos

    def post(self, request, *args, **kwargs):
        serializer = FileUploadSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"Erro de validação no upload: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        uploaded_file = serializer.validated_data["file"]
        original_filename = uploaded_file.name

        # 1. Extrair Texto do Arquivo
        extracted_text, error_msg = extract_text_from_file(uploaded_file)

        if error_msg:
            # Se houve erro na extração ou tipo não suportado
            return Response({"error": error_msg}, status=status.HTTP_400_BAD_REQUEST)

        if not extracted_text or not extracted_text.strip():
            logger.warning(
                f"Nenhum texto extraído ou texto vazio para o arquivo '{original_filename}'."
            )
            return Response(
                {
                    "message": "Nenhum conteúdo de texto encontrado no arquivo.",
                    "filename": original_filename,
                },
                status=status.HTTP_200_OK,
            )

        logger.info(
            f"Texto extraído de '{original_filename}' (Tamanho: {len(extracted_text)} caracteres)."
        )

        # 2. Dividir o Texto em Chunks
        # Ajuste chunk_size e chunk_overlap conforme necessário
        # Gemini tem limites de tokens, chunks menores podem ser melhores
        chunks = simple_chunker(extracted_text, chunk_size=1500, chunk_overlap=150)
        if not chunks:
            logger.warning(
                f"Não foram gerados chunks para o arquivo '{original_filename}'."
            )
            return Response(
                {
                    "message": "O texto extraído não gerou chunks processáveis.",
                    "filename": original_filename,
                },
                status=status.HTTP_200_OK,
            )

        logger.info(f"Texto dividido em {len(chunks)} chunks.")

        # 3. Preparar dados para ChromaDB
        chunk_ids = generate_chunk_ids(original_filename, len(chunks))
        # Metadados: Incluir nome do arquivo original e índice do chunk
        # Garantir que o metadado nunca seja vazio
        metadatas = [
            {"source": original_filename, "chunk_index": i, "total_chunks": len(chunks)}
            for i in range(len(chunks))
        ]

        try:
            # 4. Gerar Embeddings para os Chunks (em lote)
            logger.info(
                f"Gerando embeddings para {len(chunks)} chunks de '{original_filename}'..."
            )
            # Usar "retrieval_document" para embeddings de documentos a serem armazenados
            embeddings = embed_text_gemini(chunks, task_type="retrieval_document")
            logger.info("Embeddings gerados com sucesso.")

            # 5. Adicionar ao ChromaDB
            chroma_client = get_chroma_client()
            collection = chroma_client.get_or_create_collection(
                name=settings.CHROMA_COLLECTION_NAME
            )

            logger.info(
                f"Adicionando {len(chunk_ids)} chunks à coleção '{settings.CHROMA_COLLECTION_NAME}'..."
            )
            collection.add(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=metadatas,
            )
            logger.info(
                f"Chunks do arquivo '{original_filename}' adicionados com sucesso."
            )

            return Response(
                {
                    "message": f"Arquivo '{original_filename}' processado e adicionado com sucesso.",
                    "chunks_added": len(chunks),
                    "collection": settings.CHROMA_COLLECTION_NAME,
                },
                status=status.HTTP_201_CREATED,
            )

        except ConnectionError as e:
            logger.error(
                f"Erro de conexão com ChromaDB ao processar '{original_filename}': {e}",
                exc_info=True,
            )
            return Response(
                {"error": "Não foi possível conectar ao ChromaDB."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ValueError as e:  # Capturar ValueErrors de validação ou outros
            logger.error(
                f"Erro de valor durante ingestão do arquivo '{original_filename}': {e}",
                exc_info=True,
            )
            return Response(
                {"error": f"Erro de validação ou processamento: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(
                f"Erro inesperado ao processar o arquivo '{original_filename}': {e}",
                exc_info=True,
            )
            return Response(
                {"error": f"Ocorreu um erro interno inesperado: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
