"""大模型客户端人工调试入口。"""

from llm_client import ask_llm


def main():
    question = input("请输入问题：").strip()

    if not question:
        print("问题不能为空。")
        return

    mode = input("是否使用复杂模式？输入 y 或 n：")
    complex_mode = mode.lower() == "y"

    result = ask_llm(
        question=question,
        complex_mode=complex_mode,
    )

    print("\n使用模型：", result["model"])
    print("模型回答：")
    print(result["answer"])

    print("\nToken统计：")
    print("输入：", result["prompt_tokens"])
    print("输出：", result["completion_tokens"])
    print("推理：", result["reasoning_tokens"])
    print("总计：", result["total_tokens"])


if __name__ == "__main__":
    main()
