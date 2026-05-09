import os
import requests
import tempfile

from typing import List, Optional

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    UploadFile,
    File,
    Form
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
# UPLOAD PDF FILE
# =========================

@app.post("/zenodo/upload-file")
async def upload_file_to_zenodo(

    zenodo_id: str = Form(...),

    file: UploadFile = File(...),

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

    # Obtener deposition actual
    deposition_response = requests.get(
        f"{ZENODO_BASE_URL}/api/deposit/depositions/{zenodo_id}",
        headers=headers
    )

    if deposition_response.status_code >= 400:

        raise HTTPException(
            status_code=deposition_response.status_code,
            detail=deposition_response.text
        )

    deposition_data = deposition_response.json()

    bucket_url = deposition_data["links"]["bucket"]

    # Guardar temporalmente
    suffix = os.path.splitext(file.filename)[1]

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix
    ) as tmp:

        content = await file.read()

        tmp.write(content)

        temp_path = tmp.name

    # Upload a Zenodo bucket
    with open(temp_path, "rb") as fp:

        upload_response = requests.put(
            f"{bucket_url}/{file.filename}",
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

        "zenodo_id": zenodo_id,

        "filename": file.filename
    }


# =========================
# OJS USER DIAGNOSTICS
# =========================

@app.get("/ojs/test-user")
def test_ojs_user(
    x_api_key: str = Header(None)
):

    try:

        if x_api_key != API_SECRET:

            raise HTTPException(
                status_code=401,
                detail="Unauthorized"
            )

        token = os.getenv("OJS_API_TOKEN")

        base = os.getenv("OJS_BASE_URL")

        auth_variants = {

            "Bearer": {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            },

            "Plain": {
                "Authorization": token,
                "Accept": "application/json"
            },

            "ApiToken": {
                "apiToken": token,
                "Accept": "application/json"
            }
        }

        urls = [

            f"{base}/api/v1/users",

            f"{base}/api/v1/users/current",

            f"{base}/api/v1/contexts"
        ]

        results = {}

        for auth_name, headers in auth_variants.items():

            results[auth_name] = {}

            for url in urls:

                try:

                    response = requests.get(
                        url,
                        headers=headers,
                        timeout=20
                    )

                    results[auth_name][url] = {

                        "status_code": response.status_code,

                        "headers": dict(response.headers),

                        "text_preview": str(
                            response.text
                        )[:500]
                    }

                except Exception as e:

                    results[auth_name][url] = {
                        "error": str(e)
                    }

        return results

    except Exception as e:

        return {
            "fatal_error": str(e)
        }


# =========================
# OJS SUBMISSION DIAGNOSTICS
# =========================

@app.get("/ojs/test-submission/{submission_id}")
def test_ojs_submission(
    submission_id: int,
    x_api_key: str = Header(None)
):

    if x_api_key != API_SECRET:

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    token = os.getenv("OJS_API_TOKEN")

    base = os.getenv("OJS_BASE_URL")

    auth_variants = {

        "Bearer": {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        },

        "Plain": {
            "Authorization": token,
            "Accept": "application/json"
        },

        "ApiToken": {
            "apiToken": token,
            "Accept": "application/json"
        }
    }

    urls = [

        f"{base}/api/v1/submissions/{submission_id}",

        f"{base}/api/v1/submissions"
    ]

    results = {}

    for auth_name, headers in auth_variants.items():

        results[auth_name] = {}

        for url in urls:

            try:

                response = requests.get(
                    url,
                    headers=headers,
                    timeout=20
                )

                results[auth_name][url] = {

                    "status_code": response.status_code,

                    "text_preview": response.text[:300]
                }

            except Exception as e:

                results[auth_name][url] = {
                    "error": str(e)
                }

    return results
