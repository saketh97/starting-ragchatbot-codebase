"""Shared helpers and fixtures for the RAG chatbot tests."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
DOCS_DIR = BACKEND_DIR.parent / "docs"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from vector_store import SearchResults, VectorStore  # noqa: E402


# ---------- SearchResults helpers ----------

def make_results(docs=None, metas=None, error=None):
    docs = docs or []
    metas = metas or []
    return SearchResults(documents=docs, metadata=metas, distances=[0.1] * len(docs), error=error)


@pytest.fixture
def mock_store():
    store = MagicMock(spec=VectorStore)
    store.get_lesson_link.return_value = None
    return store


# ---------- Fake Anthropic objects ----------

def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def fake_response(stop_reason, blocks):
    return SimpleNamespace(stop_reason=stop_reason, content=blocks)


class FakeAnthropicClient:
    """Stands in for anthropic.Anthropic(); returns scripted responses and records every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs["messages"])  # the generator keeps appending to its list
        self.calls.append(snapshot)
        if not self._responses:
            raise AssertionError("FakeAnthropicClient ran out of scripted responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fake_client_factory():
    return FakeAnthropicClient


# ---------- API testing (FastAPI TestClient against a test app with a mocked RAGSystem) ----------

@pytest.fixture
def sample_sources():
    return [
        {"text": "MCP Course - Lesson 1", "link": "http://lesson/1"},
        {"text": "MCP Course - Lesson 2", "link": None},
    ]


@pytest.fixture
def sample_courses():
    return {"total_courses": 2, "course_titles": ["MCP Course", "Retrieval Course"]}


@pytest.fixture
def mock_rag(sample_sources, sample_courses):
    """A RAGSystem stand-in: no Chroma, no embeddings, no Anthropic calls."""
    rag = MagicMock()
    rag.session_manager.create_session.return_value = "session-1"
    rag.query.return_value = ("the answer", sample_sources)
    rag.get_course_analytics.return_value = sample_courses
    return rag


@pytest.fixture
def client(mock_rag):
    from fastapi.testclient import TestClient
    from api_app import create_test_app

    return TestClient(create_test_app(mock_rag))


# ---------- Real vector store (tmp Chroma, real docs, real embeddings) ----------

@pytest.fixture(scope="session")
def real_rag_parts(tmp_path_factory):
    """(VectorStore, DocumentProcessor, courses_added, chunks_added) built from ../docs in a temp dir."""
    from config import config
    from document_processor import DocumentProcessor

    if not DOCS_DIR.exists():
        pytest.skip("docs/ folder not found")
    try:
        store = VectorStore(str(tmp_path_factory.mktemp("chroma")), config.EMBEDDING_MODEL, config.MAX_RESULTS)
    except Exception as e:  # e.g. embedding model can't be loaded/downloaded
        pytest.skip(f"could not build real VectorStore: {e}")

    processor = DocumentProcessor(config.CHUNK_SIZE, config.CHUNK_OVERLAP)
    courses = chunks = 0
    for path in sorted(DOCS_DIR.glob("*.txt")):
        course, course_chunks = processor.process_course_document(str(path))
        store.add_course_metadata(course)
        store.add_course_content(course_chunks)
        courses += 1
        chunks += len(course_chunks)
    return store, processor, courses, chunks


@pytest.fixture
def real_store(real_rag_parts):
    return real_rag_parts[0]


@pytest.fixture(scope="session")
def ingested_rag(tmp_path_factory):
    """A full RAGSystem (real Chroma in a temp dir, real embeddings) with ../docs ingested.
    The Anthropic client is a dummy; tests swap in FakeAnthropicClient or a real key."""
    from config import Config
    from rag_system import RAGSystem

    if not DOCS_DIR.exists():
        pytest.skip("docs/ folder not found")
    cfg = Config(ANTHROPIC_API_KEY="test-key", CHROMA_PATH=str(tmp_path_factory.mktemp("chroma_rag")))
    try:
        rag = RAGSystem(cfg)
    except Exception as e:
        pytest.skip(f"could not build RAGSystem: {e}")
    rag.ingest_result = rag.add_course_folder(str(DOCS_DIR))
    return rag
