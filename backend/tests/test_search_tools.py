"""Tests for CourseSearchTool.execute (and the tool plumbing around it)."""
import re

from conftest import make_results
from search_tools import CourseOutlineTool, CourseSearchTool, ToolManager


# ---------- unit tests (mocked VectorStore) ----------

class TestExecuteUnit:
    def test_forwards_arguments_to_store(self, mock_store):
        mock_store.search.return_value = make_results(["x"], [{"course_title": "C", "lesson_number": 1}])
        CourseSearchTool(mock_store).execute("what is MCP", course_name="MCP", lesson_number=2)
        mock_store.search.assert_called_once_with(query="what is MCP", course_name="MCP", lesson_number=2)

    def test_defaults_filters_to_none(self, mock_store):
        mock_store.search.return_value = make_results(["x"], [{"course_title": "C", "lesson_number": 1}])
        CourseSearchTool(mock_store).execute("q")
        mock_store.search.assert_called_once_with(query="q", course_name=None, lesson_number=None)

    def test_formats_header_and_content(self, mock_store):
        mock_store.search.return_value = make_results(
            ["Chunk about servers", "Chunk about clients"],
            [{"course_title": "MCP Course", "lesson_number": 3}, {"course_title": "MCP Course", "lesson_number": 4}],
        )
        out = CourseSearchTool(mock_store).execute("q")
        assert "[MCP Course - Lesson 3]\nChunk about servers" in out
        assert "[MCP Course - Lesson 4]\nChunk about clients" in out

    def test_header_without_lesson_number(self, mock_store):
        mock_store.search.return_value = make_results(["body"], [{"course_title": "MCP Course"}])
        out = CourseSearchTool(mock_store).execute("q")
        assert out.startswith("[MCP Course]\nbody")

    def test_lesson_zero_is_formatted_in_header(self, mock_store):
        mock_store.search.return_value = make_results(["intro"], [{"course_title": "C", "lesson_number": 0}])
        assert "[C - Lesson 0]" in CourseSearchTool(mock_store).execute("q")

    def test_store_error_is_returned_verbatim(self, mock_store):
        mock_store.search.return_value = make_results(error="Search error: boom")
        assert CourseSearchTool(mock_store).execute("q") == "Search error: boom"

    def test_empty_results_no_filters(self, mock_store):
        mock_store.search.return_value = make_results()
        assert CourseSearchTool(mock_store).execute("q") == "No relevant content found."

    def test_empty_results_with_course_and_lesson(self, mock_store):
        mock_store.search.return_value = make_results()
        out = CourseSearchTool(mock_store).execute("q", course_name="MCP", lesson_number=2)
        assert out == "No relevant content found in course 'MCP' in lesson 2."

    def test_empty_results_mentions_lesson_zero(self, mock_store):
        """Lesson 0 exists in the course docs; `if lesson_number:` treats it as 'no filter'."""
        mock_store.search.return_value = make_results()
        out = CourseSearchTool(mock_store).execute("q", lesson_number=0)
        assert "lesson 0" in out

    def test_sources_tracked_with_links_and_deduplicated(self, mock_store):
        mock_store.get_lesson_link.return_value = "http://lesson"
        mock_store.search.return_value = make_results(
            ["a", "b", "c"],
            [{"course_title": "C", "lesson_number": 1}, {"course_title": "C", "lesson_number": 1},
             {"course_title": "C", "lesson_number": 2}],
        )
        tool = CourseSearchTool(mock_store)
        tool.execute("q")
        assert tool.last_sources == [
            {"text": "C - Lesson 1", "link": "http://lesson"},
            {"text": "C - Lesson 2", "link": "http://lesson"},
        ]

    def test_sources_replaced_on_next_search(self, mock_store):
        tool = CourseSearchTool(mock_store)
        mock_store.search.return_value = make_results(["a"], [{"course_title": "A", "lesson_number": 1}])
        tool.execute("q1")
        mock_store.search.return_value = make_results(["b"], [{"course_title": "B", "lesson_number": 2}])
        tool.execute("q2")
        assert [s["text"] for s in tool.last_sources] == ["B - Lesson 2"]

    def test_tool_definition_schema(self, mock_store):
        d = CourseSearchTool(mock_store).get_tool_definition()
        assert d["name"] == "search_course_content"
        assert d["input_schema"]["required"] == ["query"]
        assert set(d["input_schema"]["properties"]) == {"query", "course_name", "lesson_number"}


class TestToolManager:
    def test_dispatch_and_definitions(self, mock_store):
        mock_store.search.return_value = make_results(["x"], [{"course_title": "C", "lesson_number": 1}])
        tm = ToolManager()
        tm.register_tool(CourseSearchTool(mock_store))
        tm.register_tool(CourseOutlineTool(mock_store))
        assert {d["name"] for d in tm.get_tool_definitions()} == {"search_course_content", "get_course_outline"}
        assert "[C - Lesson 1]" in tm.execute_tool("search_course_content", query="q")

    def test_unknown_tool(self):
        assert ToolManager().execute_tool("nope") == "Tool 'nope' not found"

    def test_bad_kwargs_raise(self, mock_store):
        """A model-supplied argument the tool doesn't accept raises TypeError (=> HTTP 500 upstream)."""
        tm = ToolManager()
        tm.register_tool(CourseSearchTool(mock_store))
        try:
            tm.execute_tool("search_course_content", query="q", unexpected=1)
        except TypeError:
            return
        raise AssertionError("expected TypeError")

    def test_sources_reset(self, mock_store):
        mock_store.search.return_value = make_results(["x"], [{"course_title": "C", "lesson_number": 1}])
        tm = ToolManager()
        tool = CourseSearchTool(mock_store)
        tm.register_tool(tool)
        tm.execute_tool("search_course_content", query="q")
        assert tm.get_last_sources()
        tm.reset_sources()
        assert tm.get_last_sources() == []


class TestOutlineToolUnit:
    def test_not_found(self, mock_store):
        mock_store.get_course_outline.return_value = None
        assert CourseOutlineTool(mock_store).execute("zzz") == "No course found matching 'zzz'."

    def test_formats_outline(self, mock_store):
        mock_store.get_course_outline.return_value = {
            "title": "T", "course_link": "http://c",
            "lessons": [{"lesson_number": 0, "lesson_title": "Intro"}, {"lesson_number": 1, "lesson_title": "Next"}],
        }
        out = CourseOutlineTool(mock_store).execute("T")
        assert "Course: T" in out and "Course Link: http://c" in out
        assert "Lesson 0: Intro" in out and "Lesson 1: Next" in out


# ---------- integration tests (real Chroma + real embeddings + real docs) ----------

class TestExecuteIntegration:
    def test_content_query_returns_content(self, real_store):
        out = CourseSearchTool(real_store).execute("What is MCP?")
        assert out and not out.startswith(("No relevant content", "Search error", "No course found"))
        assert re.search(r"^\[.+\]", out)

    def test_partial_course_name_resolves(self, real_store):
        out = CourseSearchTool(real_store).execute("what are tools", course_name="MCP")
        assert not out.startswith(("No relevant content", "Search error", "No course found")), out
        assert "MCP" in out.split("\n")[0]

    def test_lesson_filter_only_returns_that_lesson(self, real_store):
        out = CourseSearchTool(real_store).execute("introduction", course_name="MCP", lesson_number=1)
        assert not out.startswith(("No relevant content", "Search error", "No course found")), out
        headers = re.findall(r"^\[(.+?)\]$", out, flags=re.M)
        assert headers and all(h.endswith("Lesson 1") for h in headers)

    def test_sources_have_lesson_links(self, real_store):
        tool = CourseSearchTool(real_store)
        tool.execute("What is MCP?", course_name="MCP")
        assert tool.last_sources
        assert all(s["link"] for s in tool.last_sources)

    def test_unknown_course_reports_error_string(self, real_store):
        """Semantic top-1 matching means *some* course always matches; this just must not raise."""
        out = CourseSearchTool(real_store).execute("anything", course_name="Underwater Basket Weaving 101")
        assert isinstance(out, str) and out

    def test_lesson_beyond_range_is_empty_not_error(self, real_store):
        out = CourseSearchTool(real_store).execute("x", course_name="MCP", lesson_number=999)
        assert out.startswith("No relevant content found")

    def test_outline_tool_lists_lessons(self, real_store):
        out = CourseOutlineTool(real_store).execute("MCP")
        assert out.startswith("Course: ") and "Lesson 1:" in out
