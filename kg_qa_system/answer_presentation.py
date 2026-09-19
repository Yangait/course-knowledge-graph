"""只规范答案开头的指代说明，不修改知识正文或存储的历史原文。"""
import re


_PRONOUN = r"(?:这(?:个|些)?|它(?:们)?|那(?:个|些)?|该内容)"
_MENTION = rf'(?:[“"‘\']{_PRONOUN}[^”"’\'\n]{{0,40}}[”"’\']|{_PRONOUN})'
_CONTEXT = r"(?:前文|上文|之前|刚才)(?:中)?(?:提到|讨论|介绍|说)(?:过)?的"
_INTRO = re.compile(
    rf"^\s*(?:你(?:说|提到|问)的\s*)?{_MENTION}\s*(?:通常|这里)?\s*"
    rf"(?:指代|指的是|是指)\s*{_CONTEXT}\s*"
    r"(?P<subject>[^，,。；;：:\n？！?!]{1,80})(?P<separator>[，,。；;：:])\s*"
)
_EXPLICIT_REFERENCE_QUESTION = re.compile(
    r"(?:指代|代词|指的是|是指什么|指什么|指哪个|指谁|什么意思|原文|逐字|翻译|润色|改写|分析.{0,8}(?:句子|语法))"
)


def present_answer(answer: str, question: str = "") -> str:
    """改写已明确说明对象的开场；用户询问指代本身时保持原样。"""
    if not answer or _EXPLICIT_REFERENCE_QUESTION.search(question):
        return answer
    match = _INTRO.match(answer)
    if not match:
        return answer
    subject = match["subject"].strip()
    rest = answer[match.end():]
    # 不将带疑问或不确定性的澄清改写成断言。
    if not rest or any(word in subject for word in ("可能", "还是", "或者", "或是", "不确定")):
        return answer
    if rest.startswith("其"):
        return subject + "的" + rest[1:]
    if rest.startswith("它"):
        return subject + rest[1:]
    if rest.startswith(("1.", "1、", "- ", "* ")):
        return subject + "：\n\n" + rest
    return subject + "。" + rest


def prepare_history(history):
    """只处理模型输入副本，避免旧开场措辞在后续回答中被模仿。"""
    result, question = [], ""
    for message in history or []:
        copied = dict(message)
        if copied.get("role") == "user":
            question = copied.get("content", "")
        elif copied.get("role") == "assistant":
            copied["content"] = present_answer(copied.get("content", ""), question)
        result.append(copied)
    return result
