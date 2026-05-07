import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="OJS-Zenodo Bridge")

API_SECRET = os.getenv("API_SECRET")

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

    return {
        "status": "ok",
        "message": "Mini API funcionando",
        "article_id": payload.article_id
    }
