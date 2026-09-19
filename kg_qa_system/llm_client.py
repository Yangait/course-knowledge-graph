import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

api_key = os.getenv("DASHSCOPE_API_KEY")
base_url = os.getenv("DASHSCOPE_BASE_URL")
fast_model = os.getenv("FAST_MODEL", "qwen3.5-flash")
strong_model = os.getenv("STRONG_MODEL", "qwen3.7-plus")

if not api_key:
    raise RuntimeError("没有读取到DASHSCOPE_API_KEY")

if not base_url:
    raise RuntimeError("没有读取到DASHSCOPE_BASE_URL")

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    timeout=60,
    max_retries=1
)


def ask_llm(question: str, complex_mode: bool = False) -> dict:
    """按问题复杂度选择千问模型。"""

    if complex_mode:
        model = strong_model
        extra_body = {
            "enable_thinking": True,
            "thinking_budget": 1024
        }
        max_tokens = 1000
    else:
        model = fast_model
        extra_body = {
            "enable_thinking": False
        }
        max_tokens = 500

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是一名严谨的计算机专业课程助教。"
            },
            {
                "role": "user",
                "content": question
            }
        ],
        temperature=0.2,
        max_tokens=max_tokens,
        extra_body=extra_body
    )

    details = response.usage.completion_tokens_details
    reasoning_tokens = getattr(details, "reasoning_tokens", 0) or 0

    return {
        "answer": response.choices[0].message.content,
        "model": model,
        "prompt_tokens": response.usage.prompt_tokens,
        "completion_tokens": response.usage.completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": response.usage.total_tokens
    }
