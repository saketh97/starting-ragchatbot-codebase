"""Tests for how RAGSystem handles content-related queries."""

from unittest.mock import MagicMock, patch

import pytest

from config import Config
from conftest import (
    DOCS_DIR,
    FakeAnthropicClient,
    fake_response,
    make_results,
    text_block,
    tool_use_block,
)
from rag_system import RAGSystem

# ---------- unit tests (VectorStore + AIGenerator mocked) ----------


@pytest.fixture
def rag():
    with patch("rag_system.VectorStore") as vs, patch("rag_system.AIGenerator") as ag:
        system = RAGSystem(Config(ANTHROPIC_API_KEY="k", CHROMA_PATH="unused"))
        system.mock_store = vs.return_value
        system.mock_gen = ag.return_value
        system.mock_gen.generate_response.return_value = "the answer"
        system.mock_store.get_lesson_link.return_value = "http://lesson"
        yield system


class TestQueryUnit:
    def test_passes_tools_and_manager_to_generator(self, rag):
        rag.query("What is MCP?")
        kwargs = rag.mock_gen.generate_response.call_args.kwargs
        assert {t["name"] for t in kwargs["tools"]} == {
            "search_course_content",
            "get_course_outline",
        }
        assert kwargs["tool_manager"] is rag.tool_manager
        assert "What is MCP?" in kwargs["query"]

    def test_returns_answer_and_empty_sources_when_no_search(self, rag):
        assert rag.query("hi") == ("the answer", [])

    def test_sources_come_from_search_tool_and_are_reset(self, rag):
        rag.mock_store.search.return_value = make_results(
            ["c"], [{"course_title": "MCP", "lesson_number": 2}]
        )

        def fake_generate(**kwargs):
            kwargs["tool_manager"].execute_tool("search_course_content", query="q")
            return "answer"

        rag.mock_gen.generate_response.side_effect = fake_generate

        answer, sources = rag.query("What is MCP?")
        assert answer == "answer"
        assert sources == [{"text": "MCP - Lesson 2", "link": "http://lesson"}]

        rag.mock_gen.generate_response.side_effect = None
        assert rag.query("general question")[1] == []  # no stale sources

    def test_session_history_is_stored_and_passed_on(self, rag):
        sid = rag.session_manager.create_session()
        rag.query("first", sid)
        assert (
            rag.mock_gen.generate_response.call_args.kwargs["conversation_history"]
            is None
        )
        rag.query("second", sid)
        history = rag.mock_gen.generate_response.call_args.kwargs[
            "conversation_history"
        ]
        assert "User: first" in history and "Assistant: the answer" in history

    def test_no_session_means_no_history(self, rag):
        rag.query("q")
        assert (
            rag.mock_gen.generate_response.call_args.kwargs["conversation_history"]
            is None
        )

    def test_generator_exception_propagates(self, rag):
        """app.py turns this into HTTP 500, which the frontend shows as 'Query failed'."""
        rag.mock_gen.generate_response.side_effect = RuntimeError("api down")
        with pytest.raises(RuntimeError):
            rag.query("What is MCP?")

    def test_failed_query_is_not_added_to_history(self, rag):
        sid = rag.session_manager.create_session()
        rag.mock_gen.generate_response.side_effect = RuntimeError("x")
        with pytest.raises(RuntimeError):
            rag.query("q", sid)
        assert rag.session_manager.get_conversation_history(sid) is None


# ---------- end-to-end (real Chroma + docs, scripted Anthropic client) ----------


def scripted(rag, responses):
    client = FakeAnthropicClient(responses)
    rag.ai_generator.client = client
    return client


class TestIngestion:
    def test_all_docs_ingested(self, ingested_rag):
        courses, chunks = ingested_rag.ingest_result
        assert courses == len(list(DOCS_DIR.glob("*.txt"))) and chunks > 0
        assert ingested_rag.get_course_analytics()["total_courses"] == courses

    def test_reingest_skips_existing(self, ingested_rag):
        assert ingested_rag.add_course_folder(str(DOCS_DIR)) == (0, 0)


class TestQueryEndToEnd:
    def test_content_question_runs_real_search_and_returns_sources(self, ingested_rag):
        search = tool_use_block(
            "t1",
            "search_course_content",
            {"query": "What is MCP about?", "course_name": "MCP"},
        )
        client = scripted(
            ingested_rag,
            [
                fake_response("tool_use", [search]),
                fake_response("end_turn", [text_block("MCP is a protocol.")]),
            ],
        )
        answer, sources = ingested_rag.query("What is MCP about?")

        assert answer == "MCP is a protocol."
        tool_result = client.calls[1]["messages"][-1]["content"][0]["content"]
        assert (
            tool_result.startswith("[") and "MCP" in tool_result
        )  # real chunks reached the model
        assert sources and all(s["text"] and s["link"] for s in sources)

    def test_lesson_filtered_question(self, ingested_rag):
        search = tool_use_block(
            "t1",
            "search_course_content",
            {"query": "overview", "course_name": "MCP", "lesson_number": 1},
        )
        client = scripted(
            ingested_rag,
            [
                fake_response("tool_use", [search]),
                fake_response("end_turn", [text_block("ok")]),
            ],
        )
        ingested_rag.query("What does lesson 1 of the MCP course cover?")
        result = client.calls[1]["messages"][-1]["content"][0]["content"]
        assert not result.startswith(
            ("No relevant", "Search error", "No course found")
        ), result
        assert "Lesson 1]" in result

    def test_outline_question(self, ingested_rag):
        outline = tool_use_block("t1", "get_course_outline", {"course_title": "MCP"})
        client = scripted(
            ingested_rag,
            [
                fake_response("tool_use", [outline]),
                fake_response("end_turn", [text_block("outline")]),
            ],
        )
        ingested_rag.query("List the lessons in the MCP course")
        result = client.calls[1]["messages"][-1]["content"][0]["content"]
        assert result.startswith("Course: ") and "Lesson 1:" in result

    def test_full_content_flow_with_session(self, ingested_rag):
        search = tool_use_block("t1", "search_course_content", {"query": "chroma"})
        scripted(
            ingested_rag,
            [
                fake_response("tool_use", [search]),
                fake_response("end_turn", [text_block("Answer one")]),
                fake_response("end_turn", [text_block("Answer two")]),
            ],
        )
        sid = ingested_rag.session_manager.create_session()
        ingested_rag.query("Tell me about chroma", sid)
        _, sources = ingested_rag.query("and more?", sid)
        assert sources == []  # second turn did no search -> sources were reset
        assert "Answer one" in ingested_rag.session_manager.get_conversation_history(
            sid
        )
