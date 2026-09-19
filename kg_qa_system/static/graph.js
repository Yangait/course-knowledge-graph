(() => {
    "use strict";
    const $ = id => document.getElementById(id);
    const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
    const params = new URLSearchParams(location.search);
    const state = { courses: [], data: null, cid: null, index: new Map(), selected: null, epoch: 0, detailEpoch: 0 };
    const original = new window.OriginalMindmap($("mapViewport"), $("mapCanvas"), selectNode,
        scale => { const percent=scale*100; $("zoomLevel").textContent = `${percent<1?percent.toFixed(1):Math.round(percent)}%`; });
    const relationNames = {CONTAINS:"包含",CONTAINS_AUXILIARY:"附属内容",ANNOTATES:"注释",SUMMARIZES:"总结",SEMANTIC_LINK:"原始关联（未命名）",HAS_IMAGE:"配图",BELONGS_TO_COURSE:"所属课程",BELONGS_TO_TOPIC:"所属章节",PREREQUISITE_OF:"前置知识",HAS_PROPERTY:"性质",HAS_OPERATION:"操作",USES:"使用",COURSE_EDITION_OF:"对应课程资料",REFERS_TO_COURSE:"课程引用",HAS_COURSE:"课程入口",GROUP_MEMBER:"分组成员",HAS_STRUCTURE:"辅助结构"};
    const directions = {incoming:"←",outgoing:"→",both:"↔",none:"—"};
    async function get(url) { const r = await fetch(url); if (!r.ok) throw new Error(r.status === 404 ? "未找到对应内容" : "服务暂时不可用，请确认数据库已启动"); return r.json(); }
    function notice(text) { $("notice").textContent = text; }
    function allItems() {
        const d = state.data;
        return [...d.knowledge_nodes, ...d.floating_topics.roots, ...d.floating_topics.items, ...d.summary_blocks, ...d.summary_items, ...d.callouts, ...d.structural_anchors, ...d.boundary_groups, ...(d.original_map?.extra_nodes || [])];
    }
    function drawCourses() {
        const filter = $("courseFilter").value.trim().toLowerCase();
        $("courseList").replaceChildren();
        state.courses.filter(c => c.name.toLowerCase().includes(filter)).forEach(c => {
            const b = el("button", `course-item${c.course_id === state.cid ? " active" : ""}`);
            b.append(el("span", "", c.course_id.startsWith("M") ? "总览" : c.course_id), el("div", "", c.name));
            b.setAttribute("aria-current", String(c.course_id === state.cid));
            b.onclick = () => loadCourse(c.course_id);
            $("courseList").append(b);
        });
    }
    async function loadCourse(cid, target = null) {
        const epoch = ++state.epoch; ++state.detailEpoch;
        state.cid = cid; state.data = null; state.index.clear(); state.selected = null;
        original.clear();
        $("nodeSearch").value = "";
        $("mapCanvas").replaceChildren(); $("contentList").replaceChildren();
        $("mapViewport").hidden = false; $("contentList").hidden = true;
        document.querySelector(".map-controls").hidden = true;
        $("sourceNote").hidden = true;
        $("nodeDetail").replaceChildren(el("p", "", "点击导图中的知识点查看完整资料。"));
        notice("正在加载课程…"); drawCourses();
        try {
            const data = await get(`/api/graph/courses/${encodeURIComponent(cid)}`);
            if (epoch !== state.epoch) return;
            state.data = data; state.index = new Map(allItems().map(n => [n.id, n]));
            $("courseCode").textContent = `${cid} / COURSE MAP`;
            $("courseName").textContent = data.meta.course_name;
            const map = data.original_map;
            $("courseStats").textContent = map ? `${map.hotspots.length.toLocaleString()} 个可点击知识点` : "";
            $("sourceNote").textContent = map?.separate_edition
                ? "当前显示你提供的数据库精简原图。点击知识点查看资料，Ctrl + 滚轮缩放。"
                : "点击知识点查看资料，拖动浏览，Ctrl + 滚轮缩放。";
            $("sourceNote").hidden = !map;
            $("askCourse").href = "/";
            history.replaceState(null, "", `/graph?course=${cid}`);
            notice(""); render();
            if (target && map && !map.hotspots.some(h => h.id === target)) {
                original.focus(data.main_tree[0].id);
            }
            if (target) await selectNode(target); else if (data.original_map) await selectNode(data.main_tree[0].id);
        } catch (e) { if (epoch === state.epoch) notice(e.message); }
    }
    function resultCard(n, container) {
        const card = el("button", "result-card", (n.label || n.name || "").slice(0,180));
        const info = n.path || n.definition || n.text || ({floating_root:"浮动知识",summary_block:"总结",callout:"注释"}[n.entity_type]) || "点击查看详情";
        card.append(el("small", "", info.slice(0,220))); card.onclick = () => selectNode(n.id); container.append(card);
    }
    function render() {
        if (!state.data) return;
        const map = state.data.original_map;
        const term = $("nodeSearch").value.trim().toLowerCase();
        const isMap = !term;
        $("mapViewport").hidden = !isMap;
        document.querySelector(".map-controls").hidden = !isMap || !map;
        $("contentList").hidden = isMap;
        notice("");
        if (!map) {
            notice("这门课程的原图暂未就绪。");
            $("contentList").replaceChildren();
            return;
        }
        if (isMap) {
            if (original.data !== map) original.mount(map);
            original.select(state.selected);
            return;
        }
        const items = map.hotspots.map(h => state.index.get(h.id) || h);
        const matches = items.filter(n => [n.label,n.path,n.definition,n.text,n.note_text]
            .filter(Boolean).join(" ").toLowerCase().includes(term));
        const list = $("contentList"); list.replaceChildren();
        matches.slice(0,200).forEach(n => resultCard(n,list));
        if (!matches.length) list.append(el("p", "empty", "原图中没有匹配内容，试试其他关键词。"));
        if (matches.length > 200) notice(`找到 ${matches.length} 项，当前显示前 200 项，请缩小搜索范围。`);
    }
    async function selectNode(id, focus = true) {
        const cid = id.startsWith("LEGACY:") ? state.cid : id.startsWith("SVG:") ? id.split(":")[1] : id.split(":")[0];
        if (/^[CM]\d{2}$/.test(cid) && cid !== state.cid) { await loadCourse(cid,id); return; }
        const epoch = ++state.detailEpoch; state.selected = id;
        if (!state.data) return;
        $("nodeSearch").value = ""; render();
        const inMap = state.data.original_map?.hotspots.some(h => h.id === id);
        if (inMap && focus) requestAnimationFrame(() => {
            if (epoch === state.detailEpoch) original.focus(id);
        });
        if (state.data.original_map && !inMap) {
            notice("此知识点不在当前原图中，可在详情区查看资料。");
        }
        history.replaceState(null,"",`/graph?course=${state.cid}&node=${encodeURIComponent(id)}`);
        const panel = $("nodeDetail"); panel.replaceChildren(el("p","","正在读取知识点…"));
        try {
            const data = await get(`/api/graph/node?node_id=${encodeURIComponent(id)}`);
            if (epoch !== state.detailEpoch) return;
            const n = data.node, p = data.details;
            panel.replaceChildren(el("h2","",n.name),el("p","origin",`${n.course || "课程总览"} · ${n.origin === "legacy_csv" ? "旧版补充资料" : "课程导图资料"}`));
            if (n.path) panel.append(el("p","path",n.path));
            if (n.definition || n.text) panel.append(el("p","",n.definition || n.text));
            if (n.ask_source === "mindmap") { const a = el("a","primary","围绕这个知识点提问 ↗"); a.href = `/?source=mindmap&node=${encodeURIComponent(id)}`; panel.append(a); }
            else if (n.searchable) { const a = el("a","primary","围绕这个知识点提问 ↗"); a.href = `/?course=${n.course_id || ""}&node=${encodeURIComponent(id)}`; panel.append(a); }
            else if(data.question_prompt) {const a=el("a","primary","围绕这个知识点提问 ↗");a.href=`/?draft=${encodeURIComponent(data.question_prompt)}`;panel.append(a);}
            if (n.source) { panel.append(el("h3","","资料来源"),el("p","",n.source)); }
            if (p.book_page) panel.append(el("p","",`页码：${p.book_page}`));
            if (p.evidence_text) panel.append(el("h3","","原有证据说明"),el("p","",p.evidence_text));
            const shown=new Set(), imageIndex=new Map(data.images.map(i=>[i.id,i]));
            function appendImage(i) {
                if(!i || shown.has(i.id))return;
                shown.add(i.id); const a=el("a");a.href=i.url;a.target="_blank";a.rel="noopener";
                const img=el("img");img.src=i.url;img.alt=n.name;img.loading="lazy";a.append(img);panel.append(a);
            }
            function appendBlocks(blocks, includeText=true) {
                (blocks || []).forEach(b=>{if(b.type==="image")appendImage(imageIndex.get(b.image_id));else if(includeText && b.text)panel.append(el("p","note-text",b.text));});
            }
            appendBlocks(p.content_blocks,false);
            if(p.note_blocks?.length) {panel.append(el("h3","","详细说明"));appendBlocks(p.note_blocks);}
            const remaining=data.images.filter(i=>!shown.has(i.id));
            if(remaining.length)panel.append(el("h3","","知识点配图"));
            remaining.forEach(appendImage);
            if (data.relationships.length) panel.append(el("h3","","关联与上下文"));
            data.relationships.forEach(r => {
                const b = el("button","related");
                b.append(el("small","",`${directions[r.direction] || ""} ${r.relation_text || relationNames[r.relation_type] || "相关知识"}`),el("span","",r.related_name));
                b.onclick=async()=> { if(r.related_course_id && r.related_course_id!==state.cid) await loadCourse(r.related_course_id,r.related_node_id); else await selectNode(r.related_node_id); };panel.append(b);
            });
            if(data.relationships_truncated) panel.append(el("p","","此处展示前150条关联，可点击关联知识点继续查看。"));
        } catch(e) { if(epoch===state.detailEpoch) panel.replaceChildren(el("p","",e.message)); }
    }
    $("courseFilter").oninput=drawCourses; $("nodeSearch").oninput=render;
    $("zoomOut").onclick=()=>original.zoom(original.scale/1.25);
    $("zoomIn").onclick=()=>original.zoom(original.scale*1.25);
    $("fitMap").onclick=()=>original.fit();
    $("actualSize").onclick=()=>original.zoom(1);
    $("resetMap").onclick=()=>{if(state.data?.original_map)selectNode(state.data.main_tree[0].id);};
    get("/api/graph/courses").then(data=>{state.courses=[...data.courses,...(data.overviews||[])]; const cid=params.get("course"), valid=state.courses.some(c=>c.course_id===cid); return loadCourse(valid?cid:"C07",valid?params.get("node"):null);}).catch(e=>notice(e.message));
})();
