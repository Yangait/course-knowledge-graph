from neo4j_client import (
    count_relations_for_node,
    find_entity_candidates
)


def link_entity(
    entity_name: str,
    relation_type: str | None = None,
    direction: str | None = None
) -> dict:
    """根据名称和关系上下文链接Neo4j节点。"""

    candidates = find_entity_candidates(entity_name)

    if not candidates:
        return {
            "mention": entity_name,
            "status": "not_found",
            "resolution_method": None,
            "selected": None,
            "candidates": []
        }

    # 用关系上下文消除同名实体歧义
    for candidate in candidates:
        if relation_type and direction:
            relation_count = count_relations_for_node(
                node_id=candidate["node_id"],
                relation_type=relation_type,
                direction=direction
            )
        else:
            relation_count = 0

        candidate["relation_match_count"] = relation_count

    # 先匹配实体名称，再用关系和重要性区分同名实体。
    candidates.sort(
        key=lambda candidate: (
            candidate["match_score"],
            candidate["relation_match_count"],
            candidate.get("importance") or 0
        ),
        reverse=True
    )

    best_candidate = candidates[0]

    best_rank = (
        best_candidate["match_score"],
        best_candidate["relation_match_count"],
        best_candidate.get("importance") or 0
    )

    equally_good_candidates = [
        candidate
        for candidate in candidates
        if (
            candidate["match_score"],
            candidate["relation_match_count"],
            candidate.get("importance") or 0
        ) == best_rank
    ]

    # 最高排名并列时保留歧义，避免错误链接
    if len(equally_good_candidates) > 1:
        return {
            "mention": entity_name,
            "status": "ambiguous",
            "resolution_method": None,
            "selected": None,
            "candidates": equally_good_candidates
        }

    resolution_method = (
        "relation_context"
        if best_candidate["relation_match_count"] > 0
        else "name_match"
    )

    return {
        "mention": entity_name,
        "status": "linked",
        "resolution_method": resolution_method,
        "selected": best_candidate,
        "candidates": candidates
    }
