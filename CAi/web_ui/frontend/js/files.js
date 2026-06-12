/**
 * File management: upload, download, delete, preview, reference.
 */
import {
    state, dom, $,
    escapeHtml, getFileIcon, formatFileSize, renderMarkdown,
    safeHighlight, showToast, updateSendBtnState,
} from "./state.js?v=7";

// ========== Load & Render ==========

export async function loadFiles() {
    try {
        const res = await fetch("/api/files");
        const data = await res.json();
        state.workspaceFiles = data.files || [];
        renderFileList();
    } catch (e) {
        console.error("Failed to load files:", e);
    }
}

function renderFileList() {
    if (state.workspaceFiles.length === 0) {
        dom.fileList.innerHTML = '<div class="file-empty">📂 暂无文件</div>';
        return;
    }

    dom.fileList.innerHTML = state.workspaceFiles
        .map((f) => {
            const icon = getFileIcon(f.name);
            const size = formatFileSize(f.size);
            const name = escapeHtml(f.name);
            return `
                <div class="file-item" data-filename="${name}">
                    <span class="file-icon">${icon}</span>
                    <span class="file-name" title="${name}">${name}</span>
                    <span class="file-size">${size}</span>
                    <span class="file-action file-ref-btn" title="引用到对话">📌</span>
                    <span class="file-action file-dl-btn" title="下载">⬇️</span>
                    <span class="file-action file-del-btn" title="删除">🗑️</span>
                </div>
            `;
        })
        .join("");

    dom.fileList.querySelectorAll(".file-item").forEach((item) => {
        const name = item.dataset.filename;
        item.querySelector(".file-name").addEventListener("click", () => previewFile(name));
        item.querySelector(".file-ref-btn").addEventListener("click", (e) => { e.stopPropagation(); referenceFile(name); });
        item.querySelector(".file-dl-btn").addEventListener("click", (e) => { e.stopPropagation(); downloadFile(name); });
        item.querySelector(".file-del-btn").addEventListener("click", (e) => { e.stopPropagation(); deleteFile(name); });
    });
}

// ========== File Actions ==========

export function referenceFile(filename) {
    if (state.referencedFiles.includes(filename)) {
        showToast("已引用该文件", "info");
        return;
    }
    state.referencedFiles.push(filename);
    renderAttachedFiles();
    updateSendBtnState();
    showToast(`已引用: ${filename}`, "success");
}

export async function handleSidebarUpload(e) {
    const files = e.target.files;
    if (!files.length) return;

    const formData = new FormData();
    for (const file of files) {
        formData.append("files", file);
    }

    try {
        await fetch("/api/upload", { method: "POST", body: formData });
        showToast("文件上传成功", "success");
        loadFiles();
    } catch (err) {
        showToast("上传失败: " + err.message, "error");
    }
    e.target.value = "";
}

export function handleChatFileAttach(e) {
    const files = Array.from(e.target.files);
    if (!files.length) return;

    state.attachedFiles.push(...files);
    renderAttachedFiles();
    updateSendBtnState();

    if (state.workspaceFiles.length > 0) {
        showFilePickerModal();
    }
    e.target.value = "";
}

export function renderAttachedFiles() {
    const items = [
        ...state.attachedFiles.map((f, i) => `
            <div class="attached-file">
                <span>${getFileIcon(f.name)} ${f.name}</span>
                <span class="remove-file" data-action="remove-attached" data-index="${i}">✕</span>
            </div>
        `),
        ...state.referencedFiles.map((name, i) => `
            <div class="attached-file attached-file-ref">
                <span>📌 ${name}</span>
                <span class="remove-file" data-action="remove-ref" data-index="${i}">✕</span>
            </div>
        `),
    ];
    dom.attachedFilesEl.innerHTML = items.join("");

    // Bind remove buttons
    dom.attachedFilesEl.querySelectorAll("[data-action=remove-attached]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.attachedFiles.splice(Number(btn.dataset.index), 1);
            renderAttachedFiles();
            updateSendBtnState();
        });
    });
    dom.attachedFilesEl.querySelectorAll("[data-action=remove-ref]").forEach(btn => {
        btn.addEventListener("click", () => {
            state.referencedFiles.splice(Number(btn.dataset.index), 1);
            renderAttachedFiles();
            updateSendBtnState();
        });
    });
}

export function downloadFile(filename) {
    const a = document.createElement("a");
    a.href = `/api/files/${encodeURIComponent(filename)}`;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

export async function deleteFile(filename) {
    if (!confirm(`确定删除 ${filename}？`)) return;
    try {
        await fetch(`/api/files/${encodeURIComponent(filename)}`, { method: "DELETE" });
        showToast("已删除", "info");
        loadFiles();
    } catch (err) {
        showToast("删除失败", "error");
    }
}

// ========== Preview ==========

function previewFile(filename) {
    const ext = filename.split(".").pop().toLowerCase();
    const fileUrl = `/api/files/${encodeURIComponent(filename)}?inline=1`;

    const imageExts = ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg"];
    const textExts = ["txt", "csv", "py", "json", "sh", "yaml", "yml", "r", "log", "smi"];

    if (imageExts.includes(ext)) {
        showPreviewModal(filename, `<img src="${fileUrl}" class="preview-image" alt="${escapeHtml(filename)}">`);
    } else if (ext === "pdf") {
        showPreviewModal(filename, `
            <object data="${fileUrl}" type="application/pdf" class="preview-pdf">
                <p>浏览器无法预览 PDF。<a href="/api/files/${encodeURIComponent(filename)}" download="${escapeHtml(filename)}">点击下载</a></p>
            </object>
        `);
    } else if (ext === "md" || textExts.includes(ext)) {
        showPreviewModal(filename, `<div class="preview-text-loading">加载中...</div>`);
        fetchAndRenderText(fileUrl, ext === "md");
    } else {
        showPreviewModal(filename, `
            <div class="preview-unsupported">
                <p>该文件类型不支持预览</p>
                <button class="btn btn-outline preview-download-btn">⬇️ 下载文件</button>
            </div>
        `);
        const dlBtn = $(".preview-download-btn");
        if (dlBtn) dlBtn.addEventListener("click", () => downloadFile(filename));
    }
}

function fetchAndRenderText(fileUrl, isMarkdown) {
    fetch(fileUrl)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
            return res.text();
        })
        .then(text => {
            const container = $(".preview-body");
            if (!container) return;
            if (isMarkdown) {
                container.innerHTML = `<div class="preview-markdown message-body">${renderMarkdown(text)}</div>`;
            } else {
                const previewText = text.length > 50000
                    ? text.slice(0, 50000) + "\n\n... (文件过长，仅展示前 50000 字符)"
                    : text;
                container.innerHTML = `<pre class="preview-text-content"><code>${escapeHtml(previewText)}</code></pre>`;
            }
            container.querySelectorAll("pre code").forEach(b => safeHighlight(b));
        })
        .catch((err) => {
            const container = $(".preview-body");
            if (container) container.innerHTML = `<div class="preview-error">无法加载文件: ${escapeHtml(err.message)}</div>`;
        });
}

// ========== Modals ==========

function showPreviewModal(filename, bodyHtml) {
    closeAllModals();
    const modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.id = "previewModal";
    modal.innerHTML = `
        <div class="modal-container">
            <div class="modal-header">
                <span class="modal-title">${getFileIcon(filename)} ${escapeHtml(filename)}</span>
                <div class="modal-actions">
                    <button class="btn btn-sm btn-outline modal-ref-btn">📌 引用</button>
                    <button class="btn btn-sm btn-outline modal-dl-btn">⬇️ 下载</button>
                    <button class="btn-icon modal-close-btn">✕</button>
                </div>
            </div>
            <div class="preview-body">${bodyHtml}</div>
        </div>
    `;
    document.body.appendChild(modal);
    requestAnimationFrame(() => modal.classList.add("visible"));

    modal.querySelector(".modal-ref-btn").addEventListener("click", () => { referenceFile(filename); closeAllModals(); });
    modal.querySelector(".modal-dl-btn").addEventListener("click", () => downloadFile(filename));
    modal.querySelector(".modal-close-btn").addEventListener("click", closeAllModals);
}

function showFilePickerModal() {
    closeAllModals();

    if (state.workspaceFiles.length === 0) return;

    const modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.id = "filePickerModal";

    const fileItems = state.workspaceFiles.map(f => {
        const checked = state.referencedFiles.includes(f.name) ? "checked" : "";
        return `
            <label class="picker-item">
                <input type="checkbox" value="${escapeHtml(f.name)}" ${checked}>
                <span>${getFileIcon(f.name)} ${escapeHtml(f.name)}</span>
                <span class="picker-size">${formatFileSize(f.size)}</span>
            </label>
        `;
    }).join("");

    const attachedCount = state.attachedFiles.length;

    modal.innerHTML = `
        <div class="modal-container modal-sm">
            <div class="modal-header">
                <span class="modal-title">📌 引用工作区文件</span>
                <button class="btn-icon modal-close-btn">✕</button>
            </div>
            <div class="picker-body">
                <p class="picker-hint">已选择 ${attachedCount} 个新文件。还可以选择工作区已有文件作为引用：</p>
                <div class="picker-list">${fileItems}</div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-sm btn-outline modal-done-btn">完成</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
    requestAnimationFrame(() => modal.classList.add("visible"));

    modal.querySelector(".modal-close-btn").addEventListener("click", closeAllModals);
    modal.querySelector(".modal-done-btn").addEventListener("click", closeAllModals);

    modal.querySelectorAll("input[type=checkbox]").forEach(cb => {
        cb.addEventListener("change", () => {
            const name = cb.value;
            if (cb.checked && !state.referencedFiles.includes(name)) {
                state.referencedFiles.push(name);
            } else if (!cb.checked) {
                state.referencedFiles = state.referencedFiles.filter(n => n !== name);
            }
            renderAttachedFiles();
            updateSendBtnState();
        });
    });
}

export function closeAllModals() {
    document.querySelectorAll(".modal-overlay").forEach(m => m.remove());
}

// ========== Workspace Actions ==========

export async function exportPdf() {
    try {
        showToast("正在生成 PDF...", "info");
        const url = state.currentConvId
            ? `/api/export-pdf?conversation_id=${encodeURIComponent(state.currentConvId)}`
            : "/api/export-pdf";
        const res = await fetch(url, { method: "POST" });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Export failed");
        }
        const blob = await res.blob();
        const downloadUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = downloadUrl;
        a.download = `conversation_${Date.now()}.pdf`;
        a.click();
        URL.revokeObjectURL(downloadUrl);
        showToast("PDF 导出成功", "success");
        loadFiles();
    } catch (e) {
        showToast("导出失败: " + e.message, "error");
    }
}

export async function clearFiles() {
    if (!confirm("确定清空工作区所有文件？（会话记录会保留）")) return;
    try {
        await fetch("/api/workspace", { method: "DELETE" });
        loadFiles();
        showToast("已清空工作区文件", "info");
    } catch (e) {
        showToast("清空失败", "error");
    }
}
