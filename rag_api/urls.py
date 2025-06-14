# rag_api/urls.py
from django.urls import path
from .views import IngestView, RagQueryView, FileUploadIngestView

urlpatterns = [
    path('ingest/', IngestView.as_view(), name='ingest_data'),
    path('query/', RagQueryView.as_view(), name='rag_query'),
    path('upload/', FileUploadIngestView.as_view(), name='upload_file'),
]