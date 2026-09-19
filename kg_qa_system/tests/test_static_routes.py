"""静态聊天页面和路由的离线测试。"""

import os
import unittest


os.environ.setdefault("DASHSCOPE_API_KEY", "unit-test-key")
os.environ.setdefault(
    "DASHSCOPE_BASE_URL",
    "https://example.invalid/v1",
)
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "unit-test-password")

from fastapi.testclient import TestClient  # noqa: E402

from api import app  # noqa: E402


class StaticRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_root_returns_chat_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("计算机专业知识图谱问答系统", response.text)
        self.assertIn("/static/style.css", response.text)
        self.assertIn("/static/app.js", response.text)

    def test_css_is_served(self):
        response = self.client.get("/static/style.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers["content-type"])
        self.assertIn(".chat-messages", response.text)

    def test_javascript_is_served_and_calls_same_origin_api(self):
        response = self.client.get("/static/app.js")

        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers["content-type"])
        self.assertIn('fetch("/api/ask"', response.text)
        self.assertIn("textContent", response.text)
        self.assertNotIn("innerHTML", response.text)

    def test_javascript_uses_safe_markdown_dom_renderer(self):
        script = self.client.get("/static/app.js").text
        renderer = self.client.get("/static/answer-renderer.js").text
        self.assertIn("function renderMarkdown", script)
        self.assertIn("window.AnswerRenderer.render", script)
        self.assertIn("window.DOMPurify.sanitize", renderer)
        self.assertIn("RETURN_DOM_FRAGMENT: true", renderer)
        self.assertIn("html: false", renderer)
        self.assertIn("trust: false", renderer)
        self.assertNotIn("insertAdjacentHTML", renderer)

    def test_renderer_dependencies_are_served_locally(self):
        import re

        page = self.client.get("/").text
        for path in re.findall(r'(?:src|href)="(/static/vendor/[^\"]+)"', page):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        katex_css = self.client.get("/static/vendor/katex/dist/katex.min.css").text
        for font in set(re.findall(r'url\((fonts/[^)]+)\)', katex_css)):
            with self.subTest(font=font):
                self.assertEqual(self.client.get("/static/vendor/katex/dist/" + font).status_code, 200)

    def test_javascript_contains_collapsible_evidence_panel(self):
        script = self.client.get("/static/app.js").text

        self.assertIn("function createEvidencePanel", script)
        self.assertIn('createElement("details", "evidence-panel")', script)
        self.assertIn("知识图谱依据（", script)
        self.assertIn("payload.evidence || []", script)

    def test_css_supports_long_markdown_and_evidence_on_mobile(self):
        css = self.client.get("/static/style.css").text

        self.assertIn(".markdown-content pre", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn(".evidence-panel", css)
        self.assertIn("@media (max-width: 760px)", css)

    def test_javascript_contains_required_chat_interactions(self):
        script = self.client.get("/static/app.js").text

        self.assertIn('event.key === "Enter"', script)
        self.assertIn("!event.shiftKey", script)
        self.assertIn("event.isComposing", script)
        self.assertIn("sendButton.disabled = busy", script)
        self.assertIn("正在思考", script)
        self.assertIn("chatMessages.replaceChildren()", script)

    def test_docs_and_original_api_routes_remain_available(self):
        docs = self.client.get("/docs")
        schema = self.client.get("/openapi.json").json()

        self.assertEqual(docs.status_code, 200)
        self.assertIn("/api/health", schema["paths"])
        self.assertIn("/api/ask", schema["paths"])

    def test_frontend_contains_no_credentials(self):
        combined = "\n".join(
            self.client.get(path).text
            for path in (
                "/",
                "/static/style.css",
                "/static/app.js",
            )
        )

        for forbidden in (
            "DASHSCOPE_API_KEY",
            "NEO4J_PASSWORD",
            "unit-test-password",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
