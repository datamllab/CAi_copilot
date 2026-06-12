/**
 * Conversation management: list, create, select, rename, delete.
 */
import {
    state, dom,
    escapeHtml, formatDate, showToast, loadDraft,
} from "./state.js?v=7";
import { addMessage, updateAIMessage, renderStreamingMessage } from "./chat.js?v=7";

// ========== Load & Render ==========

export async function loadConversations() {
    try {
        const res = await fetch("/api/conversations");
        const data = await res.json();
        state.conversations = data.conversations || [];
        renderConversationList();
    } catch (e) {
        console.error("Failed to load conversations:", e);
    }
}

function renderConversationList() {
    if (!dom.conversationListEl) return;

    if (state.conversations.length === 0) {
        dom.conversationListEl.innerHTML = '<div class="conv-empty">💬 暂无会话，点击 + 新建</div>';
        return;
    }

    dom.conversationListEl.innerHTML = state.conversations
        .map((c) => {
            const active = c.id === state.currentConvId ? "active" : "";
            const title = escapeHtml(c.title || "新对话");
            const date = formatDate(c.updated_at);
            return `
                <div class="conversation-item ${active}" data-conv-id="${c.id}">
                    <span class="conv-title" title="${title}">${title}</span>
                    <div class="conv-actions">
                        <button class="conv-action-btn conv-rename-btn" title="重命名">✏️</button>
                        <button class="conv-action-btn danger conv-delete-btn" title="删除">🗑️</button>
                    </div>
                    <span class="conv-meta">${date}</span>
                </div>
            `;
        })
        .join("");

    // Bind events via delegation
    dom.conversationListEl.querySelectorAll(".conversation-item").forEach(item => {
        const convId = item.dataset.convId;
        item.addEventListener("click", () => selectConversation(convId));
        item.querySelector(".conv-rename-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            renameConversation(convId);
        });
        item.querySelector(".conv-delete-btn").addEventListener("click", (e) => {
            e.stopPropagation();
            removeConversation(convId);
        });
    });
}

// ========== Conversation Actions ==========

export async function selectConversation(convId) {
    if (state.isStreaming) {
        showToast("请等待当前对话完成", "info");
        return;
    }
    try {
        const res = await fetch(`/api/conversations/${convId}`);
        if (!res.ok) throw new Error("加载失败");
        const conv = await res.json();

        state.currentConvId = convId;
        renderConversationList();

        dom.messagesEl.innerHTML = "";
        dom.welcomeScreen.style.display = "none";

        const messages = conv.messages || [];
        if (messages.length === 0) {
            dom.welcomeScreen.style.display = "flex";
        } else {
            for (const msg of messages) {
                if (msg.role === "user") {
                    addMessage("user", msg.content);
                } else if (msg.role === "assistant") {
                    const aiEl = addMessage("assistant", "", false);
                    const content = msg.content || "";
                    if (content.includes("<execute") || content.includes("<observation")) {
                        renderStreamingMessage(aiEl, content, false);
                    } else {
                        updateAIMessage(aiEl, { solution: content });
                    }
                }
            }
        }

        // Restore draft for this conversation
        const draft = loadDraft(convId);
        if (draft && dom.messageInput) {
            dom.messageInput.value = draft;
            dom.messageInput.style.height = "auto";
            dom.messageInput.style.height = Math.min(dom.messageInput.scrollHeight, 200) + "px";
            updateSendBtnState();
        } else if (dom.messageInput) {
            dom.messageInput.value = "";
            dom.messageInput.style.height = "auto";
            updateSendBtnState();
        }
    } catch (e) {
        showToast("无法加载会话: " + e.message, "error");
    }
}

export async function startNewConversation() {
    if (state.isStreaming) {
        showToast("请等待当前对话完成", "info");
        return;
    }
    try {
        const res = await fetch("/api/conversations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({}),
        });
        const meta = await res.json();
        state.currentConvId = meta.id;

        dom.messagesEl.innerHTML = "";
        dom.welcomeScreen.style.display = "flex";

        await loadConversations();
        showToast("已创建新会话", "success");
    } catch (e) {
        showToast("创建失败: " + e.message, "error");
    }
}

async function renameConversation(convId) {
    const conv = state.conversations.find((c) => c.id === convId);
    if (!conv) return;
    const newTitle = prompt("重命名会话:", conv.title);
    if (!newTitle || newTitle === conv.title) return;
    try {
        await fetch(`/api/conversations/${convId}/title`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: newTitle }),
        });
        await loadConversations();
    } catch (e) {
        showToast("重命名失败", "error");
    }
}

async function removeConversation(convId) {
    if (!confirm("确定删除这个会话？此操作不可恢复。")) return;
    try {
        await fetch(`/api/conversations/${convId}`, { method: "DELETE" });
        if (convId === state.currentConvId) {
            state.currentConvId = null;
            dom.messagesEl.innerHTML = "";
            dom.welcomeScreen.style.display = "flex";
        }
        await loadConversations();
        showToast("已删除", "info");
    } catch (e) {
        showToast("删除失败", "error");
    }
}
