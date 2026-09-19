/* One renderer for both new answers and saved conversations. */
(() => {
    "use strict";

    const md = window.markdownit({
        html: false,
        breaks: false,
        linkify: true,
        typographer: false,
        highlight(source, language) {
            if (language && window.hljs.getLanguage(language)) {
                try { return window.hljs.highlight(source, {language, ignoreIllegals: true}).value; }
                catch (_error) { /* Unknown or invalid code stays readable. */ }
            }
            return md.utils.escapeHtml(source);
        },
    });

    // Parse math before Markdown consumes backslashes, underscores and asterisks.
    // Code spans/fences retain their literal contents.
    const delimiters = ["dollars", "brackets", "beg_end"];
    md.use(window.texmath, {engine: window.katex, delimiters});
    function mathHTML(source, display) {
        try {
            return window.katex.renderToString(source, {
                displayMode: display,
                output: "htmlAndMathml",
                throwOnError: true,
                trust: false,
                strict: "ignore",
                maxExpand: 1000,
                maxSize: 20,
                macros: {},
            });
        } catch (_error) {
            // A malformed formula must never make the rest of an answer disappear.
            return `<code class="math-fallback">${md.utils.escapeHtml(source)}</code>`;
        }
    }
    const mathRules = window.texmath.mergeDelimiters(delimiters);
    for (const rule of [...mathRules.inline, ...mathRules.block]) {
        md.renderer.rules[rule.name] = (tokens, index) => {
            const token = tokens[index];
            const display = token.block || Boolean(rule.displayMode);
            const tag = token.block ? "div" : "span";
            return `<${tag} class="math-expression">${mathHTML(token.content, display)}</${tag}>`;
        };
    }
    const defaultFence = md.renderer.rules.fence;
    md.renderer.rules.fence = (tokens, index, options, env, renderer) => {
        if (tokens[index].info.trim() === "math") {
            return `<div class="math-expression">${mathHTML(tokens[index].content, true)}</div>`;
        }
        return defaultFence(tokens, index, options, env, renderer);
    };

    function decorateCode(container) {
        container.querySelectorAll("pre > code").forEach(code => {
            const pre = code.parentElement;
            const block = document.createElement("div");
            block.className = "code-block";
            const toolbar = document.createElement("div");
            toolbar.className = "code-toolbar";
            const language = document.createElement("span");
            language.textContent = Array.from(code.classList).find(name => name.startsWith("language-"))?.slice(9) || "代码";
            const copy = document.createElement("button");
            copy.type = "button";
            copy.className = "copy-code";
            copy.textContent = "复制代码";
            copy.setAttribute("aria-label", "复制代码");
            copy.addEventListener("click", async () => {
                try {
                    await navigator.clipboard.writeText(code.textContent);
                    copy.textContent = "已复制";
                } catch (_error) {
                    copy.textContent = "请选中代码复制";
                }
                window.setTimeout(() => { copy.textContent = "复制代码"; }, 2000);
            });
            toolbar.append(language, copy);
            pre.replaceWith(block);
            block.append(toolbar, pre);
        });
    }

    function render(container, source) {
        const html = md.render(String(source || "").replace(/\r\n?/g, "\n"));
        // Never insert model-provided HTML directly. Keep MathML for accessibility.
        const fragment = window.DOMPurify.sanitize(html, {
            RETURN_DOM_FRAGMENT: true,
            USE_PROFILES: {html: true, svg: true, mathMl: true},
            FORBID_TAGS: ["style", "form", "input", "textarea", "button"],
        });
        container.replaceChildren(fragment);
        container.querySelectorAll("a").forEach(link => {
            link.target = "_blank";
            link.rel = "noopener noreferrer";
        });
        container.querySelectorAll("table").forEach(table => {
            const wrapper = document.createElement("div");
            wrapper.className = "table-scroll";
            wrapper.tabIndex = 0;
            wrapper.setAttribute("role", "region");
            wrapper.setAttribute("aria-label", "表格，可横向滚动");
            table.replaceWith(wrapper);
            wrapper.append(table);
        });
        decorateCode(container);
    }

    window.AnswerRenderer = Object.freeze({render});
})();
