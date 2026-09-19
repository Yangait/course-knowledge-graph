/* Open /tests/rendering.html with python -m http.server --bind 127.0.0.1 8001.
   This page is outside the production /static mount and does not write chats. */
(() => {
    "use strict";
    const sample = String.raw`## B 树的结构

B 树是一种**多路平衡查找树**。对于 $M$ 阶 B 树，非根内部结点的孩子数至少为 $\lceil M/2 \rceil$。

### 关键规则

1. **结点有序**：关键字按升序排列。
   - 查询范围由 $key[i]$ 划分。
   - 所有叶子处在同一层。
2. **树高较低**：查找复杂度为 \(O(\log_M n)\)。

独立公式、上下标与分式：

\[
\lceil M/2 \rceil \leq c \leq M,\qquad
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
\]

| 对比项目 | B 树 | B+ 树 |
| --- | --- | --- |
| 记录位置 | 内部与叶子结点 | 叶子结点 |
| 范围查询 | 中序遍历 | 沿叶子链表遍历 |

> 结点容量越大，通常需要访问的磁盘页越少。

---

### 代码示例

` + '```python\ndef find_key(keys, target):\n    for i, key in enumerate(keys):\n        if key == target:\n            return i\n    return -1\n```' + String.raw`

行内代码保持原样：` + '`$x_i$`' + '。';

    const preview = document.querySelector("#preview");
    AnswerRenderer.render(preview, sample);
    let passed = 0;
    let failed = 0;
    function check(name, source, assertion) {
        const result = document.createElement("li");
        try {
            const target = document.createElement("div");
            AnswerRenderer.render(target, source);
            if (!assertion(target)) throw new Error("结果不符合预期");
            passed += 1;
            result.textContent = `通过：${name}`;
        } catch (error) {
            failed += 1;
            result.textContent = `失败：${name}（${error.message}）`;
        }
        document.querySelector("#test-results").append(result);
    }
    const hasMath = root => root.querySelectorAll(".katex").length === 1 && !root.querySelector(".math-fallback");
    check("截图中的 B 树向上取整公式", String.raw`至少 $\lceil M/2 \rceil$ 个孩子`, hasMath);
    check("中文紧邻行内公式", "复杂度为$O(n)$。", hasMath);
    check("括号式行内公式", String.raw`复杂度为 \(O(\log_M n)\)。`, hasMath);
    check("方括号独立公式", String.raw`\[\frac{a_1}{b^2}\]`, root => hasMath(root) && root.querySelector(".katex-display"));
    check("双美元多行公式", "$$\n\\sum_{i=1}^n i\n$$", root => hasMath(root) && root.querySelector(".katex-display"));
    check("同一段中的独立公式", "恒等式 $$x^2+y^2=z^2$$。", root => hasMath(root) && root.querySelector(".katex-display"));
    check("矩阵和换行", String.raw`\[\begin{pmatrix}a & b \\ c & d\end{pmatrix}\]`, hasMath);
    check("原生公式环境", String.raw`\begin{equation}a+b=c\end{equation}`, hasMath);
    check("公式中的下划线不被斜体拆开", "$a_i+b_j$", root => hasMath(root) && !root.querySelector("em"));
    check("粗体、斜体和删除线", "**重点**，*强调*，~~旧内容~~", root => root.querySelector("strong") && root.querySelector("em") && root.querySelector("s"));
    check("完整六级标题", "# 一\n\n###### 六", root => root.querySelector("h1") && root.querySelector("h6"));
    check("列表嵌套与连续编号", "3. 第三项\n   - 子项\n4. 第四项", root => root.querySelector('ol[start="3"] > li > ul') && root.querySelectorAll("ol > li").length === 2);
    check("列表项中的独立段落", "1. 首段\n\n   第二段\n\n2. 第二项", root => root.querySelectorAll("ol > li").length === 2 && root.querySelectorAll("li:first-child p").length === 2);
    check("表格内公式", "| 名称 | 复杂度 |\n| --- | --- |\n| 查找 | $O(n)$ |", root => root.querySelectorAll(".table-scroll td").length === 2 && hasMath(root));
    check("引用和分隔线", "> 引用\n\n---", root => root.querySelector("blockquote") && root.querySelector("hr"));
    check("代码不解析公式", '`$x_i$`\n\n```text\n\\(a+b\\)\n```', root => !root.querySelector(".katex") && root.querySelector("pre code").textContent === "\\(a+b\\)\n");
    check("代码高亮和复制按钮", '```python\nreturn 42\n```', root => root.querySelector(".hljs-keyword") && root.querySelector(".copy-code") && root.querySelector("pre code").textContent === "return 42\n");
    check("未知代码语言安全降级", '```unknown\n<script>alert(1)</script>\n```', root => root.querySelector("pre code").textContent.includes("<script>") && !root.querySelector("script"));
    check("转义符号和货币保留", String.raw`价格 \$20，预算 \$30；符号 \*。`, root => !root.querySelector(".katex") && root.textContent.includes("$20"));
    check("无闭合公式保留", "说明 $x_i 后续文字", root => root.textContent.includes("后续文字"));
    check("错误公式不丢失后文", String.raw`$\notARealCommand{x}$ 后续仍可阅读`, root => root.querySelector(".math-fallback") && root.textContent.includes("后续仍可阅读"));
    check("拒绝原始 HTML 执行", '<img src=x onerror="alert(1)"><script>alert(1)</script>', root => !root.querySelector("img,script") && root.textContent.includes("<img"));
    check("拒绝危险链接", "[危险](javascript:alert(1))", root => !root.querySelector("a[href]"));
    check("公式不允许 HTML 注入", String.raw`$\href{javascript:alert(1)}{x}$`, root => !root.querySelector("a[href]"));
    check("正常链接可访问", "[参考](https://example.com)", root => root.querySelector('a[rel="noopener noreferrer"]'));
    document.querySelector("#test-status").textContent = `${passed} 项通过，${failed} 项失败`;
    document.querySelector("#test-status").dataset.failed = String(failed);
})();
