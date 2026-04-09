/**
 * LLM Wiki - Split-pane Editor with AI Assist
 * Shared between edit.html and create.html
 *
 * Note: Preview HTML is server-rendered from the same origin (trusted).
 * The preview endpoint uses the wiki's own markdown renderer.
 */

function initEditor(slug) {
    'use strict';

    var editor = document.getElementById('editor-content');
    var preview = document.getElementById('preview-content');
    var aiInput = document.getElementById('ai-assist-input');
    var aiBtn = document.getElementById('ai-assist-btn');
    var aiStatus = document.getElementById('ai-status');

    if (!editor || !preview) return;

    // ── Live preview with debounce ──────────────────────────────
    var previewTimer = null;

    function setPreviewPlaceholder(text) {
        while (preview.firstChild) preview.removeChild(preview.firstChild);
        var p = document.createElement('p');
        p.style.color = 'var(--wiki-text-light)';
        p.style.fontStyle = 'italic';
        p.textContent = text;
        preview.appendChild(p);
    }

    function applyPreviewHtml(htmlString) {
        // Server-rendered markdown from same-origin /api/preview endpoint.
        // This is the wiki's own Jinja/markdown renderer output, not user input.
        var temp = document.createElement('template');
        temp.innerHTML = htmlString;
        // Smooth transition: brief fade
        preview.style.opacity = '0.5';
        preview.style.transition = 'opacity 0.15s ease';
        while (preview.firstChild) preview.removeChild(preview.firstChild);
        preview.appendChild(temp.content.cloneNode(true));
        requestAnimationFrame(function() { preview.style.opacity = '1'; });
    }

    function updatePreview() {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(function() {
            var md = editor.value;
            if (!md.trim()) {
                setPreviewPlaceholder('Preview will appear here...');
                return;
            }
            fetch('/api/preview', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({content: md})
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.html) applyPreviewHtml(data.html);
            })
            .catch(function() {
                setPreviewPlaceholder('Preview failed to load');
            });
        }, 400);
    }

    editor.addEventListener('input', updatePreview);
    updatePreview(); // Initial

    // ── Markdown toolbar ────────────────────────────────────────
    var toolbar = document.querySelector('.wiki-md-toolbar');
    if (toolbar) {
        toolbar.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-md]');
            if (!btn) return;

            var action = btn.getAttribute('data-md');
            var start = editor.selectionStart;
            var end = editor.selectionEnd;
            var selected = editor.value.substring(start, end);
            var before = editor.value.substring(0, start);
            var after = editor.value.substring(end);
            var insert = '';
            var cursorOffset = 0;

            switch (action) {
                case 'bold':
                    insert = '**' + (selected || 'bold text') + '**';
                    cursorOffset = selected ? insert.length : 2;
                    break;
                case 'italic':
                    insert = '*' + (selected || 'italic text') + '*';
                    cursorOffset = selected ? insert.length : 1;
                    break;
                case 'heading':
                    insert = '## ' + (selected || 'Heading');
                    cursorOffset = insert.length;
                    break;
                case 'link':
                    insert = '[' + (selected || 'link text') + '](https://)';
                    cursorOffset = insert.length - 1;
                    break;
                case 'image':
                    insert = '![' + (selected || 'alt text') + '](https://)';
                    cursorOffset = insert.length - 1;
                    break;
                case 'code':
                    if (selected && selected.indexOf('\n') !== -1) {
                        insert = '```\n' + selected + '\n```';
                    } else {
                        insert = '`' + (selected || 'code') + '`';
                    }
                    cursorOffset = insert.length;
                    break;
                case 'list':
                    insert = (selected || 'item').split('\n').map(function(l) { return '- ' + l; }).join('\n');
                    cursorOffset = insert.length;
                    break;
                case 'wikilink':
                    insert = '[[' + (selected || 'page-slug') + ']]';
                    cursorOffset = selected ? insert.length : insert.length - 2;
                    break;
                case 'table':
                    insert = '| Header 1 | Header 2 |\n|----------|----------|\n| Cell 1   | Cell 2   |\n';
                    cursorOffset = insert.length;
                    break;
            }

            editor.value = before + insert + after;
            editor.selectionStart = editor.selectionEnd = start + cursorOffset;
            editor.focus();
            editor.dispatchEvent(new Event('input'));
        });
    }

    // ── Keyboard shortcuts ───────────────────────────────────────
    editor.addEventListener('keydown', function(e) {
        // Tab inserts spaces
        if (e.key === 'Tab') {
            e.preventDefault();
            var start = this.selectionStart;
            var end = this.selectionEnd;
            this.value = this.value.substring(0, start) + '    ' + this.value.substring(end);
            this.selectionStart = this.selectionEnd = start + 4;
            return;
        }

        // Ctrl/Cmd+S to save
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            var saveBtn = document.getElementById('save-btn');
            if (saveBtn) saveBtn.click();
            return;
        }

        // Ctrl/Cmd+B for bold
        if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
            e.preventDefault();
            var boldBtn = document.querySelector('[data-md="bold"]');
            if (boldBtn) boldBtn.click();
            return;
        }

        // Ctrl/Cmd+I for italic
        if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
            e.preventDefault();
            var italicBtn = document.querySelector('[data-md="italic"]');
            if (italicBtn) italicBtn.click();
            return;
        }

        // Ctrl/Cmd+K for link
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            var linkBtn = document.querySelector('[data-md="link"]');
            if (linkBtn) linkBtn.click();
            return;
        }
    });

    // ── AI Assist ───────────────────────────────────────────────
    function sendAiAssist(instruction) {
        var content = editor.value;
        if (!content.trim() && !instruction) return;

        aiBtn.disabled = true;
        aiBtn.innerHTML = '<span class="wiki-loading-inline"></span>Thinking...';
        aiStatus.textContent = 'AI is processing your request...';
        aiStatus.style.color = 'var(--wiki-accent)';

        fetch('/api/editor/assist', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                content: content,
                instruction: instruction,
                slug: slug || 'new-page'
            })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.result) {
                editor.value = data.result;
                updatePreview();
                aiStatus.textContent = 'Applied! (' + (data.tokens_est || '?') + ' tokens)';
                aiStatus.style.color = 'var(--wiki-success, #2e7d32)';
            } else {
                aiStatus.textContent = 'Error: ' + (data.error || 'Unknown');
                aiStatus.style.color = 'var(--wiki-error, #ba0000)';
            }
        })
        .catch(function(e) {
            aiStatus.textContent = 'Error: ' + e;
            aiStatus.style.color = 'var(--wiki-error, #ba0000)';
        })
        .finally(function() {
            aiBtn.disabled = false;
            aiBtn.textContent = 'AI Assist';
        });
    }

    if (aiBtn) {
        aiBtn.addEventListener('click', function() {
            var instruction = aiInput.value.trim();
            if (!instruction) { aiInput.focus(); return; }
            sendAiAssist(instruction);
            aiInput.value = '';
        });
    }

    if (aiInput) {
        aiInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                aiBtn.click();
            }
        });
    }

    // Preset buttons
    var presetBtns = document.querySelectorAll('.wiki-ai-preset-btn');
    presetBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            sendAiAssist(this.getAttribute('data-cmd'));
        });
    });
}
