# SPDX-FileCopyrightText: Copyright (c) 2025 KX Systems, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the SEC filings -> RAG ingestion loader routes (sec_ingest.py)."""

import asyncio
import json
import sys
import types

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import kxta.fastapi_extensions.routes.sec_ingest as sec_ingest
from kxta.fastapi_extensions.routes.sec_ingest import add_sec_ingest_routes

RAG_URL = "http://ingestor-server:8082/v1"

# ---------------------------------------------------------------------------
# Fake edgartools objects
# ---------------------------------------------------------------------------


class FakeFiling:

    def __init__(self, form, filing_date, accession_no, html="<html><table><tr><td>42</td></tr></table></html>"):
        self.form = form
        self.filing_date = filing_date
        self.accession_no = accession_no
        self._html = html

    def html(self):
        return self._html

    def text(self):
        return "plain text filing"


class FakeFilings:

    def __init__(self, filings):
        self._filings = filings

    def head(self, n):
        return self._filings[:n]


class FakeCompany:
    """Fake edgar.Company returning canned filings per form."""

    filings_by_form = {
        "10-K": [FakeFiling("10-K", "2025-02-26", "0001045810-25-000023")],
        "10-Q": [FakeFiling("10-Q", "2025-05-28", "0001045810-25-000124")],
    }

    def __init__(self, ticker):
        self.ticker = ticker

    def get_filings(self, form=None):
        return FakeFilings(self.filings_by_form.get(form, []))


def install_fake_edgar(monkeypatch, company_cls=FakeCompany):
    """Install a fake `edgar` module so no network access happens."""
    import importlib.machinery
    fake = types.ModuleType("edgar")
    fake.__spec__ = importlib.machinery.ModuleSpec("edgar", loader=None)
    fake.Company = company_cls
    fake.set_identity = lambda identity: None
    monkeypatch.setitem(sys.modules, "edgar", fake)


# ---------------------------------------------------------------------------
# Fake httpx client
# ---------------------------------------------------------------------------


class FakeResponse:

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = text or json.dumps(self._json)

    def json(self):
        return self._json


class FakeAsyncClient:
    """Records calls made to the RAG ingestor and returns canned responses."""

    calls = []
    responses = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, params=None, files=None, data=None):
        FakeAsyncClient.calls.append({
            "method": "POST", "url": url, "json": json, "params": params, "files": files, "data": data
        })
        return FakeAsyncClient.responses.get(("POST", url), FakeResponse(200, {"message": "ok"}))

    async def get(self, url, params=None):
        FakeAsyncClient.calls.append({"method": "GET", "url": url, "params": params})
        return FakeAsyncClient.responses.get(("GET", url), FakeResponse(200, {"collections": []}))


@pytest.fixture
def fake_http(monkeypatch):
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = {}
    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    return FakeAsyncClient


@pytest.fixture
def client():
    app = FastAPI()
    asyncio.run(add_sec_ingest_routes(app, RAG_URL))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_ingest_happy_path_builds_multipart_and_collection(monkeypatch, fake_http, client):
    install_fake_edgar(monkeypatch)
    fake_http.responses[("POST",
                         f"{RAG_URL}/documents")] = FakeResponse(200, {
                             "message": "Documents ingested", "total_documents": 2
                         })

    resp = client.post("/sec/ingest", json={"ticker": "NVDA"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["ticker"] == "NVDA"
    assert body["collection"] == "sec_nvda"
    assert body["forms"] == ["10-K", "10-Q"]
    assert body["documents_uploaded"] == 2
    assert body["documents_failed"] == 0
    assert {f["form"] for f in body["filings"]} == {"10-K", "10-Q"}
    assert all(f["status"] == "uploaded" for f in body["filings"])

    # Collection creation call uses the ingestor conventions
    create_calls = [c for c in fake_http.calls if c["method"] == "POST" and c["url"] == f"{RAG_URL}/collections"]
    assert len(create_calls) == 1
    assert create_calls[0]["json"] == ["sec_nvda"]
    assert create_calls[0]["params"]["collection_type"] == "text"
    assert "embedding_dimension" in create_calls[0]["params"]

    # Upload call: multipart 'documents' files + 'data' JSON form field
    upload_calls = [c for c in fake_http.calls if c["method"] == "POST" and c["url"] == f"{RAG_URL}/documents"]
    assert len(upload_calls) == 1
    files = upload_calls[0]["files"]
    assert len(files) == 2
    for field_name, (filename, content, content_type) in files:
        assert field_name == "documents"
        assert filename.startswith("NVDA_10-")
        assert filename.endswith(".html")
        assert content_type == "text/html"
        assert b"<table>" in content
    metadata = json.loads(upload_calls[0]["data"]["data"])
    assert metadata["collection_name"] == "sec_nvda"
    assert metadata["blocking"] is True


def test_ingest_lowercase_ticker_and_count(monkeypatch, fake_http, client):
    install_fake_edgar(monkeypatch)

    resp = client.post("/sec/ingest", json={"ticker": "nvda", "forms": ["10-K"], "count": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "NVDA"
    assert body["collection"] == "sec_nvda"
    assert body["documents_uploaded"] == 1  # only one 10-K available


def test_ingest_existing_collection_tolerated(monkeypatch, fake_http, client):
    install_fake_edgar(monkeypatch)
    # Creation fails, but listing shows the collection already exists
    fake_http.responses[("POST", f"{RAG_URL}/collections")] = FakeResponse(500, text="already exists")
    fake_http.responses[("GET", f"{RAG_URL}/collections")] = FakeResponse(
        200, {"collections": [{
            "collection_name": "sec_nvda", "num_entities": 3
        }]})

    resp = client.post("/sec/ingest", json={"ticker": "NVDA", "forms": ["10-K"]})
    assert resp.status_code == 200
    assert resp.json()["documents_uploaded"] == 1


# ---------------------------------------------------------------------------
# Availability gating (503)
# ---------------------------------------------------------------------------


def test_503_when_rag_ingest_url_unset(monkeypatch):
    monkeypatch.delenv("RAG_INGEST_URL", raising=False)
    app = FastAPI()
    asyncio.run(add_sec_ingest_routes(app))  # no URL passed, env unset
    no_rag_client = TestClient(app)

    resp = no_rag_client.post("/sec/ingest", json={"ticker": "NVDA"})
    assert resp.status_code == 503
    assert "RAG_INGEST_URL" in resp.json()["detail"]

    resp = no_rag_client.get("/sec/collections")
    assert resp.status_code == 503


def test_503_when_edgartools_missing(monkeypatch, fake_http, client):
    monkeypatch.setattr(sec_ingest, "_edgartools_available", lambda: False)
    resp = client.post("/sec/ingest", json={"ticker": "NVDA"})
    assert resp.status_code == 503
    assert "edgartools" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Bad input (4xx)
# ---------------------------------------------------------------------------


def test_bad_ticker_rejected(client):
    resp = client.post("/sec/ingest", json={"ticker": "BAD TICKER!"})
    assert resp.status_code == 422

    resp = client.post("/sec/ingest", json={"ticker": ""})
    assert resp.status_code == 422


def test_bad_forms_and_count_rejected(client):
    resp = client.post("/sec/ingest", json={"ticker": "NVDA", "forms": []})
    assert resp.status_code == 422

    resp = client.post("/sec/ingest", json={"ticker": "NVDA", "forms": ["10-K; DROP"]})
    assert resp.status_code == 422

    resp = client.post("/sec/ingest", json={"ticker": "NVDA", "count": 0})
    assert resp.status_code == 422

    resp = client.post("/sec/ingest", json={"ticker": "NVDA", "count": 99})
    assert resp.status_code == 422


def test_unknown_ticker_404(monkeypatch, fake_http, client):

    class NotFoundCompany:

        def __init__(self, ticker):
            raise ValueError(f"Company not found for ticker {ticker}")

    install_fake_edgar(monkeypatch, company_cls=NotFoundCompany)
    resp = client.post("/sec/ingest", json={"ticker": "ZZZZ"})
    assert resp.status_code == 404


def test_no_filings_404(monkeypatch, fake_http, client):

    class EmptyCompany(FakeCompany):
        filings_by_form = {}

    install_fake_edgar(monkeypatch, company_cls=EmptyCompany)
    resp = client.post("/sec/ingest", json={"ticker": "NVDA"})
    assert resp.status_code == 404


def test_ingestor_upload_failure_502(monkeypatch, fake_http, client):
    install_fake_edgar(monkeypatch)
    fake_http.responses[("POST", f"{RAG_URL}/documents")] = FakeResponse(500, text="ingest error")
    resp = client.post("/sec/ingest", json={"ticker": "NVDA", "forms": ["10-K"]})
    assert resp.status_code == 502


# ---------------------------------------------------------------------------
# GET /sec/collections
# ---------------------------------------------------------------------------


def test_list_sec_collections_filters_prefix(fake_http, client):
    fake_http.responses[("GET", f"{RAG_URL}/collections")] = FakeResponse(
        200,
        {
            "collections": [
                {
                    "collection_name": "sec_nvda", "num_entities": 2
                },
                {
                    "collection_name": "sec_aapl", "num_entities": 4
                },
                {
                    "collection_name": "multimodal_data", "num_entities": 10
                },
            ]
        },
    )

    resp = client.get("/sec/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_collections"] == 2
    names = {c["collection_name"] for c in body["collections"]}
    assert names == {"sec_nvda", "sec_aapl"}
