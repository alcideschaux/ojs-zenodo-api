import os
import requests
import tempfile

from typing import List, Optional

from fastapi import (
    FastAPI,
    Header,
    HTTPException
)

from pydantic import BaseModel


app = FastAPI(title="OJS-Zenodo Bridge")


API_SECRET = os.getenv("API_SECRET")

ZENODO_TOKEN = os.getenv("ZENODO_TOKEN")

ZENODO_BASE_URL = os.getenv(
    "ZENODO_BASE_URL",
    "https://zenodo.org"
)


# =========================
# MODELOS
# =========================

class Author(BaseModel):

    name: str

    affiliation: Optional[str] = None

    orcid: Optional[str] = None


class ZenodoDraftRequest(BaseModel):

    title: str

    abstract: str

    doi: str

    authors: List[Author]

    keywords: Optional[List[str]] = []

    language: Optional[str] = "spa"


class UploadFromUrlRequest(BaseModel):

    zenodo_id: str

    pdf_url: str

    filename: Optional[str] = "article.pdf"


class AutoDepositRequest(BaseModel):

    doi: str

    pdf_url: str

    filename: Optional[str] = "article.pdf"


# =========================
# HEALTH
# =========================

@app.get("/")
def root():

    return {
        "message": "OJS-Zenodo API running"
    }


@app.get("/health")
def health():

    return {
        "status": "ok"
    }


# =========================
# CREATE ZENODO DRAFT
# =========================

@app.post("/zenodo/create-draft")
def create_zenodo_draft(
    payload: ZenodoDraftRequest,
    x_api_key: str = Header(None)
):

    if x_api_key != API_SECRET:

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    headers = {

        "Authorization": f"Bearer {ZENODO_TOKEN}",

        "Content-Type": "application/json"
    }

    creators = []

    for author in payload.authors:

        creator = {
            "name": author.name
        }

        if author.affiliation:

            creator["affiliation"] = author.affiliation

        if author.orcid:

            creator["orcid"] = author.orcid

        creators.append(creator)

    metadata = {

        "metadata": {

            "title": payload.title,

            "upload_type": "publication",

            "publication_type": "article",

            "description": payload.abstract,

            "creators": creators,

            "keywords": payload.keywords,

            "language": payload.language,

            "license": "cc-by-4.0",

            "communities": [
                {
                    "identifier": "scripta_scientia"
                }
            ],

            "related_identifiers": [
                {
                    "relation": "isSupplementTo",

                    "identifier": payload.doi,

                    "scheme": "doi",

                    "resource_type": "publication-article"
                }
            ]
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

        "zenodo_id": data["id"],

        "doi": data["metadata"].get(
            "prereserve_doi",
            {}
        ).get("doi"),

        "bucket_url": data["links"]["bucket"],

        "url": data["links"]["html"]
    }


# =========================
# UPLOAD PDF FROM URL
# =========================

@app.post("/zenodo/upload-from-url")
def upload_from_url(
    payload: UploadFromUrlRequest,
    x_api_key: str = Header(None)
):

    if x_api_key != API_SECRET:

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    headers = {
        "Authorization": f"Bearer {ZENODO_TOKEN}"
    }

    deposition_response = requests.get(
        f"{ZENODO_BASE_URL}/api/deposit/depositions/{payload.zenodo_id}",
        headers=headers
    )

    if deposition_response.status_code >= 400:

        raise HTTPException(
            status_code=deposition_response.status_code,
            detail=deposition_response.text
        )

    deposition_data = deposition_response.json()

    bucket_url = deposition_data["links"]["bucket"]

    pdf_response = requests.get(
        payload.pdf_url,
        timeout=60
    )

    if pdf_response.status_code >= 400:

        raise HTTPException(
            status_code=pdf_response.status_code,
            detail="Could not download PDF"
        )

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf"
    ) as tmp:

        tmp.write(pdf_response.content)

        temp_path = tmp.name

    with open(temp_path, "rb") as fp:

        upload_response = requests.put(
            f"{bucket_url}/{payload.filename}",
            data=fp,
            headers=headers
        )

    os.remove(temp_path)

    if upload_response.status_code >= 400:

        raise HTTPException(
            status_code=upload_response.status_code,
            detail=upload_response.text
        )

    return {

        "status": "file_uploaded",

        "zenodo_id": payload.zenodo_id,

        "filename": payload.filename
    }


# =========================
# FULL AUTO DEPOSIT
# =========================

@app.post("/zenodo/auto-deposit")
def auto_deposit(
    payload: AutoDepositRequest,
    x_api_key: str = Header(None)
):

    if x_api_key != API_SECRET:

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # ===================================
    # CROSSREF METADATA
    # ===================================

    crossref_response = requests.get(
        f"https://api.crossref.org/works/{payload.doi}",
        timeout=60
    )

    if crossref_response.status_code >= 400:

        raise HTTPException(
            status_code=404,
            detail="DOI not found in Crossref"
        )

    crossref_data = crossref_response.json()["message"]

    title = crossref_data.get(
        "title",
        ["Untitled"]
    )[0]

    abstract = crossref_data.get(
        "abstract",
        ""
    )

    language = crossref_data.get(
        "language",
        "eng"
    )

    keywords = crossref_data.get(
        "subject",
        []
    )

    authors = []

    for author in crossref_data.get("author", []):

        given = author.get("given", "")

        family = author.get("family", "")

        full_name = f"{family}, {given}".strip(", ")

        affiliation = ""

        if author.get("affiliation"):

            affiliation = author["affiliation"][0].get(
                "name",
                ""
            )

        authors.append({
            "name": full_name,
            "affiliation": affiliation,
            "orcid": author.get("ORCID", "")
        })

    # ===================================
    # CREATE DRAFT
    # ===================================

    draft_payload = {

        "title": title,

        "abstract": abstract,

        "doi": payload.doi,

        "authors": authors,

        "keywords": keywords,

        "language": language
    }

    draft_response = create_zenodo_draft(
        ZenodoDraftRequest(**draft_payload),
        x_api_key
    )

    zenodo_id = draft_response["zenodo_id"]

    # ===================================
    # UPLOAD PDF
    # ===================================

    upload_payload = UploadFromUrlRequest(

        zenodo_id=str(zenodo_id),

        pdf_url=payload.pdf_url,

        filename=payload.filename
    )

    upload_response = upload_from_url(
        upload_payload,
        x_api_key
    )

    return {

        "status": "auto_deposit_completed",

        "zenodo_id": zenodo_id,

        "zenodo_doi": draft_response["doi"],

        "zenodo_url": draft_response["url"],

        "upload_status": upload_response["status"]
    }
