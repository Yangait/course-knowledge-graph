"""知识图谱问答系统的 FastAPI 接口。"""

from contextlib import asynccontextmanager
from pathlib import Path
import secrets
import re
from typing import Literal

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from openai import APIConnectionError, AuthenticationError, RateLimitError
from starlette.concurrency import run_in_threadpool

from neo4j_client import check_database, driver
from qa_system import answer_question
from graph_routes import router as graph_router, course_data
from unified_graph import graph_scope, node_record
from mindmap_context import build_mindmap_context
import chat_store


MAX_QUESTION_LENGTH = 500
MAX_EVIDENCE_ITEMS = 8
STATIC_DIR = Path(__file__).resolve().parent / "static"

RELATION_LABELS = {
    "APPLIED_IN": "应用于",
    "BELONGS_TO_COURSE": "属于课程",
    "BELONGS_TO_TOPIC": "属于主题",
    "CAUSES": "导致",
    "COMPARE_WITH": "对比",
    "CONFUSED_WITH": "容易混淆",
    "CONTAINS": "包含",
    "ENSURES": "保证",
    "EVALUATED_BY": "评价指标",
    "HAS_OPERATION": "具有操作",
    "HAS_PROPERTY": "具有性质",
    "ILLUSTRATED_BY": "示例说明",
    "IMPLEMENTED_BY": "实现方式",
    "IS_A": "属于类别",
    "OPTIMIZES": "优化",
    "PREREQUISITE_OF": "前置知识",
    "SOLVES": "解决",
    "USES": "使用或依赖",
    "SEMANTIC_LINK": "原始关联（未命名）",
    "ANNOTATES": "注释说明",
    "SUMMARIZES": "总结说明",
    "CONTAINS_AUXILIARY": "附属内容",
}


class AskRequest(BaseModel):
    answer_style: Literal["auto", "concise", "detailed"] = "auto"
    conversation_id: str | None = Field(default=None, min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    request_id: str | None = Field(default=None, min_length=16, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    course_id: str | None = Field(default=None, pattern=r"^C(?:0[1-9]|1[0-9]|2[0-6])$")
    node_id: str | None = Field(default=None, min_length=1, max_length=160)
    context_source: Literal["knowledge_graph", "mindmap"] = "knowledge_graph"
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
        description="用户提出的计算机课程知识问题",
        examples=["栈有哪些操作？"],
    )

    @field_validator("question", mode="before")
    @classmethod
    def strip_question(cls, value):
        if isinstance(value, str):
            value = value.strip()

            if not value:
                raise ValueError("问题不能为空")

        return value


class EvidenceItem(BaseModel):
    context_source: Literal["knowledge_graph", "mindmap"] | None = None
    node_id: str | None = None
    course_id: str | None = None
    direction: str | None = None
    core_concept: str | None = None
    related_concept: str | None = None
    relation: str | None = None
    reason: str | None = None
    course: str | None = None
    source: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class AskResponse(BaseModel):
    answer: str
    answer_mode: str
    model: str
    total_tokens: int = Field(ge=0)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ServiceHealth(BaseModel):
    status: Literal["running"]


class Neo4jHealth(BaseModel):
    status: Literal["connected", "disconnected"]
    nodes: int | None = None
    relationships: int | None = None
    cross_course_relationships: int | None = None
    courses: int | None = None
    dataset_id: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    service: ServiceHealth
    neo4j: Neo4jHealth


def validation_message(error: dict) -> str:
    error_type = error.get("type", "")

    if error_type == "missing":
        return "缺少 question 字段"

    if error_type == "string_type":
        return "question 必须是字符串"

    if error_type == "string_too_long":
        return f"问题长度不能超过 {MAX_QUESTION_LENGTH} 个字符"

    if error_type in {"string_too_short", "value_error"}:
        return "问题不能为空"

    if error_type == "json_invalid":
        return "请求体必须是合法 JSON"

    return "请求参数不正确"


def clean_text(value) -> str | None:
    if not isinstance(value, str):
        return None

    value = value.strip()
    return value or None


def clean_confidence(value) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None

    if 0 <= confidence <= 1:
        return round(confidence, 3)

    return None


def readable_source(source, book_page=None) -> str | None:
    source_text = clean_text(source)
    page_text = clean_text(book_page)

    if source_text and page_text:
        return f"{source_text}（页码：{page_text}）"

    if source_text:
        return source_text

    if page_text:
        return f"教材页码：{page_text}"

    return None


def build_evidence(graph_results: list[dict]) -> list[EvidenceItem]:
    evidence = []
    seen = set()

    def append_item(
        *,
        core_concept=None,
        related_concept=None,
        relation_type=None,
        reason=None,
        course=None,
        source=None,
        book_page=None,
        confidence=None,
        relation_label=None,
        node_id=None,
        course_id=None,
        direction=None,
        context_source=None,
    ):
        if len(evidence) >= MAX_EVIDENCE_ITEMS:
            return

        core_text = clean_text(core_concept)
        related_text = clean_text(related_concept)
        reason_text = clean_text(reason)
        source_text = readable_source(source, book_page)

        if not any((core_text, related_text, reason_text, source_text)):
            return

        relation_text = relation_label or RELATION_LABELS.get(
            relation_type,
            "相关知识",
        )
        signature = (
            core_text,
            related_text,
            relation_text,
            reason_text,
            source_text,
            node_id,
        )

        if signature in seen:
            return

        seen.add(signature)
        evidence.append(
            EvidenceItem(
                context_source=context_source,
                node_id=clean_text(node_id),
                course_id=clean_text(course_id),
                direction=clean_text(direction),
                core_concept=core_text,
                related_concept=related_text,
                relation=relation_text,
                reason=reason_text,
                course=clean_text(course),
                source=source_text,
                confidence=clean_confidence(confidence),
            )
        )

    for item in graph_results:
        if len(evidence) >= MAX_EVIDENCE_ITEMS:
            break

        if item.get("evidence_type") == "mindmap_context":
            append_item(core_concept=item.get("name"), reason=item.get("notes") or item.get("text") or item.get("path"),
                        relation_label="当前导图资料", course=item.get("course"), source=item.get("source"),
                        node_id=item.get("node_id"), course_id=item.get("course_id"), context_source="mindmap")
        elif item.get("evidence_type") == "entity_context":
            relationships = item.get("relationships") or []

            if relationships:
                for relationship in relationships:
                    append_item(
                        core_concept=item.get("name"),
                        related_concept=relationship.get("related_name"),
                        relation_type=relationship.get("relation_type"),
                        reason=(
                            relationship.get("reason")
                            or relationship.get("related_definition")
                        ),
                        course=item.get("course"),
                        source=(
                            relationship.get("source")
                            or item.get("source")
                        ),
                        book_page=item.get("book_page"),
                        confidence=relationship.get("confidence"),
                        node_id=item.get("display_node_id", item.get("node_id")) if item.get("course_id") else None,
                        course_id=item.get("course_id"),
                        direction=relationship.get("direction") if item.get("course_id") else None,
                        relation_label=relationship.get("relation_text"),
                    )
            else:
                append_item(
                    core_concept=item.get("name"),
                    relation_label="知识点说明",
                    reason=item.get("definition"),
                    course=item.get("course"),
                    source=item.get("source"),
                    book_page=item.get("book_page"),
                    node_id=item.get("display_node_id", item.get("node_id")) if item.get("course_id") else None,
                    course_id=item.get("course_id"),
                )

        else:
            append_item(
                core_concept=item.get("anchor_name"),
                related_concept=item.get("related_name"),
                relation_type=item.get("relation_type"),
                reason=(
                    item.get("reason")
                    or item.get("related_definition")
                ),
                course=item.get("related_course"),
                source=item.get("source"),
                book_page=item.get("book_page"),
                confidence=item.get("confidence"),
                node_id=item.get("display_node_id", item.get("anchor_node_id")) if item.get("course_id") else None,
                course_id=item.get("course_id"),
                direction=item.get("direction") if item.get("course_id") else None,
                relation_label=item.get("relation_text"),
            )

    return evidence


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        driver.close()


app = FastAPI(
    title="计算机专业知识图谱问答 API",
    description="为现有知识图谱问答流程提供 HTTP 接口。",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)
app.include_router(graph_router)


@app.middleware("http")
async def chat_identity(request: Request, call_next):
    token = request.cookies.get(chat_store.COOKIE_NAME, "")
    valid = bool(re.fullmatch(r"[A-Za-z0-9_-]{40,80}", token))
    if not valid:
        token = secrets.token_urlsafe(32)
    request.state.chat_owner = chat_store.owner_key(token)
    response = await call_next(request)
    if request.url.path.startswith("/api/conversations"):
        response.headers["Cache-Control"] = "no-store"
        if not valid:
            response.set_cookie(chat_store.COOKIE_NAME, token, max_age=31536000,
                                httponly=True, samesite="strict", secure=request.url.scheme == "https")
    return response


@app.exception_handler(chat_store.ChatNotFound)
async def missing_chat(_request, _error):
    return JSONResponse(status_code=404, content={"error": {"message": "该会话不存在或无法访问"}})


@app.exception_handler(chat_store.ChatBusy)
async def busy_chat(_request, _error):
    return JSONResponse(status_code=409, content={"error": {"message": "这个会话正在生成回答，请稍后重试"}})


class RenameConversation(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value):
        if not value.strip():
            raise ValueError("会话名称不能为空")
        return value.strip()


@app.get("/api/conversations")
def conversations(request: Request):
    return {"conversations": chat_store.list_chats(request.state.chat_owner)}


@app.post("/api/conversations")
def new_conversation(request: Request):
    return chat_store.create_chat(request.state.chat_owner)


@app.get("/api/conversations/{chat_id}")
def conversation(request: Request, chat_id: str):
    return chat_store.get_chat(request.state.chat_owner, chat_id)


@app.patch("/api/conversations/{chat_id}")
def rename_conversation(request: Request, chat_id: str, payload: RenameConversation):
    chat_store.change_chat(request.state.chat_owner, chat_id, title=payload.title)
    return {"status": "ok"}


@app.delete("/api/conversations/{chat_id}")
def delete_conversation(request: Request, chat_id: str):
    chat_store.change_chat(request.state.chat_owner, chat_id, delete=True)
    return {"status": "ok"}


@app.get("/graph", include_in_schema=False)
async def graph_page():
    return FileResponse(STATIC_DIR / "graph.html")


@app.get("/api/mindmap/node")
def mindmap_node(node_id: str):
    context = build_mindmap_context(node_id)
    return {"node": {"node_id": node_id, "name": context["name"], "path": context["path"],
                     "course": context["course"], "course_id": context["course_id"], "source": context["source"]}}


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request,
    error: RequestValidationError,
):
    details = [
        {
            "field": ".".join(
                str(part)
                for part in item.get("loc", [])[1:]
            ) or "request",
            "message": validation_message(item),
        }
        for item in error.errors()
    ]

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "请求参数校验失败",
                "details": details,
            }
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(
    _request: Request,
    _error: Exception,
):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "服务内部错误，请稍后重试",
            }
        },
    )


@app.get(
    "/api/health",
    response_model=HealthResponse,
    summary="检查服务和 Neo4j 状态",
)
async def health(response: Response) -> HealthResponse:
    try:
        database_result = await run_in_threadpool(check_database)

        return HealthResponse(
            status="ok",
            service=ServiceHealth(status="running"),
            neo4j=Neo4jHealth(
                status="connected",
                nodes=database_result["nodes"],
                relationships=database_result["relationships"],
                cross_course_relationships=database_result[
                    "cross_course_relationships"
                ],
                courses=database_result.get("courses"),
                dataset_id=database_result.get("dataset_id"),
            ),
        )
    except Exception:
        response.status_code = 503
        return HealthResponse(
            status="degraded",
            service=ServiceHealth(status="running"),
            neo4j=Neo4jHealth(status="disconnected"),
        )


@app.post(
    "/api/ask",
    response_model=AskResponse,
    response_model_exclude_none=True,
    summary="提交一个知识图谱问答问题",
)
async def ask(payload: AskRequest, request: Request) -> AskResponse | JSONResponse:
    token = None
    owner = request.state.chat_owner
    request_id = payload.request_id or secrets.token_urlsafe(24)
    try:
        history = []
        if payload.conversation_id:
            token, history, cached = await run_in_threadpool(
                chat_store.begin_turn, owner, payload.conversation_id, request_id)
            if cached is not None:
                return AskResponse(**cached)
        def run_scoped():
            if payload.course_id:
                course_data(payload.course_id)
            with graph_scope(payload.course_id):
                options = {"history": history} if history else {}
                if payload.answer_style != "auto":
                    options["answer_style"] = payload.answer_style
                if payload.context_source == "mindmap":
                    if not payload.node_id:
                        raise HTTPException(422, "请先选择导图知识点")
                    selected = build_mindmap_context(payload.node_id)
                    if payload.course_id and selected["course_id"] != payload.course_id:
                        raise HTTPException(404, "所选知识点不属于当前课程")
                    return answer_question(payload.question, mindmap_node_id=payload.node_id, **options)
                if payload.node_id:
                    n = node_record(payload.node_id)
                    if not n or not n.get("searchable"):
                        raise HTTPException(404, "所选知识点不存在或不属于当前课程")
                    return answer_question(payload.question, focused_node_id=payload.node_id, **options)
                return answer_question(payload.question, **options)
        result = await run_in_threadpool(run_scoped)

        response = AskResponse(
            answer=result["answer"],
            answer_mode=result["answer_mode"],
            model=result["model"],
            total_tokens=result["total_tokens"],
            evidence=build_evidence(
                result.get("graph_results") or []
            ),
        )
        if payload.conversation_id:
            await run_in_threadpool(chat_store.finish_turn, owner, payload.conversation_id, token,
                                   request_id, payload.question, response.model_dump(exclude_none=True),
                                   payload.course_id, payload.node_id, payload.context_source)
        return response
    except (chat_store.ChatNotFound, chat_store.ChatBusy):
        raise
    except HTTPException:
        raise
    except APIConnectionError:
        return JSONResponse(status_code=502, content={"error": {
            "code": "model_connection_failed", "message": "暂时无法连接大模型服务，知识导图仍可正常浏览。请检查模型接口网络连接。"}})
    except AuthenticationError:
        return JSONResponse(status_code=502, content={"error": {
            "code": "model_authentication_failed", "message": "大模型接口认证失败，请检查本机配置中的密钥和接口地址。"}})
    except RateLimitError:
        return JSONResponse(status_code=502, content={"error": {
            "code": "model_rate_limited", "message": "大模型接口额度或请求频率受限，请稍后重试或检查额度。"}})
    except Exception:
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "qa_service_unavailable",
                    "message": "问答服务暂时不可用，请稍后重试",
                }
            },
        )
    finally:
        if token:
            await run_in_threadpool(chat_store.release_turn, owner, payload.conversation_id, token)
