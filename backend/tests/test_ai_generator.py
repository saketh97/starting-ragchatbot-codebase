"""Tests that AIGenerator calls the CourseSearchTool correctly (Anthropic client is faked)."""
from unittest.mock import MagicMock, patch

import pytest

from ai_generator import AIGenerator
from conftest import FakeAnthropicClient, fake_response, text_block, tool_use_block

TOOLS = [{"name": "search_course_content", "description": "d", "input_schema": {"type": "object", "properties": {}}}]


def make_generator(responses):
    client = FakeAnthropicClient(responses)
    with patch("ai_generator.anthropic.Anthropic", return_value=client):
        gen = AIGenerator("key", "model-x")
    return gen, client


def tool_manager(result="RESULT"):
    tm = MagicMock()
    tm.execute_tool.return_value = result
    return tm


class TestFirstCall:
    def test_tools_and_auto_choice_sent_when_provided(self):
        gen, client = make_generator([fake_response("end_turn", [text_block("hi")])])
        gen.generate_response("q", tools=TOOLS, tool_manager=tool_manager())
        call = client.calls[0]
        assert call["tools"] == TOOLS and call["tool_choice"] == {"type": "auto"}
        assert call["model"] == "model-x"
        assert call["messages"] == [{"role": "user", "content": "q"}]

    def test_no_tools_key_when_not_provided(self):
        gen, client = make_generator([fake_response("end_turn", [text_block("hi")])])
        gen.generate_response("q")
        assert "tools" not in client.calls[0] and "tool_choice" not in client.calls[0]

    def test_history_appended_to_system_prompt(self):
        gen, client = make_generator([fake_response("end_turn", [text_block("hi")])])
        gen.generate_response("q", conversation_history="User: a\nAssistant: b")
        assert "Previous conversation:\nUser: a\nAssistant: b" in client.calls[0]["system"]

    def test_system_prompt_instructs_search_for_course_content(self):
        p = AIGenerator.SYSTEM_PROMPT
        assert "search_course_content" in p and "get_course_outline" in p
        assert "Course-specific questions" in p and "Search first" in p


class TestDirectAnswer:
    def test_end_turn_returns_text_without_tools_used(self):
        gen, client = make_generator([fake_response("end_turn", [text_block("General answer")])])
        tm = tool_manager()
        assert gen.generate_response("q", tools=TOOLS, tool_manager=tm) == "General answer"
        tm.execute_tool.assert_not_called()
        assert len(client.calls) == 1


class TestToolExecution:
    def test_tool_called_with_model_input_and_result_sent_back(self):
        tu = tool_use_block("tu_1", "search_course_content", {"query": "MCP", "course_name": "MCP", "lesson_number": 1})
        first = fake_response("tool_use", [text_block("Searching"), tu])
        gen, client = make_generator([first, fake_response("end_turn", [text_block("Final")])])
        tm = tool_manager("SEARCH RESULT")

        out = gen.generate_response("q", tools=TOOLS, tool_manager=tm)

        assert out == "Final"
        tm.execute_tool.assert_called_once_with("search_course_content", query="MCP", course_name="MCP", lesson_number=1)
        follow_up = client.calls[1]["messages"]
        assert follow_up[0] == {"role": "user", "content": "q"}
        assert follow_up[1] == {"role": "assistant", "content": first.content}
        assert follow_up[2]["role"] == "user"
        assert follow_up[2]["content"][0] == {"type": "tool_result", "tool_use_id": "tu_1", "content": "SEARCH RESULT"}

    def test_multiple_tool_use_blocks_all_executed(self):
        first = fake_response("tool_use", [
            tool_use_block("a", "search_course_content", {"query": "one"}),
            tool_use_block("b", "get_course_outline", {"course_title": "MCP"}),
        ])
        gen, client = make_generator([first, fake_response("end_turn", [text_block("Done")])])
        tm = tool_manager()
        gen.generate_response("q", tools=TOOLS, tool_manager=tm)
        assert tm.execute_tool.call_count == 2
        results = client.calls[1]["messages"][2]["content"]
        assert [r["tool_use_id"] for r in results if r["type"] == "tool_result"] == ["a", "b"]

    def test_two_round_chain(self):
        r1 = fake_response("tool_use", [tool_use_block("a", "search_course_content", {"query": "one"})])
        r2 = fake_response("tool_use", [tool_use_block("b", "search_course_content", {"query": "two"})])
        gen, client = make_generator([r1, r2, fake_response("end_turn", [text_block("Answer")])])
        tm = tool_manager()
        assert gen.generate_response("q", tools=TOOLS, tool_manager=tm) == "Answer"
        assert tm.execute_tool.call_count == 2
        assert len(client.calls) == 3

    def test_round_cap_and_last_call_has_no_tools(self):
        """Model keeps asking for tools: we must stop after MAX_TOOL_ROUNDS and still return text."""
        n = AIGenerator.MAX_TOOL_ROUNDS
        responses = [fake_response("tool_use", [tool_use_block(f"t{i}", "search_course_content", {"query": "q"})])
                     for i in range(n + 1)]
        gen, client = make_generator(responses)
        tm = tool_manager()
        gen.generate_response("q", tools=TOOLS, tool_manager=tm)
        assert tm.execute_tool.call_count == n
        assert len(client.calls) == n + 1
        assert "tools" in client.calls[1]          # intermediate follow-up keeps tools
        assert "tools" not in client.calls[-1]     # final follow-up drops them

    def test_last_round_request_still_contains_tool_blocks(self):
        """Documents the request shape sent when tools are dropped: history has tool_use/tool_result blocks
        but no `tools` param. The live test tells us whether the real API accepts this."""
        n = AIGenerator.MAX_TOOL_ROUNDS
        responses = [fake_response("tool_use", [tool_use_block(f"t{i}", "search_course_content", {"query": "q"})])
                     for i in range(n)] + [fake_response("end_turn", [text_block("ok")])]
        gen, client = make_generator(responses)
        gen.generate_response("q", tools=TOOLS, tool_manager=tool_manager())
        last = client.calls[-1]
        has_tool_history = any(isinstance(m["content"], list) and any(
            (isinstance(b, dict) and b.get("type") == "tool_result") or getattr(b, "type", "") == "tool_use"
            for b in m["content"]) for m in last["messages"])
        assert has_tool_history and "tools" not in last


class TestEdgeCases:
    def test_tool_use_without_tool_manager_still_returns_something(self):
        gen, _ = make_generator([fake_response("tool_use", [tool_use_block("a", "search_course_content", {"query": "q"})])])
        assert gen.generate_response("q", tools=TOOLS, tool_manager=None) != ""

    def test_tool_exception_does_not_crash_request(self):
        tu = tool_use_block("a", "search_course_content", {"query": "q"})
        gen, client = make_generator([fake_response("tool_use", [tu]), fake_response("end_turn", [text_block("Sorry")])])
        tm = MagicMock()
        tm.execute_tool.side_effect = RuntimeError("chroma exploded")
        # An uncaught exception here would become HTTP 500 -> "Query failed" in the UI.
        assert gen.generate_response("q", tools=TOOLS, tool_manager=tm) == "Sorry"
        result = client.calls[1]["messages"][2]["content"][0]
        assert result["is_error"] is True and "chroma exploded" in result["content"]

    def test_api_error_propagates(self):
        gen, _ = make_generator([RuntimeError("401 invalid x-api-key")])
        with pytest.raises(RuntimeError):
            gen.generate_response("q", tools=TOOLS, tool_manager=tool_manager())

    def test_empty_final_answer_is_flagged(self):
        tu = tool_use_block("a", "search_course_content", {"query": "q"})
        gen, _ = make_generator([fake_response("tool_use", [tu]), fake_response("end_turn", [])])
        assert gen.generate_response("q", tools=TOOLS, tool_manager=tool_manager()) != ""
