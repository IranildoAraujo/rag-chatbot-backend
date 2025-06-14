from django.urls import path, include  # Adicione include

urlpatterns = [
    path("api/", include("rag_api.urls")),  # Inclui as URLs do nosso app
]
