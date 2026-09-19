from answer_generator import generate_answer
from entity_linker import link_entity
from neo4j_client import (
    driver,
    query_entity_context,
    query_related_nodes
)
from question_parser import parse_question
from unified_graph import find_entity_candidates
from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
from conversation_context import resolve_request
from llm_client import fast_model
from mindmap_context import build_mindmap_context, graph_supplements


def diverse_candidates(candidates, limit=4):
    """在查询预算内保留不同课程、不同来源，候选节点仍各自独立。"""
    chosen, remaining, groups = [], [], set()
    for candidate in candidates:
        group = (candidate.get("course_id"), candidate.get("origin"))
        if group not in groups:
            chosen.append(candidate)
            groups.add(group)
        else:
            remaining.append(candidate)
    return (chosen + remaining)[:limit]


def source_companions(selected, candidates):
    """只补充同课程、同名但来源不同的资料，不建立节点等价关系。"""
    if not all(selected.get(key) for key in ("name", "course_id", "origin")):
        return []
    return diverse_candidates([
        c for c in candidates
        if c.get("node_id") != selected["node_id"]
        and c.get("name") == selected["name"]
        and c.get("course_id") == selected["course_id"]
        and c.get("origin") and c["origin"] != selected["origin"]
    ], limit=2)


def answer_question(question: str, focused_node_id: str | None = None, history: list[dict] | None = None, answer_style: str = "auto", mindmap_node_id: str | None = None) -> dict:
    primary = build_mindmap_context(mindmap_node_id, question) if mindmap_node_id else None
    focus = {key: primary[key] for key in ("name", "course", "path")} if primary else None
    context = resolve_request(question, history, focus=focus) if focus else resolve_request(question, history)
    if context["status"] == "needs_clarification":
        return dict(status="success", answer=context["clarification"], answer_mode="llm_only",
                    model=fast_model, total_tokens=context["total_tokens"],
                    parsed_result={"context_resolution": context["status"]}, linked_result=None, graph_results=[])
    resolved_question = context["question"]
    if primary:
        # Use the restored request for branch relevance, while keeping the actual selected source.
        primary = build_mindmap_context(mindmap_node_id, resolved_question)
        try:
            parsed = parse_question(resolved_question)
        except ValueError:
            parsed = {"complexity": "simple", "relation_type": None, "direction": None}
        evidence = [primary, *graph_supplements(primary, parsed)]
        result = generate_answer(resolved_question, parsed, evidence, history=history, answer_style=answer_style)
        parsed.update(original_question=question, resolved_question=resolved_question, context_resolution=context["status"])
        return dict(result, status="success", parsed_result=parsed,
                    linked_result={"status": "mindmap", "node_id": mindmap_node_id}, graph_results=evidence,
                    total_tokens=result["total_tokens"] + context["total_tokens"])
    try:
        result = _answer_question(resolved_question, focused_node_id, history, answer_style)
    except (Neo4jError, ServiceUnavailable, SessionExpired):
        # 图谱暂不可用时，仍按问题和历史对话回答；模型连接异常由接口单独处理。
        parsed = {"complexity": "simple", "relation_type": None, "direction": None}
        answer = generate_answer(user_question=resolved_question, parsed_result=parsed,
                                 graph_results=[], answer_style=answer_style,
                                 **({"history": history} if history else {}))
        result = {**answer, "status": "success", "parsed_result": parsed, "linked_result": None, "graph_results": []}
    result["parsed_result"].update(original_question=question, resolved_question=resolved_question,
                                  context_resolution=context["status"])
    result["total_tokens"] += context["total_tokens"]
    return result


def _answer_question(question: str, focused_node_id: str | None = None, history: list[dict] | None = None, answer_style: str = "auto") -> dict:
    """完成一次支持多实体的知识图谱增强问答。"""

    try:
        # 解析器和回答模型使用同一个已经还原的请求，不再分别判断原始代词。
        parsed_result = parse_question(question)
    except ValueError:
        parsed_result = dict(anchor_entity=None, entities=[], relation_type=None, direction=None, complexity="simple")

    anchor_entity = parsed_result.get("anchor_entity")
    entities = parsed_result.get("entities") or []
    relation_type = parsed_result.get("relation_type")
    direction = parsed_result.get("direction")

    graph_results = []
    linked_result = None
    context_node_ids = set()
    relation_node_ids = set()
    retrieval_notes = []

    def add_entity_context(
        node_id: str,
        limit: int
    ):
        """查询并添加实体上下文。"""

        if node_id in context_node_ids:
            return

        context = query_entity_context(
            node_id=node_id,
            limit=limit
        )

        graph_results.extend(context)
        context_node_ids.add(node_id)

    def add_anchor(candidate):
        node_id = candidate["node_id"]
        if node_id in relation_node_ids:
            return
        relation_node_ids.add(node_id)
        relations = []
        if relation_type and direction:
            relations = query_related_nodes(
                node_id=node_id, relation_type=relation_type, direction=direction)
            graph_results.extend(relations)
        if not relations:
            # 学习建议可参考“使用/依赖”，但绝不改写为先修关系。
            if relation_type == "PREREQUISITE_OF" and direction == "incoming":
                dependencies = query_related_nodes(
                    node_id=node_id, relation_type="USES", direction="outgoing")
                graph_results.extend(dict(row, evidence_role="dependency_context") for row in dependencies)
                retrieval_notes.append({
                    "实体": candidate.get("name"), "课程": candidate.get("course"),
                    "来源": candidate.get("origin"),
                    "说明": "本次未检索到该节点的明确先修关系；使用关系仅支持学习建议，不等于先修关系。",
                })
            add_entity_context(node_id, limit=10)

    if focused_node_id:
        context = query_entity_context(focused_node_id, limit=20)
        if not context:
            raise ValueError("所选知识点不存在或不属于当前课程")
        selected = context[0]
        # 聚焦节点也执行精确关系检索，避免邻接列表截断遗漏关系。
        context_node_ids.add(focused_node_id)
        add_anchor(selected)
        graph_results.extend(context)
        for companion in source_companions(selected, find_entity_candidates(selected["name"])):
            add_anchor(companion)
        linked_result = {"status": "focused", "node_id": focused_node_id}

    # 明确关系时优先精确查询，否则检索实体上下文
    elif anchor_entity:
        if relation_type and direction:
            linked_result = link_entity(
                entity_name=anchor_entity,
                relation_type=relation_type,
                direction=direction
            )
        else:
            linked_result = link_entity(
                entity_name=anchor_entity
            )

        if linked_result["status"] == "linked":
            selected_node = linked_result["selected"]

            add_anchor(selected_node)
            for companion in source_companions(selected_node, linked_result["candidates"]):
                add_anchor(companion)

        elif linked_result["status"] == "ambiguous":
            retrieval_notes.append({"说明": "实体存在歧义，以下候选资料须按课程和来源分别说明。"})
            for candidate in diverse_candidates(linked_result["candidates"]):
                add_anchor(candidate)

    # 补充检索问题中的其他实体
    additional_entities = []
    seen_entity_names = set()

    if anchor_entity:
        seen_entity_names.add(
            anchor_entity.strip().lower()
        )

    for entity_name in entities:
        if not isinstance(entity_name, str):
            continue

        clean_name = entity_name.strip()

        if not clean_name:
            continue

        normalized_name = clean_name.lower()

        if normalized_name in seen_entity_names:
            continue

        seen_entity_names.add(normalized_name)
        additional_entities.append(clean_name)

    # 限制补充实体数量，控制查询量和Token消耗
    for entity_name in ([] if focused_node_id else additional_entities[:3]):
        secondary_link = link_entity(
            entity_name=entity_name
        )

        if secondary_link["status"] == "linked":
            selected_node = secondary_link["selected"]

            add_entity_context(
                node_id=selected_node["node_id"],
                limit=6
            )

        elif secondary_link["status"] == "ambiguous":
            for candidate in diverse_candidates(secondary_link["candidates"]):
                add_entity_context(
                    node_id=candidate["node_id"],
                    limit=4
                )

    parsed_result["retrieval_notes"] = retrieval_notes

    answer_result = generate_answer(
        user_question=question,
        parsed_result=parsed_result,
        graph_results=graph_results,
        answer_style=answer_style,
        **({"history": history} if history else {})
    )

    return {
        "status": "success",
        "answer": answer_result["answer"],
        "answer_mode": answer_result["answer_mode"],
        "model": answer_result["model"],
        "total_tokens": answer_result["total_tokens"],
        "parsed_result": parsed_result,
        "linked_result": linked_result,
        "graph_results": graph_results
    }


def main():
    """运行命令行连续问答。"""

    print("=" * 50)
    print("计算机专业知识图谱问答系统")
    print("输入“退出”即可结束程序")
    print("=" * 50)

    try:
        while True:
            question = input("\n你：").strip()

            if question.lower() in {
                "退出",
                "结束",
                "exit",
                "quit"
            }:
                print("\n系统：再见！")
                break

            if not question:
                print("\n系统：请输入一个问题。")
                continue

            try:
                result = answer_question(question)

                print("\n系统：")
                print(result["answer"])

                if result["status"] == "success":
                    mode_names = {
                    "knowledge_graph": "知识图谱增强",
                    "hybrid": "知识图谱与大模型综合回答",
                    "llm_only": "大模型直接回答"
                }

                    mode_name = mode_names.get(
                        result["answer_mode"],
                        result["answer_mode"]
                    )

                    print(
                        f'\n[模式：{mode_name}，'
                        f'模型：{result["model"]}，'
                        f'Token：{result["total_tokens"]}]'
                    )

            except Exception as error:
                print("\n系统运行时出现错误：")
                print(type(error).__name__, str(error))

    except KeyboardInterrupt:
        print("\n\n系统：程序已结束。")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
