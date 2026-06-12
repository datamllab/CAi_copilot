/**
 * Shared application state, DOM references, and utility functions.
 */

// ========== State ==========
export const state = {
    messages: [],
    isStreaming: false,
    attachedFiles: [],       // File objects from local disk
    referencedFiles: [],     // filenames from workspace
    workspaceFiles: [],
    currentConvId: null,     // active conversation id
    conversations: [],       // conversation metadata list
};

// ========== DOM Helpers ==========
export const $ = (sel) => document.querySelector(sel);

// ========== Safe wrappers for optional CDN libs ==========
export function safeHighlight(block) {
    try {
        if (typeof hljs !== "undefined" && hljs?.highlightElement) {
            block.removeAttribute("data-highlighted");
            hljs.highlightElement(block);
        }
    } catch (_) { /* ignore */ }
}

export function safeCreateIcons() {
    try {
        if (typeof lucide !== "undefined" && lucide?.createIcons) {
            lucide.createIcons();
        }
    } catch (_) { /* ignore */ }
}

// ========== DOM Element References ==========
// Initialized after DOMContentLoaded via initDomRefs()
export const dom = {
    messagesContainer: null,
    messagesEl: null,
    welcomeScreen: null,
    messageInput: null,
    sendBtn: null,
    fileList: null,
    attachedFilesEl: null,
    fileUploadInput: null,
    chatFileInput: null,
    conversationListEl: null,
};

export function initDomRefs() {
    dom.messagesContainer = $("#messagesContainer");
    dom.messagesEl = $("#messages");
    dom.welcomeScreen = $("#welcomeScreen");
    dom.messageInput = $("#messageInput");
    dom.sendBtn = $("#sendBtn");
    dom.fileList = $("#fileList");
    dom.attachedFilesEl = $("#attachedFiles");
    dom.fileUploadInput = $("#fileUploadInput");
    dom.chatFileInput = $("#chatFileInput");
    dom.conversationListEl = $("#conversationList");
}

// ========== Utility Functions ==========

export function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

export function renderMarkdown(text) {
    try {
        const rawHtml = marked.parse(text);
        if (typeof DOMPurify !== "undefined" && DOMPurify?.sanitize) {
            return DOMPurify.sanitize(rawHtml);
        }
        return rawHtml;
    } catch {
        return escapeHtml(text).replace(/\n/g, "<br>");
    }
}

export function getFileIcon(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    const icons = {
        pdf: "📄", csv: "📊", xlsx: "📊", xls: "📊",
        png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️",
        py: "🐍", r: "📈", json: "📋", txt: "📝", md: "📝",
        sdf: "🧪", mol: "🧪", pdb: "🧬",
    };
    return icons[ext] || "📁";
}

export function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

export function formatDate(iso) {
    if (!iso) return "";
    try {
        const d = new Date(iso);
        const now = new Date();
        const diffMs = now - d;
        const diffMin = Math.floor(diffMs / 60000);
        const diffHour = Math.floor(diffMs / 3600000);
        const diffDay = Math.floor(diffMs / 86400000);
        if (diffMin < 1) return "刚刚";
        if (diffMin < 60) return `${diffMin}分钟前`;
        if (diffHour < 24) return `${diffHour}小时前`;
        if (diffDay < 7) return `${diffDay}天前`;
        return `${d.getMonth() + 1}/${d.getDate()}`;
    } catch {
        return "";
    }
}

export function scrollToBottom() {
    dom.messagesContainer.scrollTop = dom.messagesContainer.scrollHeight;
}

export function showToast(message, type = "info") {
    let container = $(".toast-container");
    if (!container) {
        container = document.createElement("div");
        container.className = "toast-container";
        document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ========== Theme ==========

export function initTheme() {
    const saved = localStorage.getItem("cai-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = saved || (prefersDark ? "dark" : "light");
    applyTheme(theme);
}

export function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("cai-theme", theme);

    const hljsLink = document.getElementById("hljs-theme");
    if (hljsLink) {
        hljsLink.href = theme === "dark"
            ? "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css"
            : "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css";
    }
}

export function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
}

// ========== Send Button State ==========
// Lives here (not in chat.js) to avoid circular imports with files.js.

export function updateSendBtnState() {
    if (!dom.sendBtn || !dom.messageInput) return;
    if (state.isStreaming) {
        dom.sendBtn.disabled = false;
        dom.sendBtn.classList.add("btn-stop");
        dom.sendBtn.title = "停止生成 (Esc)";
    } else {
        dom.sendBtn.classList.remove("btn-stop");
        dom.sendBtn.title = "发送 (Enter)";
        dom.sendBtn.disabled = !dom.messageInput.value.trim()
            && state.attachedFiles.length === 0
            && state.referencedFiles.length === 0;
    }
}

// ========== Draft Autosave ==========

const _DRAFT_KEY = (convId) => `cai_draft_${convId || "new"}`;
const _DRAFT_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

export function saveDraft(convId, text) {
    const key = _DRAFT_KEY(convId);
    if (!text || !text.trim()) {
        localStorage.removeItem(key);
        return;
    }
    localStorage.setItem(key, JSON.stringify({ text, timestamp: Date.now() }));
}

export function loadDraft(convId) {
    try {
        const raw = localStorage.getItem(_DRAFT_KEY(convId));
        if (!raw) return null;
        const data = JSON.parse(raw);
        if (Date.now() - data.timestamp > _DRAFT_TTL_MS) {
            localStorage.removeItem(_DRAFT_KEY(convId));
            return null;
        }
        return data.text;
    } catch {
        return null;
    }
}

export function clearDraft(convId) {
    localStorage.removeItem(_DRAFT_KEY(convId));
}
