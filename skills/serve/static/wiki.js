/**
 * LLM Wiki - Page JavaScript
 * Handles search autocomplete, expand buttons, TOC toggle, and researching status
 */

(function() {
    'use strict';

    // ========================================================================
    // Search Autocomplete
    // ========================================================================

    const searchInput = document.getElementById('search-input');
    let searchTimeout = null;
    let autocompleteDropdown = null;

    if (searchInput) {
        searchInput.addEventListener('input', debounce(function(e) {
            const query = e.target.value.trim();

            if (query.length < 2) {
                closeAutocomplete();
                return;
            }

            fetch('/api/suggestions?q=' + encodeURIComponent(query))
                .then(response => response.json())
                .then(data => {
                    showAutocomplete(query, data.suggestions || []);
                })
                .catch(error => {
                    console.error('Autocomplete error:', error);
                });
        }, 300));

        // Close autocomplete on blur
        searchInput.addEventListener('blur', function() {
            setTimeout(closeAutocomplete, 200);
        });

        // Handle keyboard navigation in autocomplete
        searchInput.addEventListener('keydown', function(e) {
            if (!autocompleteDropdown) {
                return;
            }
            var items = autocompleteDropdown.querySelectorAll('.wiki-autocomplete-item');
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
                updateAutocompleteSelection(autocompleteDropdown);
                if (items[selectedIndex]) items[selectedIndex].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, -1);
                updateAutocompleteSelection(autocompleteDropdown);
                if (selectedIndex >= 0 && items[selectedIndex]) items[selectedIndex].scrollIntoView({ block: 'nearest' });
            } else if (e.key === 'Enter' && selectedIndex >= 0 && items[selectedIndex]) {
                e.preventDefault();
                items[selectedIndex].click();
            } else if (e.key === 'Escape') {
                closeAutocomplete();
            } else if (e.key === 'Enter') {
                closeAutocomplete();
            }
        });
    }

    let selectedIndex = -1;

    function showAutocomplete(query, suggestions) {
        closeAutocomplete();
        selectedIndex = -1;

        if (suggestions.length === 0) {
            return;
        }

        const dropdown = document.createElement('div');
        dropdown.className = 'wiki-autocomplete-dropdown';
        dropdown.setAttribute('role', 'listbox');
        dropdown.setAttribute('aria-label', 'Search suggestions');
        dropdown.style.cssText = `
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: var(--wiki-bg, white);
            border: 1px solid var(--wiki-border, #a2a9b1);
            border-top: none;
            border-radius: 0 0 8px 8px;
            max-height: 300px;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: 0 4px 16px var(--wiki-shadow-md, rgba(0,0,0,0.12));
            opacity: 0;
            transform: translateY(-4px);
            transition: opacity 0.15s ease, transform 0.15s ease;
        `;

        suggestions.forEach(function(suggestion, idx) {
            const item = document.createElement('div');
            item.className = 'wiki-autocomplete-item';
            item.setAttribute('role', 'option');
            item.style.cssText = `
                padding: 10px 14px;
                cursor: pointer;
                border-bottom: 1px solid var(--wiki-border-light, #e8eaed);
                font-family: var(--wiki-font-ui, sans-serif);
                font-size: 0.9em;
                transition: background-color 0.1s ease;
                color: var(--wiki-text, #1a1a1a);
            `;

            // Escape query for regex safety
            const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const highlightedText = suggestion.title.replace(
                new RegExp('(' + escaped + ')', 'gi'),
                '<strong>$1</strong>'
            );

            item.innerHTML = highlightedText;

            item.addEventListener('mouseenter', function() {
                item.style.backgroundColor = 'var(--wiki-bg-hover, #f0f2f5)';
                selectedIndex = idx;
                updateAutocompleteSelection(dropdown);
            });

            item.addEventListener('mouseleave', function() {
                item.style.backgroundColor = 'transparent';
            });

            item.addEventListener('click', function() {
                searchInput.value = suggestion.title;
                closeAutocomplete();
                searchInput.form.submit();
            });

            dropdown.appendChild(item);
        });

        // Position dropdown
        const searchForm = searchInput.closest('.wiki-search-form');
        if (searchForm) {
            searchForm.style.position = 'relative';
            searchForm.appendChild(dropdown);
            autocompleteDropdown = dropdown;
            // Trigger fade-in
            requestAnimationFrame(function() {
                dropdown.style.opacity = '1';
                dropdown.style.transform = 'translateY(0)';
            });
        }
    }

    function updateAutocompleteSelection(dropdown) {
        if (!dropdown) return;
        var items = dropdown.querySelectorAll('.wiki-autocomplete-item');
        items.forEach(function(item, i) {
            item.style.backgroundColor = i === selectedIndex ? 'var(--wiki-bg-hover, #f0f2f5)' : 'transparent';
            item.setAttribute('aria-selected', i === selectedIndex ? 'true' : 'false');
        });
    }

    function closeAutocomplete() {
        if (autocompleteDropdown) {
            autocompleteDropdown.remove();
            autocompleteDropdown = null;
        }
    }

    // ========================================================================
    // Expand Button Handler
    // ========================================================================

    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('wiki-expand-btn')) {
            e.preventDefault();
            handleExpand(e.target);
        }
    });

    function handleExpand(button) {
        const section = button.closest('[data-expand-id]');
        if (!section) {
            return;
        }

        const expandId = section.getAttribute('data-expand-id');
        const expandContainer = document.getElementById('expand-' + expandId);

        if (!expandContainer) {
            return;
        }

        // Show loading state
        button.disabled = true;
        var origText = button.textContent;
        button.innerHTML = '<span class="wiki-loading-inline"></span>Loading...';

        fetch('/api/expand', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ expand_id: expandId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'done') {
                // Expand is complete - fade in content
                expandContainer.innerHTML = data.content_html || '';
                expandContainer.style.display = 'block';
                expandContainer.style.opacity = '0';
                expandContainer.style.transition = 'opacity 0.3s ease';
                requestAnimationFrame(function() { expandContainer.style.opacity = '1'; });
                button.style.display = 'none';
            } else if (data.status === 'in_progress') {
                // Poll for completion
                pollExpandCompletion(expandId, button, expandContainer);
            } else {
                button.disabled = false;
                button.textContent = origText || 'Expand';
            }
        })
        .catch(error => {
            console.error('Expand error:', error);
            button.disabled = false;
            button.textContent = 'Retry';
            button.title = 'Expansion failed. Click to retry.';
        });
    }

    function pollExpandCompletion(expandId, button, container) {
        const maxAttempts = 30;
        let attempts = 0;

        function poll() {
            attempts++;

            if (attempts > maxAttempts) {
                button.disabled = false;
                button.textContent = 'Expand';
                return;
            }

            fetch('/api/expand?expand_id=' + encodeURIComponent(expandId))
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'done') {
                        container.innerHTML = data.content_html || '';
                        container.style.display = 'block';
                        button.style.display = 'none';
                    } else {
                        setTimeout(poll, 500);
                    }
                })
                .catch(error => {
                    console.error('Poll error:', error);
                    setTimeout(poll, 500);
                });
        }

        setTimeout(poll, 500);
    }

    // ========================================================================
    // Table of Contents Toggle
    // ========================================================================

    const tocToggle = document.querySelector('.wiki-toc-toggle');
    if (tocToggle) {
        tocToggle.addEventListener('click', function(e) {
            e.preventDefault();
            const content = document.querySelector('.wiki-toc-content');

            if (content.style.display === 'none') {
                content.style.display = 'block';
                content.style.opacity = '0';
                content.style.transition = 'opacity 0.2s ease';
                requestAnimationFrame(function() { content.style.opacity = '1'; });
                tocToggle.textContent = '\u25BC';
                tocToggle.setAttribute('aria-expanded', 'true');
            } else {
                content.style.opacity = '0';
                setTimeout(function() { content.style.display = 'none'; }, 200);
                tocToggle.textContent = '\u25B6';
                tocToggle.setAttribute('aria-expanded', 'false');
            }
        });
    }

    // ========================================================================
    // Research Topic Button (Search Results Page)
    // ========================================================================

    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('wiki-research-btn')) {
            e.preventDefault();

            const topic = e.target.getAttribute('data-topic');
            if (!topic) {
                return;
            }

            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/api/research';

            const topicInput = document.createElement('input');
            topicInput.type = 'hidden';
            topicInput.name = 'topic';
            topicInput.value = topic;

            form.appendChild(topicInput);
            document.body.appendChild(form);
            form.submit();
        }
    });

    // ========================================================================
    // Utility Functions
    // ========================================================================

    function debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }

    // ========================================================================
    // Research dashboard auto-refresh
    // ========================================================================

    function initDashboardRefresh() {
        const taskTable = document.getElementById('active-tasks-body');
        if (!taskTable) return;

        setInterval(async () => {
            try {
                const resp = await fetch('/api/status/all');
                const tasks = await resp.json();
                // Update table rows (rebuild tbody innerHTML)
                let html = '';
                tasks.forEach(task => {
                    html += `
                        <tr>
                            <td><a href="/wiki/${task.slug}">${task.slug}</a></td>
                            <td>${task.task_type || 'unknown'}</td>
                            <td><span class="priority-badge priority-${task.priority}">${task.priority || 'medium'}</span></td>
                            <td><span class="status-badge status-${task.status}">${task.status || 'unknown'}</span></td>
                            <td>${task.stage || '—'}</td>
                            <td>${task.elapsed_time || '—'}</td>
                        </tr>
                    `;
                });
                taskTable.innerHTML = html || '<tr><td colspan="6" style="text-align: center; padding: 12px;">No active tasks</td></tr>';
            } catch (e) { console.log('Dashboard refresh failed:', e); }
        }, 5000);
    }

    // ========================================================================
    // Research suggestions panel
    // ========================================================================

    function initSuggestions() {
        const panel = document.querySelector('.suggestions-header');
        if (!panel) return;

        panel.addEventListener('click', async () => {
            const body = panel.nextElementSibling;
            body.classList.toggle('open');
            if (body.classList.contains('open') && body.dataset.loaded !== 'true') {
                const slug = body.dataset.slug;
                try {
                    const resp = await fetch(`/api/suggestions/research/${slug}`);
                    const suggestions = await resp.json();
                    body.innerHTML = suggestions.map(s => `
                        <div class="suggestion-item">
                            <div>
                                <a href="/wiki/${s.slug}">${s.slug}</a>
                                <div class="suggestion-reason">${s.reason || 'Suggested topic'}</div>
                            </div>
                            <button class="suggestion-research-btn" onclick="researchTopic('${s.slug}', '${s.priority || 'high'}')">Research</button>
                        </div>
                    `).join('') || '<p style="padding: 8px; color: #54595d;">No suggestions available.</p>';
                    body.dataset.loaded = 'true';
                } catch (e) {
                    body.innerHTML = '<p style="padding: 8px; color: #ba0000;">Failed to load suggestions.</p>';
                }
            }
        });
    }

    // ========================================================================
    // Annotation support
    // ========================================================================

    function initAnnotations() {
        const content = document.querySelector('.wiki-content');
        if (!content) return;

        const addNoteBtn = document.createElement('button');
        addNoteBtn.className = 'add-note-btn';
        addNoteBtn.textContent = 'Add Note';
        document.body.appendChild(addNoteBtn);

        content.addEventListener('mouseup', (e) => {
            const selection = window.getSelection();
            if (selection.toString().trim().length > 0) {
                const range = selection.getRangeAt(0);
                const rect = range.getBoundingClientRect();
                addNoteBtn.style.display = 'block';
                addNoteBtn.style.top = (rect.top + window.scrollY - 30) + 'px';
                addNoteBtn.style.left = (rect.left + window.scrollX) + 'px';
                addNoteBtn.dataset.text = selection.toString();
            } else {
                addNoteBtn.style.display = 'none';
            }
        });

        addNoteBtn.addEventListener('click', async () => {
            const text = addNoteBtn.dataset.text;
            const note = prompt('Add a note about this text:');
            if (note) {
                const slug = document.querySelector('[data-page-slug]')?.dataset.pageSlug;
                try {
                    await fetch('/api/annotations', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({slug, type: 'comment', content: note + '\n\n> ' + text})
                    });
                    addNoteBtn.style.display = 'none';
                    // Optionally show a confirmation
                    alert('Note added successfully!');
                } catch (e) {
                    console.error('Failed to add annotation:', e);
                }
            }
        });
    }

    // ========================================================================
    // Research with priority/depth
    // ========================================================================

    window.researchTopic = function(slug, priority = 'high', depth = 'full') {
        fetch('/api/research', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({slug, query: slug.replace(/-/g, ' '), priority, depth})
        }).then(r => r.json()).then(data => {
            window.location.href = '/wiki/' + slug;
        }).catch(e => {
            console.error('Research request failed:', e);
        });
    };

    // ========================================================================
    // Delete Page Button
    // ========================================================================

    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('wiki-delete-btn')) {
            e.preventDefault();
            const slug = e.target.getAttribute('data-slug');
            if (!slug) return;

            if (!confirm('Delete page "' + slug + '"? This cannot be undone.')) return;

            fetch('/api/wiki/' + encodeURIComponent(slug), { method: 'DELETE' })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'deleted') {
                        window.location.href = '/';
                    } else {
                        alert('Page not found.');
                    }
                })
                .catch(err => {
                    console.error('Delete failed:', err);
                    alert('Delete failed.');
                });
        }
    });

    // ========================================================================
    // Research Queue Sidebar (auto-refresh)
    // ========================================================================

    function initResearchSidebar() {
        var body = document.getElementById('research-sidebar-body');
        if (!body) return;

        // Track last data hash to avoid unnecessary DOM rebuilds
        var lastDataHash = '';
        var queueCountEl = document.getElementById('queue-count');
            header.addEventListener('click', function() {
                minimized = !minimized;
                body.style.display = minimized ? 'none' : 'block';
                sidebar.classList.toggle('minimized', minimized);
            });
        }

        // Cancel a task
        function cancelTask(taskId) {
            fetch('/api/research/' + taskId + '/cancel', { method: 'POST' })
                .then(function() { refresh(); })
                .catch(function(e) { console.error('Cancel failed:', e); });
        }

        // Reorder a task
        function reorderTask(taskId, direction) {
            fetch('/api/research/' + taskId + '/reorder', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direction: direction })
            })
                .then(function() { refresh(); })
                .catch(function(e) { console.error('Reorder failed:', e); });
        }

        async function refresh() {
            try {
                var resp = await fetch('/api/research/active');
                var tasks = await resp.json();

                // Hash the response to skip DOM rebuild if nothing changed
                var hash = JSON.stringify(tasks.map(function(t) {
                    return t.id + ':' + t.status + ':' + (t.progress && t.progress.stage || '') + ':' + (t.elapsed || 0);
                }));
                if (hash === lastDataHash) return;
                lastDataHash = hash;

                // Update queue count badge
                if (queueCountEl) {
                    queueCountEl.textContent = tasks.length > 0 ? tasks.length : '';
                }

                if (!tasks || tasks.length === 0) {
                    body.textContent = '';
                    var p = document.createElement('p');
                    p.className = 'research-sidebar-empty';
                    p.textContent = 'No active tasks';
                    body.appendChild(p);
                    return;
                }

                body.textContent = '';
                tasks.forEach(function(task, idx) {
                    var item = document.createElement('div');
                    item.className = 'research-sidebar-item';

                    // Top row: link + controls
                    var topRow = document.createElement('div');
                    topRow.className = 'research-item-top';

                    var link = document.createElement('a');
                    link.href = '/wiki/' + task.slug;
                    link.textContent = task.slug.replace(/-/g, ' ');
                    link.className = 'research-sidebar-link';
                    topRow.appendChild(link);

                    // Controls: reorder arrows + cancel
                    var controls = document.createElement('span');
                    controls.className = 'research-item-controls';

                    // Up/down arrows only for queued tasks
                    if (task.status === 'queued') {
                        var upBtn = document.createElement('button');
                        upBtn.className = 'research-ctrl-btn';
                        upBtn.textContent = '\u25B2';
                        upBtn.title = 'Increase priority';
                        upBtn.addEventListener('click', (function(id) {
                            return function(e) { e.preventDefault(); reorderTask(id, 'up'); };
                        })(task.id));
                        controls.appendChild(upBtn);

                        var downBtn = document.createElement('button');
                        downBtn.className = 'research-ctrl-btn';
                        downBtn.textContent = '\u25BC';
                        downBtn.title = 'Decrease priority';
                        downBtn.addEventListener('click', (function(id) {
                            return function(e) { e.preventDefault(); reorderTask(id, 'down'); };
                        })(task.id));
                        controls.appendChild(downBtn);
                    }

                    // Cancel button for all active tasks
                    var cancelBtn = document.createElement('button');
                    cancelBtn.className = 'research-ctrl-btn research-cancel-btn';
                    cancelBtn.textContent = '\u2715';
                    cancelBtn.title = 'Cancel';
                    cancelBtn.addEventListener('click', (function(id, slug) {
                        return function(e) {
                            e.preventDefault();
                            if (confirm('Cancel research for "' + slug.replace(/-/g, ' ') + '"?')) {
                                cancelTask(id);
                            }
                        };
                    })(task.id, task.slug));
                    controls.appendChild(cancelBtn);

                    topRow.appendChild(controls);
                    item.appendChild(topRow);

                    // Status badge + priority
                    var badgeRow = document.createElement('div');
                    badgeRow.className = 'research-item-badges';

                    var badge = document.createElement('span');
                    badge.className = 'status-badge status-' + (task.status || 'queued');
                    badge.textContent = task.status || 'queued';
                    badgeRow.appendChild(badge);

                    if (task.status === 'queued' && task.priority && task.priority !== 'medium' && ['high', 'low'].indexOf(task.priority) !== -1) {
                        var priBadge = document.createElement('span');
                        priBadge.className = 'priority-badge priority-' + task.priority;
                        priBadge.textContent = task.priority;
                        badgeRow.appendChild(priBadge);
                    }

                    item.appendChild(badgeRow);

                    // Progress bar + stage for researching tasks
                    if (task.status === 'researching') {
                        var stageOrder = ['searching', 'analyzing', 'writing', 'indexing'];
                        var stage = task.progress && task.progress.stage;
                        var stageIdx = stage ? stageOrder.indexOf(stage) : -1;
                        var pct = stageIdx >= 0 ? Math.round(((stageIdx + 1) / stageOrder.length) * 100) : 10;

                        var progressRow = document.createElement('div');
                        progressRow.className = 'research-sidebar-progress';

                        var bar = document.createElement('div');
                        bar.className = 'research-progress-bar';
                        var fill = document.createElement('div');
                        fill.className = 'research-progress-fill';
                        fill.style.width = pct + '%';
                        bar.appendChild(fill);
                        progressRow.appendChild(bar);

                        var info = document.createElement('span');
                        info.className = 'research-sidebar-stage';
                        var label = stage ? stage : 'starting';
                        if (task.elapsed) {
                            var m = Math.floor(task.elapsed / 60);
                            var s = task.elapsed % 60;
                            label += ' (' + (m > 0 ? m + 'm ' : '') + s + 's)';
                        }
                        info.textContent = label;
                        progressRow.appendChild(info);

                        item.appendChild(progressRow);
                    }

                    body.appendChild(item);
                });
            } catch (e) {
                console.log('Research sidebar refresh failed:', e);
            }
        }

        refresh();
        setInterval(refresh, 3000);
    }

    // ========================================================================
    // Initialize
    // ========================================================================

    console.log('LLM Wiki page script loaded');

    // ========================================================================
    // Global Keyboard Shortcuts
    // ========================================================================

    document.addEventListener('keydown', function(e) {
        // Skip if user is typing in an input/textarea
        var tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) {
            return;
        }

        // "/" to focus search
        if (e.key === '/' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            var si = document.getElementById('search-input');
            if (si) { si.focus(); si.select(); }
        }

        // "?" to show shortcuts help (future: could show a modal)
    });

    // Make external links open in new tabs and add visual indicator
    function initExternalLinks() {
        document.querySelectorAll('.wiki-main a[href^="http"]').forEach(function(link) {
            // Skip wiki-internal links
            if (link.hostname === window.location.hostname) return;
            link.setAttribute('target', '_blank');
            link.setAttribute('rel', 'noopener noreferrer');
            if (!link.classList.contains('wiki-link')) {
                link.classList.add('external-link');
            }
        });
    }

    // Add error handling for broken images
    function initImageFallbacks() {
        document.querySelectorAll('.wiki-main img').forEach(function(img) {
            img.addEventListener('error', function() {
                this.style.display = 'none';
            });
        });
    }

    // Wait for DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            initDashboardRefresh();
            initSuggestions();
            initAnnotations();
            initResearchSidebar();
            initExternalLinks();
            initImageFallbacks();
        });
    } else {
        initDashboardRefresh();
        initSuggestions();
        initAnnotations();
        initResearchSidebar();
        initExternalLinks();
        initImageFallbacks();
    }
})();
