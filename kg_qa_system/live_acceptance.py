"""连接真实 Neo4j 和千问服务的端到端验收脚本。"""

import json
import sys

from neo4j_client import check_database, driver
from qa_system import answer_question


def main() -> int:
    question = " ".join(sys.argv[1:]).strip() or "栈有哪些操作？"

    try:
        database_result = check_database()
        answer_result = answer_question(question)

        summary = {
            "question": question,
            "database": database_result,
            "status": answer_result["status"],
            "answer_mode": answer_result["answer_mode"],
            "model": answer_result["model"],
            "graph_result_count": len(answer_result["graph_results"]),
            "total_tokens": answer_result["total_tokens"],
            "answer": answer_result["answer"],
        }

        if database_result["nodes"] <= 0:
            raise RuntimeError("Neo4j 中没有知识图谱节点")

        if answer_result["status"] != "success":
            raise RuntimeError("问答流程没有返回 success")

        if not answer_result["answer"].strip():
            raise RuntimeError("问答流程返回了空答案")

        print("端到端验收：PASS")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    except Exception as error:
        print("端到端验收：FAIL")
        print(type(error).__name__, str(error))
        return 1

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
