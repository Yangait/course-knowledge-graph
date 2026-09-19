(() => {
    "use strict";

    const chatMessages = document.querySelector("#chatMessages");
    const chatForm = document.querySelector("#chatForm");
    const questionInput = document.querySelector("#questionInput");
    const sendButton = document.querySelector("#sendButton");
    const clearButton = document.querySelector("#clearButton");
    const composerStatus = document.querySelector("#composerStatus");
    const healthBadge = document.querySelector("#healthBadge");
    const healthText = document.querySelector("#healthText");

    let isSending = false;
    const answerStyle = document.querySelector("#answerStyle");
    try {
        const savedStyle = localStorage.getItem("kg-answer-style");
        if (["auto", "concise", "detailed"].includes(savedStyle)) answerStyle.value = savedStyle;
    } catch (_error) { /* 无法保存偏好时，当前页面仍可选择。 */ }
    answerStyle.addEventListener("change", () => {
        try { localStorage.setItem("kg-answer-style", answerStyle.value); }
        catch (_error) { /* 使用当前选择。 */ }
    });
    const focusedLabel = document.querySelector("#focusedLabel");
    const clearFocus = document.querySelector("#clearFocus");
    const params = new URLSearchParams(location.search);
    let focusedNode = params.get("node") || null;
    let contextSource = params.get("source") === "mindmap" ? "mindmap" : "knowledge_graph";
    const focusUrl = (id, source) => `/api/${source === "mindmap" ? "mindmap" : "graph"}/node?node_id=${encodeURIComponent(id)}`;
    function showFocus(node) {
        focusedLabel.textContent = `${contextSource === "mindmap" ? "当前导图" : "当前知识点"}：${node.name}`;
        focusedLabel.title = [node.course, node.path].filter(Boolean).join(" · ");
        focusedLabel.hidden = false;
        clearFocus.hidden = false;
    }
    let contextReady = false;
    let chatsReady = false;
    let activeChatId = null;
    let pendingRequest = null;
    const conversationList = document.querySelector("#conversationList");
    const historyStatus = document.querySelector("#historyStatus");
    const newChatButton = document.querySelector("#newChatButton");
    const historyToggle = document.querySelector("#historyToggle");
    const workspace = document.querySelector(".workspace");
    const appShell = document.querySelector(".app-shell");
    const chatSearch = document.querySelector("#chatSearch");
    const mobileLayout = window.matchMedia("(max-width: 760px)");

    function setSidebar(open) {
        if (mobileLayout.matches) workspace.classList.toggle("history-open", open);
        else workspace.classList.toggle("sidebar-collapsed", !open);
        historyToggle.setAttribute("aria-expanded", String(open));
        historyToggle.setAttribute("aria-label", open ? "收起侧栏" : "展开侧栏");
    }

    function filterChats() {
        const term = chatSearch.value.trim().toLocaleLowerCase();
        conversationList.querySelectorAll(".conversation-row").forEach(row => {
            row.hidden = !row.querySelector(".conversation-title").textContent.toLocaleLowerCase().includes(term);
        });
    }
    const conversationDialog = document.querySelector("#conversationDialog");
    const dialogName = document.querySelector("#dialogName");
    const dialogSubmit = document.querySelector("#dialogSubmit");
    const dialogError = document.querySelector("#dialogError");
    let dialogAction = null;

    function showConversationDialog(chat, action) {
        if (isSending) return;
        conversationList.querySelectorAll("details[open]").forEach(menu => { menu.open = false; });
        dialogAction = {chat, action};
        const deleting = action === "delete";
        document.querySelector("#dialogTitle").textContent = deleting ? "删除会话" : "重命名会话";
        document.querySelector("#dialogDescription").textContent = deleting ? `将删除“${chat.title}”及其全部聊天记录，此操作无法撤销。` : "给这段对话起一个容易找到的名字。";
        document.querySelector("#dialogNameLabel").hidden = deleting;
        dialogName.hidden = deleting;
        dialogName.required = !deleting;
        dialogName.value = chat.title;
        dialogError.textContent = "";
        dialogSubmit.textContent = deleting ? "删除" : "保存";
        conversationDialog.showModal();
        if (!deleting) dialogName.select();
    }

    function rememberChat(id) {
        activeChatId = id;
        try {
            if (id) localStorage.setItem("kg-active-chat", id);
            else localStorage.removeItem("kg-active-chat");
        } catch (_error) { /* 历史仍保存在服务端。 */ }
        history.replaceState(null, "", id ? `/?chat=${encodeURIComponent(id)}` : "/");
    }

    async function chatRequest(path, options = {}) {
        const response = await fetch(path, { ...options, headers: {"Content-Type": "application/json", ...(options.headers || {})} });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || payload.detail || "会话操作失败，请重试");
        return payload;
    }

    function showHistoryError(error) { historyStatus.textContent = error.message || "历史会话暂时无法加载，请刷新重试"; }

    async function refreshChats() {
        const data = await chatRequest("/api/conversations");
        conversationList.replaceChildren();
        for (const chat of data.conversations) {
            const row = createElement("div", "conversation-row");
            row.classList.toggle("is-active", chat.id === activeChatId);
            const open = createElement("button", "conversation-title", chat.title);
            open.type = "button";
            open.title = chat.title;
            if (chat.id === activeChatId) open.setAttribute("aria-current", "true");
            open.addEventListener("click", () => openChat(chat.id).catch(showHistoryError));
            row.append(open);
            const menu = createElement("details", "conversation-menu");
            const menuTrigger = createElement("summary", "", "···");
            menuTrigger.setAttribute("aria-label", `会话操作：${chat.title}`);
            menu.append(menuTrigger);
            menu.addEventListener("toggle", () => {
                if (menu.open) conversationList.querySelectorAll("details[open]").forEach(other => {
                    if (other !== menu) other.open = false;
                });
            });
            const actions = createElement("div", "conversation-actions");
            const rename = createElement("button", "", "改名");
            rename.type = "button";
            rename.setAttribute("aria-label", `重命名会话：${chat.title}`);
            rename.addEventListener("click", () => showConversationDialog(chat, "rename"));
            const remove = createElement("button", "", "删除");
            remove.type = "button";
            remove.setAttribute("aria-label", `删除会话：${chat.title}`);
            remove.addEventListener("click", () => showConversationDialog(chat, "delete"));
            actions.append(rename, remove);
            menu.append(actions);
            row.append(menu);
            conversationList.append(row);
        }
        historyStatus.textContent = data.conversations.length ? `${data.conversations.length} 个已保存会话` : "发送第一条消息，开始新对话。";
        filterChats();
    }

    function startNewChat() {
        if (isSending) return;
        rememberChat(null);
        pendingRequest = null;
        resetFocus();
        questionInput.value = "";
        chatMessages.replaceChildren();
        addWelcomeMessage();
        if (mobileLayout.matches) setSidebar(false);
        conversationList.querySelectorAll(".is-active").forEach(row => row.classList.remove("is-active"));
        questionInput.focus();
    }

    async function openChat(id) {
        if (isSending) return;
        setBusy(true);
        try {
            const chat = await chatRequest(`/api/conversations/${id}`);
            rememberChat(id);
            pendingRequest = null;
            questionInput.value = "";
            resetFocus();
            if (chat.node_id) {
                try {
                    contextSource = chat.context_source || "knowledge_graph";
                    const detail = await chatRequest(focusUrl(chat.node_id, contextSource));
                    focusedNode = chat.node_id;
                    showFocus(detail.node);
                } catch (_error) { resetFocus(); }
            }
            chatMessages.replaceChildren();
            if (!chat.messages.length) addWelcomeMessage();
            for (const message of chat.messages) {
                addMessage(message.role, message.content, false, message.result?.evidence || []);
            }
            if (mobileLayout.matches) setSidebar(false);
            await refreshChats();
        } finally { setBusy(false); }
    }

    async function loadChats() {
        try {
            await refreshChats();
            let saved = params.get("chat");
            if (!saved && !params.get("node") && !params.get("course") && !params.get("draft")) {
                try { saved = localStorage.getItem("kg-active-chat"); } catch (_error) { /* 无本地偏好。 */ }
            }
            if (saved) {
                try { await openChat(saved); }
                catch (error) { startNewChat(); showHistoryError(error); }
            }
            chatsReady = true;
            if(params.get("draft") && !params.get("chat") && !params.get("node")) {
                questionInput.value=params.get("draft").slice(0,500);
                resizeInput();
                questionInput.focus();
            }
        } catch (error) { showHistoryError(error); }
    }

    function resetFocus() {
        focusedNode = null;
        contextSource = "knowledge_graph";
        focusedLabel.hidden = true;
        clearFocus.hidden = true;
    }
    clearFocus.addEventListener("click", resetFocus);
    async function loadFocusedNode() {
        try {
            if (focusedNode) {
                const r = await fetch(focusUrl(focusedNode, contextSource));
                if (!r.ok) throw new Error("知识点无法加载，请重新选择");
                const n = (await r.json()).node;
                showFocus(n);
            }
        } catch (error) {
            resetFocus();
            composerStatus.textContent = error.message;
        } finally { contextReady = true; }
    }

    function scrollToBottom() {
        window.requestAnimationFrame(() => {
            chatMessages.scrollTo({
                top: chatMessages.scrollHeight,
                behavior: "smooth",
            });
        });
    }

    function createElement(tagName, className, text) {
        const element = document.createElement(tagName);
        element.className = className;

        if (text !== undefined) {
            element.textContent = text;
        }

        return element;
    }

    function renderMarkdown(container, markdown) {
        window.AnswerRenderer.render(container, markdown);
    }

    function appendEvidenceField(container, label, value) {
        if (value === null || value === undefined || value === "") {
            return;
        }

        const row = createElement("div", "evidence-field");
        row.append(
            createElement("dt", "evidence-label", label),
            createElement("dd", "evidence-value", String(value))
        );
        container.append(row);
    }

    function createEvidencePanel(evidence) {
        const details = createElement("details", "evidence-panel");
        const summary = createElement(
            "summary",
            "evidence-summary",
            evidence.some(item => item.context_source === "mindmap") ? `参考资料（${evidence.length}）` : `知识图谱依据（${evidence.length}）`
        );
        const list = createElement("div", "evidence-list");

        evidence.forEach((item, index) => {
            const card = createElement("article", "evidence-card");
            const title = createElement(
                "h4",
                "evidence-title",
                `依据 ${index + 1}`
            );
            const fields = createElement("dl", "evidence-fields");

            appendEvidenceField(fields, "核心知识点", item.core_concept);
            appendEvidenceField(fields, "相关知识点", item.related_concept);
            appendEvidenceField(fields, "关系", item.relation);
            appendEvidenceField(fields, "方向", {incoming:"相关知识点 → 核心知识点",outgoing:"核心知识点 → 相关知识点",both:"双向",none:"无方向"}[item.direction]);
            appendEvidenceField(fields, "原因", item.reason);
            appendEvidenceField(fields, "所属课程", item.course);
            appendEvidenceField(fields, "资料来源", item.source);

            if (Number.isFinite(item.confidence)) {
                appendEvidenceField(
                    fields,
                    "置信度",
                    `${Math.round(item.confidence * 100)}%`
                );
            }

            card.append(title, fields);
            if (item.node_id && item.course_id) {
                const link = createElement("a", "source-link", "在知识导图中查看 ↗");
                link.href = `/graph?course=${encodeURIComponent(item.course_id)}&node=${encodeURIComponent(item.node_id)}`;
                card.append(link);
            }
            list.append(card);
        });

        details.append(summary, list);
        return details;
    }

    function addMessage(
        role,
        text,
        isError = false,
        evidence = []
    ) {
        if (appShell.classList.contains("is-empty")) {
            chatMessages.replaceChildren();
            appShell.classList.remove("is-empty");
        }
        const message = createElement(
            "article",
            `message message--${role}${isError ? " message--error" : ""}`
        );
        message.setAttribute("aria-label", role === "user" ? "你" : "知识助手");
        const body = createElement("div", "message-body");
        const bubble = createElement("div", "message-bubble");

        if (role === "assistant" && !isError) {
            bubble.classList.add("markdown-content");
            renderMarkdown(bubble, text);
        } else {
            bubble.textContent = text;
        }

        body.append(bubble);

        const extras = createElement("div", "answer-extras");

        if (Array.isArray(evidence) && evidence.length > 0) {
            extras.append(createEvidencePanel(evidence));
        }

        if (extras.childElementCount > 0) {
            body.append(extras);
        }

        message.append(body);
        chatMessages.append(message);
        scrollToBottom();
        return message;
    }

    function addWelcomeMessage() {
        appShell.classList.add("is-empty");
        const welcome = createElement("div", "welcome-state");
        welcome.append(createElement("h2", "", "有什么可以帮你？"));
        chatMessages.replaceChildren(welcome);
    }

    function addThinkingMessage() {
        const message = createElement(
            "article",
            "message message--assistant"
        );
        message.setAttribute("aria-label", "知识助手");
        const body = createElement("div", "message-body");

        const bubble = createElement("div", "message-bubble");
        const thinking = createElement("span", "thinking");
        const label = createElement("span", "", "正在思考");
        const dots = createElement("span", "thinking-dots");

        for (let index = 0; index < 3; index += 1) {
            dots.append(document.createElement("span"));
        }

        thinking.append(label, dots);
        bubble.append(thinking);
        body.append(bubble);
        message.append(body);
        chatMessages.append(message);
        scrollToBottom();
        return message;
    }

    function setBusy(busy) {
        isSending = busy;
        sendButton.disabled = busy;
        questionInput.disabled = busy;
        clearButton.disabled = busy;
        newChatButton.disabled = busy;
        conversationList.querySelectorAll("button").forEach(button => { button.disabled = busy; });
        answerStyle.disabled = busy;
        clearFocus.disabled = busy;
        composerStatus.textContent = busy
            ? "正在思考，请稍候…"
            : "Enter 发送 · Shift+Enter 换行";
    }

    function resizeInput() {
        questionInput.style.height = "auto";
        questionInput.style.height = `${Math.min(questionInput.scrollHeight, 128)}px`;
    }

    function readableError(response, payload) {
        if (payload && payload.error && payload.error.message) {
            return payload.error.message;
        }

        if (response.status === 422) {
            return "问题格式不正确，请检查后重试。";
        }

        if (response.status === 502 || response.status === 503) {
            return "问答服务暂时不可用，请稍后重试。";
        }

        return "请求没有完成，请稍后重试。";
    }

    async function submitQuestion(rawQuestion) {
        const question = rawQuestion.trim();
        if (!contextReady || !chatsReady) { composerStatus.textContent = "正在加载会话，请稍候；加载失败时请刷新重试"; return; }

        if (!question || isSending) {
            if (!question) {
                composerStatus.textContent = "请输入问题后再发送";
                questionInput.focus();
            }
            return;
        }

        addMessage("user", question);
        questionInput.value = "";
        resizeInput();
        setBusy(true);
        const thinkingMessage = addThinkingMessage();

        try {
            if (!activeChatId) {
                const chat = await chatRequest("/api/conversations", {method:"POST"});
                rememberChat(chat.id);
            }
            // 普通聊天始终跨课程检索，不沿用旧会话的课程限制。
            const scope = null;
            if (!pendingRequest || pendingRequest.question !== question || pendingRequest.conversation_id !== activeChatId || pendingRequest.course_id !== scope || pendingRequest.node_id !== focusedNode || pendingRequest.context_source !== contextSource || pendingRequest.answer_style !== answerStyle.value) {
                pendingRequest = { question, answer_style:answerStyle.value, course_id:scope, node_id:focusedNode, context_source:contextSource, conversation_id:activeChatId, request_id:crypto.randomUUID() };
            }
            const response = await fetch("/api/ask", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json",
                },
                body: JSON.stringify(pendingRequest),
            });

            let payload = null;

            try {
                payload = await response.json();
            } catch (_error) {
                payload = null;
            }

            if (!response.ok) {
                throw new Error(readableError(response, payload));
            }

            if (!payload || typeof payload.answer !== "string") {
                throw new Error("服务返回内容不完整，请稍后重试。");
            }

            thinkingMessage.remove();
            addMessage("assistant", payload.answer, false, payload.evidence || []);
            pendingRequest = null;
            refreshChats().catch(showHistoryError);
        } catch (error) {
            thinkingMessage.remove();
            const message =
                error instanceof TypeError
                    ? "无法连接到问答服务，请确认服务已经启动。"
                    : error.message;
            addMessage("assistant", message, true);
            questionInput.value = question;
            resizeInput();
        } finally {
            setBusy(false);
            questionInput.focus();
        }
    }

    async function checkHealth() {
        try {
            const response = await fetch("/api/health", {
                headers: { Accept: "application/json" },
            });
            const payload = await response.json();
            const connected =
                response.ok &&
                payload.neo4j &&
                payload.neo4j.status === "connected";

            healthBadge.dataset.state = connected
                ? "connected"
                : "disconnected";
            healthText.textContent = connected
                ? `${payload.neo4j.courses || 26} 门课程已连接`
                : "知识图谱未连接";
        } catch (_error) {
            healthBadge.dataset.state = "disconnected";
            healthText.textContent = "服务连接失败";
        }
    }

    chatForm.addEventListener("submit", (event) => {
        event.preventDefault();
        submitQuestion(questionInput.value);
    });

    questionInput.addEventListener("keydown", (event) => {
        if (event.isComposing) {
            return;
        }

        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            chatForm.requestSubmit();
        }
    });

    questionInput.addEventListener("input", () => {
        resizeInput();
        composerStatus.textContent = questionInput.value.length > 400 ? `${questionInput.value.length}/500 字` : "Enter 发送 · Shift+Enter 换行";
    });

    clearButton.addEventListener("click", startNewChat);
    newChatButton.addEventListener("click", startNewChat);
    historyToggle.addEventListener("click", () => {
        const open = mobileLayout.matches ? workspace.classList.contains("history-open") : !workspace.classList.contains("sidebar-collapsed");
        setSidebar(!open);
    });
    document.querySelector("#sidebarClose").addEventListener("click", () => setSidebar(false));
    document.querySelector("#sidebarBackdrop").addEventListener("click", () => setSidebar(false));
    chatSearch.addEventListener("input", filterChats);
    mobileLayout.addEventListener("change", () => {
        workspace.classList.remove("history-open", "sidebar-collapsed");
        setSidebar(!mobileLayout.matches);
    });
    document.addEventListener("keydown", event => {
        if (event.key === "Escape" && workspace.classList.contains("history-open") && !conversationDialog.open) setSidebar(false);
    });
    setSidebar(!mobileLayout.matches);
    document.querySelector("#dialogCancel").addEventListener("click", () => conversationDialog.close());
    document.querySelector("#conversationDialogForm").addEventListener("submit", async event => {
        event.preventDefault();
        if (!dialogAction || dialogSubmit.disabled) return;
        const {chat, action} = dialogAction;
        const title = dialogName.value.trim();
        if (action === "rename" && !title) { dialogError.textContent = "请输入会话名称"; return; }
        dialogSubmit.disabled = true;
        try {
            await chatRequest(`/api/conversations/${chat.id}`, action === "delete" ? {method:"DELETE"} : {method:"PATCH", body:JSON.stringify({title})});
            if (action === "delete" && chat.id === activeChatId) startNewChat();
            conversationDialog.close();
            await refreshChats();
        } catch (error) { dialogError.textContent = error.message; }
        finally { dialogSubmit.disabled = false; }
    });

    resizeInput();
    checkHealth();
    loadFocusedNode().then(loadChats);
})();
