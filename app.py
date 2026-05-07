import os
import requests
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="OJS-Zenodo Bridge")

API_SECRET = os.getenv("API_SECRET")
ZENODO_TOKEN = os.getenv("ZENODO_TOKEN")
ZENODO_BASE_URL = os.getenv("ZENODO_BASE_URL", "https://zenodo.org")

class DraftRequest(BaseModel):
    article_id: int

@app.get("/")
def root():
    return {"message": "OJS-Zenodo API running"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/zenodo/draft-from-ojs")
def create_draft(payload: DraftRequest, x_api_key: str = Header(None)):

    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    headers = {
        "Authorization": f"Bearer {ZENODO_TOKEN}",
        "Content-Type": "application/json"
    }

    metadata = {
        "metadata": {
            "title": f"Draft test article {payload.article_id}",
            "upload_type": "publication",
            "publication_type": "article",
            "description": "Test draft generated from OJS-Zenodo bridge.",
            "creators": [
                {
                    "name": "Chaux, Alcides"
                }
            ],
            "communities": [
                {
                    "identifier": "scripta_scientia"
                }
            ],
            "license": "cc-by-4.0"
        }
    }

    response = requests.post(
        f"{ZENODO_BASE_URL}/api/deposit/depositions",
        json=metadata,
        headers=headers
    )

    if response.status_code >= 400:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text
        )

    data = response.json()

    return {
        "status": "draft_created",
        "article_id": payload.article_id,
        "zenodo_id": data["id"],
        "doi": data["metadata"].get("prereserve_doi", {}).get("doi"),
        "url": data["links"]["html"]
    }

@app.get("/ojs/test-submission/{submission_id}")
def test_ojs_submission(submission_id: int, x_api_key: str = Header(None)):

    if x_api_key != API_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    headers = {
        "Authorization": f"Bearer {os.getenv('OJS_API_TOKEN')}"
    }

    base = os.getenv("OJS_BASE_URL")

    urls = [
        f"{base}/api/v1/submissions/{submission_id}",
        f"{base}/api/v1/_submissions/{submission_id}",
        f"{base}/api/v1/submissions"
    ]

    results = {}

    for url in urls:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=20
            )

            results[url] = {
                "status_code": response.status_code,
                "text_preview": response.text[:500]
            }

        except Exception as e:
            results[url] = {
                "error": str(e)
            }

    return results
