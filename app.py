import os
import requests
import tempfile

from bs4 import BeautifulSoup

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


class AutoDepositRequest(BaseModel):

    doi: str

    article_url: str

    filename: Optional[str] = "article.pdf"


# =========================
# HELPERS
# =========================

def extract_meta(soup, name):

    tag = soup.find(
        "meta",
        attrs={"name": name}
    )

    if tag:

        return tag.get("content", "")

    return ""


def extract_all_meta(soup, name):

    tags = soup.find_all(
        "meta",
        attrs={"name": name}
    )

    values = []

    for tag in tags:

        content = tag.get("content", "").strip()

        if content:

            values.append(content)

    return values


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
# FULL AUTO DEPOSIT
# =========================

@app.post("/zenodo/auto-deposit")
def auto_deposit(
    payload: AutoDepositRequest,
    x_api_key: str = Header(None)
):

    # ===================================
    # AUTH
    # ===================================

    if x_api_key != API_SECRET:

        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

    # ===================================
    # CROSSREF
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

    # ===================================
    # OJS LANDING PAGE
    # ===================================

    article_response = requests.get(
        payload.article_url,
        timeout=60
    )

    if article_response.status_code >= 400:

        raise HTTPException(
            status_code=404,
            detail="Could not access article URL"
        )

    soup = BeautifulSoup(
        article_response.text,
        "html.parser"
    )

    # ===================================
    # METADATA EXTRACTION
    # ===================================

    title = extract_meta(
        soup,
        "citation_title"
    )

    if not title:

        title = crossref_data.get(
            "title",
            ["Untitled"]
        )[0]

    abstract = extract_meta(
        soup,
        "description"
    )

    if not abstract:

        abstract = crossref_data.get(
            "abstract",
            ""
        )

    keywords = extract_all_meta(
        soup,
        "citation_keywords"
    )

    language = extract_meta(
        soup,
        "citation_language"
    )

    if not language:

        language = "spa"

    journal_title = extract_meta(
        soup,
        "citation_journal_title"
    )

    volume = extract_meta(
        soup,
        "citation_volume"
    )

    issue = extract_meta(
        soup,
        "citation_issue"
    )

    publication_date = extract_meta(
        soup,
        "citation_publication_date"
    )

    pdf_url = extract_meta(
        soup,
        "citation_pdf_url"
    )

    issn = extract_meta(
        soup,
        "citation_issn"
    )

    publisher = "ChauxLab Institute"

    # ===================================
    # AUTHORS
    # ===================================

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
    # CREATE ZENODO DRAFT
    # ===================================

    headers = {

        "Authorization": f"Bearer {ZENODO_TOKEN}",

        "Content-Type": "application/json"
    }

    metadata = {

        "metadata": {

            "title": title,

            "upload_type": "publication",

            "publication_type": "article",

            "description": abstract,

            "creators": authors,

            "keywords": keywords,

            "language": language,

            "license": "cc-by-4.0",

            "publisher": publisher,

            "journal_title": journal_title,

            "journal_volume": volume,

            "journal_issue": issue,

            "notes": (
                f"Published in {journal_title}. "
                f"ISSN: {issn}. "
                f"Publication date: {publication_date}."
            ),

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

    draft_response = requests.post(
        f"{ZENODO_BASE_URL}/api/deposit/depositions",
        json=metadata,
        headers=headers
    )

    if draft_response.status_code >= 400:

        raise HTTPException(
            status_code=draft_response.status_code,
            detail=draft_response.text
        )

    draft_data = draft_response.json()

    zenodo_id = draft_data["id"]

    bucket_url = draft_data["links"]["bucket"]

    # ===================================
    # PDF DOWNLOAD
    # ===================================

    if not pdf_url:

        pdf_url = payload.article_url

    pdf_response = requests.get(
        pdf_url,
        timeout=60
    )

    if pdf_response.status_code >= 400:

        raise HTTPException(
            status_code=404,
            detail="Could not download PDF"
        )

    # ===================================
    # TEMP FILE
    # ===================================

    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".pdf"
    ) as tmp:

        tmp.write(pdf_response.content)

        temp_path = tmp.name

    # ===================================
    # ZENODO BUCKET UPLOAD
    # ===================================

    upload_headers = {

        "Authorization": f"Bearer {ZENODO_TOKEN}",

        "Content-Type": "application/octet-stream"
    }

    with open(temp_path, "rb") as fp:

        upload_response = requests.put(
            f"{bucket_url}/{payload.filename}",
            data=fp,
            headers=upload_headers
        )

    os.remove(temp_path)

    if upload_response.status_code >= 400:

        raise HTTPException(
            status_code=upload_response.status_code,
            detail=upload_response.text
        )

    # ===================================
    # SUCCESS
    # ===================================

    return {

        "status": "auto_deposit_completed",

        "zenodo_id": zenodo_id,

        "zenodo_doi": draft_data["metadata"].get(
            "prereserve_doi",
            {}
        ).get("doi"),

        "zenodo_url": draft_data["links"]["html"],

        "journal_title": journal_title,

        "keywords": keywords,

        "language": language,

        "pdf_url": pdf_url
    }
