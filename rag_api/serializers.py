# rag_api/serializers.py
from rest_framework import serializers

class DocumentSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=200)
    text = serializers.CharField()
    metadata = serializers.DictField(required=False, default={})

class IngestSerializer(serializers.Serializer):
    documents = serializers.ListField(
        child=DocumentSerializer(),
        allow_empty=False
    )

class QuerySerializer(serializers.Serializer):
    query = serializers.CharField(max_length=1000)
    top_k = serializers.IntegerField(min_value=1, max_value=10, default=3) # Quantos documentos buscar

class RagResponseSerializer(serializers.Serializer):
    query = serializers.CharField()
    retrieved_context = serializers.ListField(child=serializers.CharField())
    answer = serializers.CharField()
    model_used = serializers.CharField()

class FileUploadSerializer(serializers.Serializer):
    # 'file' é o nome esperado para o campo no formulário multipart
    file = serializers.FileField(max_length=None, allow_empty_file=False)
    # Você pode adicionar outros campos aqui se precisar passar metadados extras
    # source_tag = serializers.CharField(max_length=100, required=False)