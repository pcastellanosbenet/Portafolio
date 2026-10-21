from app.main import create_app
from fastapi.testclient import TestClient

from src.config import Settings


def test_health_query_and_documents(agent, store, sample_documents, tmp_path) -> None:
    settings = Settings(artifacts_dir=tmp_path, corpus_dir=tmp_path)
    app = create_app(
        settings=settings,
        agent=agent,
        store=store,
        documents=sample_documents,
    )
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["chunks"] == 4

        response = client.post(
            "/v1/query",
            json={"question": "What is DPT 1.001?", "top_k": 3},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["citations"]
        assert payload["citations"][0]["page_start"] == 21

        documents = client.get("/v1/documents")
        assert documents.status_code == 200
        assert documents.json()[0]["doc_id"] == "doc-dpt"

        detail = client.get("/v1/documents/doc-dpt")
        assert detail.status_code == 200
        assert detail.json()["title"] == "Datapoint Types"

        missing = client.get("/v1/documents/missing")
        assert missing.status_code == 404
