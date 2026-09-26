"""API endpoint tests: request validation, response shape, session handling, error mapping."""
import pytest

pytestmark = pytest.mark.api


class TestQueryEndpoint:
    def test_returns_answer_sources_and_session(self, client, sample_sources):
        r = client.post("/api/query", json={"query": "What is MCP?"})
        assert r.status_code == 200
        assert r.json() == {"answer": "the answer", "sources": sample_sources, "session_id": "session-1"}

    def test_creates_session_when_missing(self, client, mock_rag):
        client.post("/api/query", json={"query": "hi"})
        mock_rag.session_manager.create_session.assert_called_once()
        mock_rag.query.assert_called_once_with("hi", "session-1")

    def test_reuses_provided_session(self, client, mock_rag):
        r = client.post("/api/query", json={"query": "hi", "session_id": "existing"})
        assert r.json()["session_id"] == "existing"
        mock_rag.session_manager.create_session.assert_not_called()
        mock_rag.query.assert_called_once_with("hi", "existing")

    def test_empty_sources(self, client, mock_rag):
        mock_rag.query.return_value = ("general answer", [])
        assert client.post("/api/query", json={"query": "2+2"}).json()["sources"] == []

    def test_source_link_may_be_null(self, client):
        sources = client.post("/api/query", json={"query": "q"}).json()["sources"]
        assert sources[1]["link"] is None

    @pytest.mark.parametrize("body", [{}, {"session_id": "s"}, {"query": 123}, {"query": None}])
    def test_invalid_body_returns_422(self, client, mock_rag, body):
        assert client.post("/api/query", json=body).status_code == 422
        mock_rag.query.assert_not_called()

    def test_non_json_body_returns_422(self, client):
        assert client.post("/api/query", content="not json").status_code == 422

    def test_rag_failure_returns_500_with_detail(self, client, mock_rag):
        mock_rag.query.side_effect = RuntimeError("boom")
        r = client.post("/api/query", json={"query": "q"})
        assert r.status_code == 500
        assert r.json()["detail"] == "boom"

    def test_get_not_allowed(self, client):
        assert client.get("/api/query").status_code == 405


class TestCoursesEndpoint:
    def test_returns_stats(self, client, sample_courses):
        r = client.get("/api/courses")
        assert r.status_code == 200
        assert r.json() == sample_courses

    def test_no_courses(self, client, mock_rag):
        mock_rag.get_course_analytics.return_value = {"total_courses": 0, "course_titles": []}
        assert client.get("/api/courses").json() == {"total_courses": 0, "course_titles": []}

    def test_failure_returns_500(self, client, mock_rag):
        mock_rag.get_course_analytics.side_effect = RuntimeError("chroma down")
        r = client.get("/api/courses")
        assert r.status_code == 500
        assert r.json()["detail"] == "chroma down"

    def test_post_not_allowed(self, client):
        assert client.post("/api/courses").status_code == 405


class TestSessionEndpoint:
    def test_delete_session(self, client, mock_rag):
        r = client.delete("/api/session/abc")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}
        mock_rag.session_manager.delete_session.assert_called_once_with("abc")


class TestRootEndpoint:
    def test_root_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_unknown_route_404(self, client):
        assert client.get("/api/nope").status_code == 404
