/**
 * Chat logic: sending messages, streaming SSE, rendering message bubbles.
 */
import {
    state, dom,
    escapeHtml, renderMarkdown, safeHighlight, scrollToBottom, showToast,
    updateSendBtnState,
} from "./state.js?v=7";
import { loadFiles } from "./files.js?v=7";
import { loadConversations } from "./conversations.js?v=7";
import { loadUtilities } from "./utilities.js?v=7";

// ========== Copy Helpers ==========

const COPY_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>`;
const CHECK_ICON = `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;

function copyText(text) {
    if (navigator.clipboard?.writeText) {
        return navigator.clipboard.writeText(text);
    }
    // Fallback for non-HTTPS contexts
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;opacity:0;top:0;left:0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    return Promise.resolve();
}

function flashCopied(btn) {
    btn.innerHTML = CHECK_ICON;
    btn.classList.add("copied");
    setTimeout(() => {
        btn.innerHTML = COPY_ICON;
        btn.classList.remove("copied");
    }, 1500);
}

function getPlainText(rawContent) {
    // Return readable text: join all segment contents, separated by blank lines
    return parseSegments(rawContent)
        .map(s => s.content.trim())
        .filter(Boolean)
        .join("\n\n");
}

// ========== Cancel ==========

export async function cancelGeneration() {
    if (!state.isStreaming) return;
    try {
        const url = state.currentConvId
            ? `/api/chat/cancel?conversation_id=${encodeURIComponent(state.currentConvId)}`
            : "/api/chat/cancel";
        await fetch(url, { method: "POST" });
    } catch (_) { /* best effort */ }
    state.isStreaming = false;
    updateSendBtnState();
    showToast("已停止生成", "info");
}

// ========== Send Message ==========

export async function sendMessage() {
    const text = dom.messageInput.value.trim();
    if (!text && state.attachedFiles.length === 0 && state.referencedFiles.length === 0) return;
    if (state.isStreaming) return;

    dom.welcomeScreen.style.display = "none";

    // Build display
    let displayText = text;
    const allFileNames = [
        ...state.attachedFiles.map(f => f.name),
        ...state.referencedFiles,
    ];
    if (allFileNames.length > 0) {
        displayText += `\n\n📎 ${allFileNames.join(", ")}`;
    }

    addMessage("user", displayText);

    // Upload new files
    const fileRefs = [...state.referencedFiles];
    if (state.attachedFiles.length > 0) {
        try {
            const formData = new FormData();
            for (const file of state.attachedFiles) {
                formData.append("files", file);
            }
            const res = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await res.json();
            fileRefs.push(...(data.uploaded || []));
        } catch (e) {
            showToast("文件上传失败: " + e.message, "error");
        }
    }

    // Clear input
    dom.messageInput.value = "";
    dom.messageInput.style.height = "auto";
    dom.sendBtn.disabled = true;
    state.attachedFiles = [];
    state.referencedFiles = [];
    dom.attachedFilesEl.innerHTML = "";

    // Stream response
    state.isStreaming = true;
    updateSendBtnState();
    const aiMsgEl = addMessage("assistant", "", true);

    let fullContent = "";
    let currentTurnText = "";

    try {
        const response = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: text,
                file_refs: fileRefs,
                conversation_id: state.currentConvId,
            }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let streamDone = false;

        const handleEvent = (event) => {
            switch (event.type) {
                case "conversation_id":
                    state.currentConvId = event.content;
                    break;
                case "token":
                    currentTurnText += event.content;
                    fullContent += event.content;
                    renderStreamingMessage(aiMsgEl, fullContent, true);
                    break;
                case "message_end": {
                    const beforeTurn = fullContent.slice(0, fullContent.length - currentTurnText.length);
                    fullContent = beforeTurn + event.content;
                    currentTurnText = "";
                    renderStreamingMessage(aiMsgEl, fullContent, true);
                    break;
                }
                case "observation":
                    fullContent += "\n" + event.content;
                    currentTurnText = "";
                    renderStreamingMessage(aiMsgEl, fullContent, true);
                    break;
                case "solution":
                    if (!fullContent.trim()) {
                        fullContent = event.content;
                        renderStreamingMessage(aiMsgEl, fullContent, true);
                    }
                    break;
                case "error":
                    fullContent += `\n\n❌ 错误: ${event.content}`;
                    renderStreamingMessage(aiMsgEl, fullContent, true);
                    break;
                case "done":
                    streamDone = true;
                    break;
                case "maintenance_pending":
                    showMaintenancePopup();
                    break;
            }
        };

        while (!streamDone) {
            const { done, value } = await reader.read();
            if (done) {
                if (buffer.trim()) {
                    for (const line of buffer.split("\n")) {
                        if (!line.startsWith("data: ")) continue;
                        const j = line.slice(6).trim();
                        if (!j) continue;
                        try { handleEvent(JSON.parse(j)); } catch (_) { /* skip */ }
                    }
                }
                break;
            }

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
                if (!line.startsWith("data: ")) continue;
                const j = line.slice(6).trim();
                if (!j) continue;
                try { handleEvent(JSON.parse(j)); } catch (_) { /* skip */ }
                if (streamDone) break;
            }
        }

        renderStreamingMessage(aiMsgEl, fullContent || "(无响应)", false);

    } catch (e) {
        renderStreamingMessage(aiMsgEl, `❌ 请求失败: ${e.message}`, false);
    } finally {
        state.isStreaming = false;
        // Final render with streaming=false to ensure dots are removed
        renderStreamingMessage(aiMsgEl, fullContent || "(无响应)", false);
        updateSendBtnState();
        loadFiles();
        loadConversations();
        loadUtilities();
    }
}

// ========== Message Rendering ==========

export function addMessage(role, content, isStreaming = false) {
    const msgEl = document.createElement("div");
    msgEl.className = `message message-${role}`;

    if (role === "user") {
        msgEl.innerHTML = `
            <div class="message-content">
                <div class="message-text-wrap">${escapeHtml(content).replace(/\n/g, "<br>")}</div>
                <div class="message-actions">
                    <button class="copy-btn" title="复制消息">${COPY_ICON}</button>
                </div>
            </div>
        `;
        const btn = msgEl.querySelector(".copy-btn");
        btn.addEventListener("click", () => {
            copyText(content).then(() => flashCopied(btn)).catch(() => {});
        });
    } else {
        msgEl.innerHTML = `
            <div class="message-header">
                <div class="message-avatar">🧬</div>
                <span class="message-role">CAi</span>
            </div>
            <div class="message-body">
                ${isStreaming ? '<div class="streaming-indicator"><span class="streaming-dot"></span><span class="streaming-dot"></span><span class="streaming-dot"></span></div>' : ""}
            </div>
            <div class="message-actions">
                <button class="copy-btn" title="复制消息">${COPY_ICON}</button>
            </div>
        `;
        const btn = msgEl.querySelector(".copy-btn");
        btn.addEventListener("click", () => {
            const raw = msgEl.dataset.content || "";
            const text = raw ? getPlainText(raw) : msgEl.querySelector(".message-body")?.innerText || "";
            copyText(text).then(() => flashCopied(btn)).catch(() => {});
        });
    }

    dom.messagesEl.appendChild(msgEl);
    scrollToBottom();
    return msgEl;
}

// Track code execution start times per message element
const _codeTimers = new WeakMap();

export function renderStreamingMessage(msgEl, fullContent, isStreaming = false) {
    const body = msgEl.querySelector(".message-body");
    const segments = parseSegments(fullContent);
    let html = "";

    // Manage execution timers
    if (!_codeTimers.has(msgEl)) {
        _codeTimers.set(msgEl, { starts: [], ends: [] });
    }
    const timers = _codeTimers.get(msgEl);

    // Count code segments to track timing
    let codeIdx = 0;

    segments.forEach((seg, i) => {
        const isLast = i === segments.length - 1;
        const inProgress = isStreaming && isLast;
        const statusOK = " ✓";
        const statusRun = " ⏳";

        if (seg.type === "plan") {
            // Plan blocks are rendered as a distinct, always-visible section
            // with markdown rendering for the checklist items.
            const planHtml = buildPlanBlock(seg.content, inProgress);
            html += planHtml;
        } else if (seg.type === "text") {
            if (seg.content.trim()) {
                html += `<div class="solution-content">${renderMarkdown(seg.content)}</div>`;
            }
        } else if (seg.type === "code") {
            // Record start time for this code block
            if (!timers.starts[codeIdx]) {
                timers.starts[codeIdx] = Date.now();
            }

            let timeStr = "";
            if (inProgress) {
                // Show live elapsed time
                const elapsed = ((Date.now() - timers.starts[codeIdx]) / 1000).toFixed(1);
                timeStr = ` <span class="exec-time">(${elapsed}s)</span>`;
            } else if (timers.ends[codeIdx]) {
                // Show final elapsed time
                const elapsed = ((timers.ends[codeIdx] - timers.starts[codeIdx]) / 1000).toFixed(1);
                timeStr = ` <span class="exec-time">(${elapsed}s)</span>`;
            }

            const status = inProgress ? `${statusRun} 执行中...${timeStr}` : `${statusOK}${timeStr}`;
            // Prefer the lang attribute carried on the segment; fall back to
            // heuristic detection only for legacy messages without `lang`.
            const lang = seg.lang || detectCodeLanguage(seg.content);
            const highlighted = highlightCode(seg.content, lang);
            html += buildCollapsible(
                `💻 执行代码${status}`,
                `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>`,
                "code",
                inProgress,
                true,
            );
            codeIdx++;
        } else if (seg.type === "observation") {
            // Mark the previous code block as finished
            const prevCodeIdx = codeIdx - 1;
            if (prevCodeIdx >= 0 && !timers.ends[prevCodeIdx]) {
                timers.ends[prevCodeIdx] = Date.now();
            }

            // Extract image paths and render them as <img> tags
            const obsContent = seg.content;
            const imageLines = [];
            const textLines = [];
            for (const line of obsContent.split("\n")) {
                const imgMatch = line.match(/\[Image saved\]:\s*(.+)/);
                if (imgMatch) {
                    const filename = imgMatch[1].trim().split(/[/\\]/).pop();
                    imageLines.push(
                        `<div class="plot-preview"><img src="/api/files/${encodeURIComponent(filename)}?inline=1" alt="${escapeHtml(filename)}"></div>`
                    );
                } else {
                    textLines.push(line);
                }
            }
            let obsHtml = `<pre><code>${escapeHtml(textLines.join("\n"))}</code></pre>`;
            if (imageLines.length) {
                obsHtml += imageLines.join("");
            }
            html += buildCollapsible(
                `📊 执行结果${statusOK}`,
                obsHtml,
                "observation",
                inProgress,
                true,
            );
        }
    });

    // If streaming ended, mark any unfinished code blocks
    if (!isStreaming) {
        for (let i = 0; i < timers.starts.length; i++) {
            if (timers.starts[i] && !timers.ends[i]) {
                timers.ends[i] = Date.now();
            }
        }
    }

    if (isStreaming) {
        html += '<div class="streaming-indicator"><span class="streaming-dot"></span><span class="streaming-dot"></span><span class="streaming-dot"></span></div>';
    }

    if (!html.trim()) {
        html = isStreaming
            ? '<div class="streaming-indicator"><span class="streaming-dot"></span><span class="streaming-dot"></span><span class="streaming-dot"></span></div>'
            : '<div class="solution-content"><em>(无响应)</em></div>';
    }

    body.innerHTML = html;
    // Apply syntax highlighting to any code blocks that weren't pre-highlighted
    body.querySelectorAll("pre code[class*='language-']:not(.hljs)").forEach((block) => safeHighlight(block));
    // Store raw content so the copy button can extract clean plain text
    if (!isStreaming) {
        msgEl.dataset.content = fullContent;
    }
    scrollToBottom();
}

// ========== Parsing ==========
//
// Tag syntax (mirrors CAi/CAi_agent/agent_tags.py):
//   <execute lang="python">code</execute>
//   <observation>output</observation>
//   <done/>
//
// `lang` is optional (defaults to python). For backward compat, a
// `#!BASH` / `#!R` shebang as the first non-blank line of an
// attribute-less <execute> block is also accepted.

const _ATTR_RE = /(\w+)="([^"]*)"/g;

function _parseAttrs(attrStr) {
    const out = {};
    if (!attrStr) return out;
    let m;
    _ATTR_RE.lastIndex = 0;
    while ((m = _ATTR_RE.exec(attrStr)) !== null) {
        out[m[1]] = m[2];
    }
    return out;
}

function _detectLang(code, attrLang) {
    if (attrLang) {
        const normalized = attrLang.trim().toLowerCase();
        if (["python", "bash", "r", "plan"].includes(normalized)) return normalized;
        return "python";
    }
    const stripped = code.replace(/^[\s\n]+/, "");
    if (/^#!BASH\b/i.test(stripped)) return "bash";
    if (/^#!R\b/i.test(stripped)) return "r";
    return "python";
}

function _stripLegacyShebang(code, lang) {
    // Only strip when the shebang was used as an in-content marker.
    if (lang === "bash") return code.replace(/^[\s\n]*#!BASH\s*\n?/i, "");
    if (lang === "r") return code.replace(/^[\s\n]*#!R\s*\n?/i, "");
    return code;
}

export function parseSegments(content) {
    const segs = [];
    const src = content.replace(/<done\s*\/?>/g, "");
    // Capture optional attribute list on <execute>; <observation> has none.
    const tagRe = /<(execute|observation)((?:\s+\w+="[^"]*")*)\s*>/g;
    let lastIndex = 0;
    let m;

    while ((m = tagRe.exec(src)) !== null) {
        if (m.index > lastIndex) {
            segs.push({ type: "text", content: src.slice(lastIndex, m.index) });
        }
        const tagName = m[1];
        const attrs = _parseAttrs(m[2] || "");
        const closeTag = `</${tagName}>`;
        const bodyStart = tagRe.lastIndex;
        const closeIdx = src.indexOf(closeTag, bodyStart);

        if (closeIdx === -1) {
            // Unclosed tag (still streaming).
            const rawBody = src.slice(bodyStart);
            if (tagName === "execute") {
                const lang = _detectLang(rawBody, attrs.lang);
                segs.push({
                    type: lang === "plan" ? "plan" : "code",
                    lang,
                    content: _stripLegacyShebang(rawBody, lang),
                    attrs,
                });
            } else {
                segs.push({ type: "observation", content: rawBody });
            }
            lastIndex = src.length;
            break;
        }

        const rawBody = src.slice(bodyStart, closeIdx);
        if (tagName === "execute") {
            const lang = _detectLang(rawBody, attrs.lang);
            segs.push({
                type: lang === "plan" ? "plan" : "code",
                lang,
                content: _stripLegacyShebang(rawBody, lang),
                attrs,
            });
        } else {
            segs.push({ type: "observation", content: rawBody });
        }
        lastIndex = closeIdx + closeTag.length;
        tagRe.lastIndex = lastIndex;
    }

    if (lastIndex < src.length) {
        segs.push({ type: "text", content: src.slice(lastIndex) });
    }

    return segs;
}

// Legacy — used by conversation hydration
export function updateAIMessage(msgEl, { thinking, code, observation, solution }) {
    const parts = [];
    if (thinking) parts.push(thinking);
    if (code) parts.push(`<execute>${code}</execute>`);
    if (observation) parts.push(`<observation>${observation}</observation>`);
    if (solution) parts.push(solution);
    renderStreamingMessage(msgEl, parts.join("\n"), false);
}

function detectCodeLanguage(code) {
    // Detect bash: shebang, or starts with common shell commands
    if (/^#!\s*\/(?:usr\/(?:local\/)?bin\/(?:env\s+)?)?(?:bash|sh|zsh)/m.test(code)) return "bash";
    if (/^(?:apt(?:-get)?|yum|pip(?:3)?|conda|brew|ls|cd|mkdir|cp|mv|rm|chmod|grep|find|cat|echo|export|source|curl|wget|git|docker)\s/m.test(code)) return "bash";
    return "python";
}

// Pre-highlight code synchronously using hljs and return HTML string.
// Falls back to escaped plain text if hljs isn't loaded yet.
function highlightCode(code, lang) {
    try {
        if (typeof hljs === "undefined") return escapeHtml(code);

        // First try the requested language
        if (hljs.getLanguage && hljs.getLanguage(lang)) {
            const result = hljs.highlight(code, { language: lang, ignoreIllegals: true });
            if (result && result.value) return result.value;
        }

        // Fallback to auto-detection (good when language pack isn't registered)
        if (hljs.highlightAuto) {
            const auto = hljs.highlightAuto(code);
            if (auto && auto.value) return auto.value;
        }
    } catch (_) { /* fall through */ }
    return escapeHtml(code);
}

function buildPlanBlock(content, inProgress = false) {
    const status = inProgress ? " ⏳ 规划中..." : " ✓";
    // Render markdown-like checklist items: [✓], [✗], [x], [ ], [-]
    const rendered = escapeHtml(content)
        .replace(/\[✓\]/g, '<span class="plan-check plan-done">✓</span>')
        .replace(/\[✗\]/g, '<span class="plan-check plan-fail">✗</span>')
        .replace(/\[x\]/gi, '<span class="plan-check plan-done">✓</span>')
        .replace(/\[\s*\]/g, '<span class="plan-check plan-pending">○</span>')
        .replace(/\[-\]/g, '<span class="plan-check plan-skip">—</span>')
        .replace(/\n/g, "<br>");
    return `
        <div class="plan-block${inProgress ? " plan-in-progress" : ""}">
            <div class="plan-header">
                <span>📋 任务计划${status}</span>
            </div>
            <div class="plan-body">${rendered}</div>
        </div>
    `;
}

function buildCollapsible(title, content, _type, defaultOpen = false, isRaw = false) {
    const openClass = defaultOpen ? "open" : "";
    const renderedContent = isRaw ? content : `<div>${escapeHtml(content).replace(/\n/g, "<br>")}</div>`;
    return `
        <div class="collapsible ${openClass}">
            <div class="collapsible-header" onclick="event.stopPropagation(); this.parentElement.classList.toggle('open')">
                <span class="arrow">▶</span>
                <span>${title}</span>
            </div>
            <div class="collapsible-body">${renderedContent}</div>
        </div>
    `;
}


// ========== Utility Maintenance Popup ==========

let maintenanceAutoHideTimer = null;

function showMaintenancePopup() {
    const popup = document.getElementById("maintenancePopup");
    const resultEl = document.getElementById("maintenanceResult");
    if (!popup) return;

    // Reset state
    popup.style.display = "block";
    popup.classList.remove("loading");
    resultEl.style.display = "none";
    resultEl.innerHTML = "";

    // Auto-hide after 30s if no action taken
    clearTimeout(maintenanceAutoHideTimer);
    maintenanceAutoHideTimer = setTimeout(() => hideMaintenancePopup(), 30000);
}

function hideMaintenancePopup() {
    const popup = document.getElementById("maintenancePopup");
    if (popup) popup.style.display = "none";
    clearTimeout(maintenanceAutoHideTimer);
}

async function handleMaintenanceAction(mode) {
    const popup = document.getElementById("maintenancePopup");
    const resultEl = document.getElementById("maintenanceResult");
    if (!popup) return;

    clearTimeout(maintenanceAutoHideTimer);
    popup.classList.add("loading");
    resultEl.style.display = "block";
    resultEl.innerHTML = "⏳ 正在分析...";

    try {
        const res = await fetch("/api/utilities/maintain", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ skip_cooldown: true, mode }),
        });
        const data = await res.json();

        popup.classList.remove("loading");

        if (mode === "preview") {
            if (data.preview && data.preview.length > 0) {
                resultEl.innerHTML = data.preview.map(a => {
                    const cls = `result-${a.type}`;
                    const icon = a.type === "save" ? "💾" : a.type === "update" ? "🔄" : "🗑️";
                    return `<div class="result-item ${cls}">${icon} ${a.type}: <strong>${a.name}</strong>${a.description ? " — " + a.description : ""}</div>`;
                }).join("");
            } else {
                resultEl.innerHTML = "✅ 无需变更";
                setTimeout(() => hideMaintenancePopup(), 3000);
            }
        } else {
            // execute mode
            const parts = [];
            if (data.saved?.length) parts.push(`💾 保存: ${data.saved.join(", ")}`);
            if (data.updated?.length) parts.push(`🔄 更新: ${data.updated.join(", ")}`);
            if (data.deleted?.length) parts.push(`🗑️ 删除: ${data.deleted.join(", ")}`);
            if (data.rejected?.length) parts.push(`⚠ 拒绝: ${data.rejected.join("; ")}`);

            if (parts.length > 0) {
                resultEl.innerHTML = parts.map(p => `<div class="result-item">${p}</div>`).join("");
                showToast("工具库已更新", "success");
            } else {
                resultEl.innerHTML = "✅ 无需变更";
            }
            setTimeout(() => hideMaintenancePopup(), 5000);
        }
    } catch (e) {
        popup.classList.remove("loading");
        resultEl.innerHTML = `❌ 失败: ${e.message}`;
        setTimeout(() => hideMaintenancePopup(), 5000);
    }
}

// Wire up buttons on DOM ready
document.addEventListener("DOMContentLoaded", () => {
    const previewBtn = document.getElementById("maintenancePreviewBtn");
    const executeBtn = document.getElementById("maintenanceExecuteBtn");
    const skipBtn = document.getElementById("maintenanceSkipBtn");

    if (previewBtn) previewBtn.addEventListener("click", () => handleMaintenanceAction("preview"));
    if (executeBtn) executeBtn.addEventListener("click", () => handleMaintenanceAction("execute"));
    if (skipBtn) skipBtn.addEventListener("click", () => hideMaintenancePopup());
});
