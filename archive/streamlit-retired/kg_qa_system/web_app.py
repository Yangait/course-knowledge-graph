"""计算机专业知识图谱问答系统的 Streamlit 页面。"""

from __future__ import annotations

from typing import Any

import streamlit as st

from neo4j_client import check_database
from qa_system import answer_question


MODE_LABELS = {
    "knowledge_graph": "知识图谱增强",
    "hybrid": "图谱与模型综合",
    "llm_only": "大模型直接回答",
}

EXAMPLE_QUESTIONS = [
    "栈有哪些操作？",
    "虚拟内存需要先学什么？",
    "数据库索引有什么作用？",
    "数据结构和操作系统有什么联系？",
]

PAGE_CSS = """
<style>
:root {
    --ink: #17212b;
    --muted: #637083;
    --teal: #0f766e;
    --teal-dark: #115e59;
    --paper: rgba(255, 255, 255, 0.86);
    --line: rgba(15, 118, 110, 0.14);
}

.stApp {
    background:
        radial-gradient(circle at 8% 0%, rgba(20, 184, 166, 0.12), transparent 28rem),
        radial-gradient(circle at 95% 12%, rgba(59, 130, 246, 0.10), transparent 24rem),
        #f5f8f7;
    color: var(--ink);
}

.block-container {
    max-width: 1120px;
    padding-top: 2rem;
    padding-bottom: 5rem;
}

.hero {
    padding: 1.75rem 1.9rem;
    margin-bottom: 1.15rem;
    border: 1px solid var(--line);
    border-radius: 22px;
    background: linear-gradient(120deg, rgba(255,255,255,.96), rgba(237,248,245,.88));
    box-shadow: 0 18px 50px rgba(31, 73, 68, 0.08);
}

.hero-kicker {
    margin-bottom: .55rem;
    color: var(--teal);
    font-size: .78rem;
    font-weight: 750;
    letter-spacing: .16em;
}

.hero h1 {
    margin: 0;
    color: var(--ink);
    font-size: clamp(2rem, 4vw, 3.15rem);
    line-height: 1.12;
    letter-spacing: -.035em;
}

.hero p {
    max-width: 760px;
    margin: .8rem 0 0;
    color: var(--muted);
    font-size: 1rem;
    line-height: 1.75;
}

.intro-card {
    min-height: 150px;
    padding: 1rem 1.05rem;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: var(--paper);
}

.intro-card strong {
    display: block;
    margin-bottom: .45rem;
    color: var(--teal-dark);
}

.intro-card span {
    color: var(--muted);
    line-height: 1.65;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #102a2a 0%, #142332 100%);
}

[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stMetricLabel"],
[data-testid="stSidebar"] [data-testid="stMetricValue"] {
    color: #f3f8f7 !important;
}

[data-testid="stMetric"] {
    padding: .75rem .85rem;
    border: 1px solid rgba(255,255,255,.12);
    border-radius: 14px;
    background: rgba(255,255,255,.07);
}

[data-testid="stChatMessage"] {
    margin: .45rem 0;
    border: 1px solid var(--line);
    border-radius: 16px;
    background: rgba(255, 255, 255, 0.82);
    box-shadow: 0 8px 24px rgba(31, 73, 68, 0.045);
}

[data-testid="stChatInput"] {
    border-color: rgba(15,118,110,.24);
}

.meta-line {
    margin-top: .8rem;
    color: var(--muted);
    font-size: .83rem;
}

.status-ok {
    color: #7ee7c4;
    font-weight: 700;
}

.status-error {
    color: #fecaca;
    font-weight: 700;
}

@media (max-width: 700px) {
    .block-container { padding-top: 1rem; }
    .hero { padding: 1.25rem; border-radius: 16px; }
    .intro-card { min-height: auto; }
}
</style>
"""


def mode_label(mode: str | None) -> str:
    """将内部回答模式转换为用户可读名称。"""

    if not mode:
        return "未知"

    return MODE_LABELS.get(mode, mode)


def safe_database_status() -> dict[str, Any]:
    """读取数据库状态，并把连接异常转换为页面可展示结果。"""

    try:
        result = check_database()
        return {
            "ok": True,
            **result,
        }
    except Exception as error:
        return {
            "ok": False,
            "error": f"{type(error).__name__}: {error}",
        }


def build_assistant_message(result: dict[str, Any]) -> dict[str, Any]:
    """把问答系统结果整理为页面会话消息。"""

    return {
        "role": "assistant",
        "content": result.get("answer") or "本次没有生成回答。",
        "meta": {
            "answer_mode": result.get("answer_mode"),
            "model": result.get("model"),
            "total_tokens": result.get("total_tokens", 0),
            "graph_result_count": len(result.get("graph_results") or []),
        },
        "parsed_result": result.get("parsed_result") or {},
        "linked_result": result.get("linked_result"),
        "graph_results": result.get("graph_results") or [],
    }


def summarize_graph_results(results: list[dict]) -> list[dict[str, Any]]:
    """压缩图谱结果，便于在页面详情中展示。"""

    summaries = []

    for item in results[:8]:
        if item.get("evidence_type") == "entity_context":
            summaries.append(
                {
                    "核心实体": item.get("name"),
                    "关系": "实体上下文",
                    "相关实体": f"{len(item.get('relationships') or [])} 条相邻知识",
                    "所属课程": item.get("course"),
                }
            )
        else:
            summaries.append(
                {
                    "核心实体": item.get("anchor_name"),
                    "关系": item.get("relation_type"),
                    "相关实体": item.get("related_name"),
                    "所属课程": item.get("related_course"),
                }
            )

    return summaries


def render_assistant_details(message: dict[str, Any]):
    meta = message.get("meta") or {}

    st.markdown(
        (
            '<div class="meta-line">'
            f"{mode_label(meta.get('answer_mode'))} · "
            f"{meta.get('model') or '未知模型'} · "
            f"{meta.get('total_tokens', 0)} Token · "
            f"{meta.get('graph_result_count', 0)} 条图谱结果"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    with st.expander("查看解析与检索详情"):
        parsed_result = message.get("parsed_result") or {}

        if parsed_result:
            st.caption("问题解析")
            st.json(parsed_result)

        summaries = summarize_graph_results(
            message.get("graph_results") or []
        )

        if summaries:
            st.caption("图谱证据摘要")
            st.dataframe(
                summaries,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("本次没有检索到知识图谱证据。")


def render_message(message: dict[str, Any]):
    role = message.get("role", "assistant")

    with st.chat_message(role):
        st.markdown(message.get("content") or "")

        if role == "assistant":
            if message.get("error"):
                with st.expander("查看错误详情"):
                    st.code(message["error"])
            else:
                render_assistant_details(message)


def render_sidebar():
    with st.sidebar:
        st.title("系统状态")
        st.caption("知识图谱与模型服务概览")

        if "database_status" not in st.session_state:
            st.session_state.database_status = safe_database_status()

        if st.button("刷新数据库状态", use_container_width=True):
            st.session_state.database_status = safe_database_status()

        status = st.session_state.database_status

        if status.get("ok"):
            st.markdown(
                '<div class="status-ok">● Neo4j 已连接</div>',
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns(2)
            col1.metric("节点", f"{status.get('nodes', 0):,}")
            col2.metric("关系", f"{status.get('relationships', 0):,}")
            st.metric(
                "跨课程关系",
                f"{status.get('cross_course_relationships', 0):,}",
            )
        else:
            st.markdown(
                '<div class="status-error">● Neo4j 未连接</div>',
                unsafe_allow_html=True,
            )
            st.caption(status.get("error", "数据库连接失败"))

        st.divider()
        st.subheader("示例问题")

        for index, example in enumerate(EXAMPLE_QUESTIONS):
            if st.button(
                example,
                key=f"example_{index}",
                use_container_width=True,
            ):
                st.session_state.pending_question = example

        st.divider()

        if st.button("清空对话", use_container_width=True):
            st.session_state.messages = []
            st.rerun()

        st.caption("当前为本地演示版，回答会调用已配置的千问接口。")


def render_empty_state():
    st.subheader("你可以这样使用")
    columns = st.columns(3)
    cards = [
        (
            "查概念",
            "询问定义、性质、操作或应用场景，系统会优先引用课程图谱。",
        ),
        (
            "找联系",
            "探索前置知识、章节归属和跨课程关系，理解知识之间的结构。",
        ),
        (
            "做比较",
            "比较容易混淆的概念，结合图谱证据获得更有针对性的解释。",
        ),
    ]

    for column, (title, description) in zip(columns, cards):
        column.markdown(
            (
                '<div class="intro-card">'
                f"<strong>{title}</strong>"
                f"<span>{description}</span>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )


def main():
    st.set_page_config(
        page_title="计算机专业知识图谱问答系统",
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(PAGE_CSS, unsafe_allow_html=True)

    if "messages" not in st.session_state:
        st.session_state.messages = []

    render_sidebar()

    st.markdown(
        """
        <section class="hero">
            <div class="hero-kicker">COURSE KNOWLEDGE GRAPH</div>
            <h1>计算机专业知识图谱问答系统</h1>
            <p>
                面向九门计算机专业课程，从 2701 个知识节点和 10630 条关系中
                检索证据，再结合大模型生成清晰、可追溯的回答。
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )

    if not st.session_state.messages:
        render_empty_state()

    for message in st.session_state.messages:
        render_message(message)

    typed_question = st.chat_input(
        "输入课程知识问题，例如：虚拟内存需要先学什么？",
        max_chars=500,
    )
    question = (
        typed_question
        or st.session_state.pop("pending_question", None)
    )

    if not question:
        return

    question = question.strip()

    if not question:
        st.warning("请输入有效问题。")
        return

    user_message = {
        "role": "user",
        "content": question,
    }
    st.session_state.messages.append(user_message)
    render_message(user_message)

    try:
        with st.status(
            "正在解析问题并检索知识图谱…",
            expanded=True,
        ) as status:
            st.write("识别核心实体和关系意图")
            st.write("检索 Neo4j 图谱证据")
            result = answer_question(question)
            status.update(
                label="回答生成完成",
                state="complete",
                expanded=False,
            )

        assistant_message = build_assistant_message(result)

    except Exception as error:
        assistant_message = {
            "role": "assistant",
            "content": (
                "本次回答没有完成。请检查 Neo4j、网络和模型接口配置后重试。"
            ),
            "error": f"{type(error).__name__}: {error}",
        }

    st.session_state.messages.append(assistant_message)
    render_message(assistant_message)


if __name__ == "__main__":
    main()
