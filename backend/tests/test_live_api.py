"""Opt-in test against the REAL Anthropic API (costs a few calls). Run: uv run pytest tests -m live -v -s"""

import pytest

from config import config

pytestmark = pytest.mark.live


@pytest.fixture
def live_rag(ingested_rag):
    if not config.ANTHROPIC_API_KEY:
        pytest.skip("ANTHROPIC_API_KEY not set")
    from ai_generator import AIGenerator

    ingested_rag.ai_generator = AIGenerator(
        config.ANTHROPIC_API_KEY, config.ANTHROPIC_MODEL
    )
    return ingested_rag


def test_real_content_query(live_rag):
    answer, sources = live_rag.query("What is MCP and what are its main components?")
    print("\nANSWER:", answer, "\nSOURCES:", sources)
    assert answer.strip()
    assert sources, "model never called the search tool for a course-content question"


def test_real_general_query_without_search(live_rag):
    answer, sources = live_rag.query("What is 2 + 2?")
    assert answer.strip() and sources == []
