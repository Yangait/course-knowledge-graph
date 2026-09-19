"""用已配置模型验证上下文语义解析；不修改图谱或用户会话。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kg_qa_system"))
from conversation_context import resolve_request


def dialogue(question, answer):
    return [dict(role="user", content=question), dict(role="assistant", content=answer)]


index_history = dialogue("数据库索引有什么作用？", "数据库索引可以加速查询、优化排序，唯一索引可以约束重复值。")
polluted_history = index_history + dialogue("这有什么用", "“这”指代前文讨论的数据库索引，其作用是加速查询。") + dialogue(
    "他是干什么的", "由于您提到的他指代不明确，无法确定是哪位人物。如果您是指数据库索引，它可以加速查询；如果是某位专家请补充姓名。")
comparison = dialogue("比较一下栈和队列", "1. 栈：后进先出。\n2. 队列：先进先出。")
cases = [
    ("typo_he", "他是干什么的", polluted_history, "resolved", ["索引"]),
    ("typo_she", "她有什么用，只写两条", index_history, "resolved", ["索引", "两条"]),
    ("colloquial", "这玩意有啥用", index_history, "resolved", ["索引"]),
    ("omitted_subject", "怎么用，给个SQL例子", index_history, "resolved", ["索引", "SQL"]),
    ("former", "前者怎么实现", comparison, "resolved", ["栈"]),
    ("latter", "后者怎么实现", comparison, "resolved", ["队列"]),
    ("expand_second", "展开第二点，举一个例子", comparison, "resolved", ["队列"]),
    ("new_topic", "换个话题，解释事务的ACID", index_history, "standalone", ["事务", "ACID"]),
    ("correct_topic", "不说索引了，讲虚拟内存", index_history, "standalone", ["虚拟内存"]),
    ("real_person", "他是干什么的", dialogue("图灵是谁？", "图灵是一位数学家和计算机科学先驱。"), "resolved", ["图灵"]),
    ("ambiguous", "它怎么实现", comparison, "needs_clarification", []),
]


def main():
    results = []
    for name, question, history, expected_status, terms in cases:
        result = resolve_request(question, history)
        passed = result["status"] == expected_status and all(term in result["question"] for term in terms)
        record = dict(case=name, original=question, expected_status=expected_status, expected_terms=terms,
                      passed=passed, **result)
        results.append(record)
        print(json.dumps(record, ensure_ascii=True), flush=True)
    output = ROOT / "unified_kg" / "conversation_context_acceptance.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(row["passed"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
