"""问题解析人工调试入口。"""

import json

from question_parser import parse_question


def main():
    question = input("请输入问题：").strip()

    if not question:
        print("问题不能为空。")
        return

    try:
        result = parse_question(question)

        print("\n解析结果：")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )
    except ValueError as error:
        print("\n问题解析失败：", error)


if __name__ == "__main__":
    main()
