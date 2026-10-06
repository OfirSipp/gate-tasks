/* Gate Tasks front end -- board, people, dialogs, effects. */
'use strict';

const COLUMNS = ['To Do', 'In Progress', 'No Need', 'Completed'];
let me = null;          // signed-in user
let people = [];        // everyone (for assigning / switching boards)
let viewingId = null;   // whose board is on screen
let allTasks = [];

// ---------------------------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------------------------
function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

async function api(path, { method = 'GET', body } = {}) {
    const res = await fetch(path, {
        method,
        headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: 'same-origin',
    });
    if (res.status === 401 && path !== '/api/me/password') {
        window.location.href = '/login';
        throw new Error('Signed out');
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
        let msg = data && data.detail;
        if (Array.isArray(msg)) msg = msg.map(d => d.msg).join('; ');
        throw new Error(msg || `Request failed (${res.status})`);
    }
    return data;
}

let toastTimer = null;
function toast(message, isError = false) {
    const el = document.getElementById('toast');
    el.textContent = message;
    el.classList.toggle('error', isError);
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

function petDo(fn) {
    try { if (window.gatePet) fn(window.gatePet.core); } catch (e) { console.warn('pet:', e); }
}

function personName(id) {
    if (me && id === me.id) return 'Me';
    const p = people.find(x => x.id === id);
    return p ? p.display_name : 'Unknown';
}

function colourFor(text) {
    let h = 0;
    for (const ch of String(text)) h = (h * 31 + ch.charCodeAt(0)) % 360;
    return `hsl(${h}, 70%, 60%)`;
}

function initials(name) {
    return String(name).trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
}

function todayISO() {
    const d = new Date();
    return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

// ---------------------------------------------------------------------------------------------
// start-up
// ---------------------------------------------------------------------------------------------
async function init() {
    try {
        me = await api('/api/me');
        people = await api('/api/users');
    } catch (e) {
        return;
    }
    viewingId = me.id;
    renderHeader();
    renderPeopleSelects();
    await fetchTasks();
}

function renderHeader() {
    document.getElementById('user-name').textContent = me.display_name;
    document.getElementById('menu-name').textContent = me.display_name;
    document.getElementById('menu-role').textContent = `@${me.username} · ${me.is_admin ? 'Admin' : 'Member'}`;
    const avatar = document.getElementById('user-avatar');
    avatar.textContent = initials(me.display_name);
    avatar.style.background = colourFor(me.username);
    avatar.style.boxShadow = `0 0 10px ${colourFor(me.username)}`;
    document.querySelectorAll('.admin-only').forEach(el => { el.style.display = me.is_admin ? '' : 'none'; });
    document.getElementById('board-switch').style.display = me.is_admin && people.length > 1 ? '' : 'none';
}

function renderPeopleSelects() {
    const others = people.filter(p => p.id !== me.id);
    const owner = document.getElementById('task-owner');
    const current = owner.value ? Number(owner.value) : viewingId;
    owner.innerHTML = [`<option value="${me.id}">Me</option>`]
        .concat(others.map(p => `<option value="${p.id}">${esc(p.display_name)}</option>`)).join('');
    owner.value = String(people.some(p => p.id === current) ? current : viewingId);

    const board = document.getElementById('board-select');
    board.innerHTML = [`<option value="${me.id}">My board</option>`]
        .concat(others.map(p => `<option value="${p.id}">${esc(p.display_name)}</option>`)).join('');
    board.value = String(viewingId);
}

document.getElementById('board-select').addEventListener('change', (e) => switchBoard(Number(e.target.value)));

function switchBoard(id) {
    viewingId = id;
    document.getElementById('board-select').value = String(id);
    document.getElementById('task-owner').value = String(id);
    const banner = document.getElementById('viewing-banner');
    if (id !== me.id) {
        banner.innerHTML = `👀 You're viewing <strong>${esc(personName(id))}</strong>'s board. New tasks you add here go to them. <a href="#" style="color:#fff;" onclick="switchBoard(me.id); return false;">Back to my board</a>`;
        banner.classList.add('show');
    } else {
        banner.classList.remove('show');
    }
    resetForm();
    fetchTasks();
}

// ---------------------------------------------------------------------------------------------
// user menu, password, sign out
// ---------------------------------------------------------------------------------------------
function toggleUserMenu(e) {
    e.stopPropagation();
    document.getElementById('user-menu').classList.toggle('open');
}
document.addEventListener('click', () => document.getElementById('user-menu').classList.remove('open'));

function openModal(html, wide = false) {
    document.getElementById('user-menu').classList.remove('open');
    document.getElementById('expanded-card-body').classList.toggle('wide', wide);
    document.getElementById('expanded-inner-html').innerHTML = html;
    document.getElementById('expansion-modal').classList.add('active');
    petDo(p => p.startle());
}

function closeModal() {
    document.getElementById('expansion-modal').classList.remove('active');
}

function closeExpandedView(e) {
    if (!e || e.target.id === 'expansion-modal' || e.target.classList.contains('close-expanded')) closeModal();
}
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

function openChangePassword() {
    openModal(`
        <h2>🔑 Change password</h2>
        <form onsubmit="submitChangePassword(event)">
            <div class="field"><label>Current password</label><input type="password" id="pw-current" autocomplete="current-password" required></div>
            <div class="field"><label>New password (6+ characters)</label><input type="password" id="pw-new" minlength="6" autocomplete="new-password" required></div>
            <div class="field"><label>Repeat new password</label><input type="password" id="pw-new2" minlength="6" autocomplete="new-password" required></div>
            <div class="error" id="pw-error"></div>
            <div class="actions">
                <button type="button" class="btn-secondary" onclick="closeModal()">Cancel</button>
                <button type="submit" class="btn-success">Save password</button>
            </div>
        </form>`);
    setTimeout(() => document.getElementById('pw-current').focus(), 50);
}

async function submitChangePassword(e) {
    e.preventDefault();
    const err = document.getElementById('pw-error');
    const current = document.getElementById('pw-current').value;
    const next = document.getElementById('pw-new').value;
    if (next !== document.getElementById('pw-new2').value) { err.textContent = "The new passwords don't match."; return; }
    try {
        await api('/api/me/password', { method: 'POST', body: { current_password: current, new_password: next } });
        closeModal();
        toast('Password changed.');
    } catch (ex) {
        err.textContent = ex.message;
    }
}

async function logout() {
    try { await api('/api/logout', { method: 'POST' }); } catch (e) { /* ignore */ }
    window.location.href = '/login';
}

function confirmShutdown() {
    openModal(`
        <h2>⏻ Stop the server?</h2>
        <p class="sub">Gate Tasks will close for everyone using it. Start it again with Start_Gate_Tasks.bat.</p>
        <div class="actions">
            <button type="button" class="btn-secondary" onclick="closeModal()">Cancel</button>
            <button type="button" class="btn-danger" onclick="shutdownServer()">Stop server</button>
        </div>`);
}

async function shutdownServer() {
    try {
        await api('/api/admin/shutdown', { method: 'POST' });
        document.body.innerHTML = '<div style="display:flex;height:90vh;align-items:center;justify-content:center;flex-direction:column;gap:10px;color:#cbd5e1;font-family:Inter,sans-serif;"><h2>Gate Tasks has stopped.</h2><p style="color:#64748b;">You can close this tab.</p></div>';
    } catch (ex) {
        toast(ex.message, true);
    }
}

// ---------------------------------------------------------------------------------------------
// team management (admins)
// ---------------------------------------------------------------------------------------------
async function openTeam() {
    try { people = await api('/api/users'); } catch (ex) { toast(ex.message, true); return; }
    renderPeopleSelects();
    renderHeader();
    const rows = people.map(p => {
        const total = p.task_count || 0;
        const done = p.done_count || 0;
        const pct = total ? Math.round(done / total * 100) : 0;
        const self = p.id === me.id;
        return `
            <tr>
                <td><div style="display:flex;align-items:center;gap:8px;">
                    <div class="avatar" style="flex-shrink:0;width:28px;height:28px;font-size:9px;background:${colourFor(p.username)}">${esc(initials(p.display_name))}</div>
                    <div style="white-space:nowrap;"><div style="font-weight:600;color:#f1f5f9;">${esc(p.display_name)}${self ? ' (you)' : ''}</div>
                    <div style="font-size:11px;color:#64748b;">@${esc(p.username)}</div></div></div></td>
                <td>${p.is_admin ? '<span class="role">Admin</span>' : '<span style="color:#64748b;font-size:12px;">Member</span>'}</td>
                <td><span class="progress-mini"><div style="width:${pct}%"></div></span><span style="font-size:11px;color:#94a3b8;">${done}/${total}</span></td>
                <td style="text-align:right;white-space:nowrap;">
                    <button class="btn-secondary mini" onclick="closeModal(); switchBoard(${p.id})">Open board</button>
                    <button class="btn-secondary mini" onclick="openResetPassword(${p.id})">Reset password</button>
                    ${self ? '' : `<button class="btn-secondary mini" onclick="toggleAdmin(${p.id}, ${!p.is_admin})">${p.is_admin ? 'Remove admin' : 'Make admin'}</button>
                    <button class="btn-danger mini" onclick="deleteUser(${p.id}, this)">Delete</button>`}
                </td>
            </tr>`;
    }).join('');
    openModal(`
        <h2>👥 Team</h2>
        <p class="sub">Everyone gets a private board. Admins can open any board, manage people and stop the server.</p>
        <table class="team-table">
            <thead><tr><th>Person</th><th>Role</th><th>Progress</th><th></th></tr></thead>
            <tbody>${rows}</tbody>
        </table>
        <h3 style="font-size:14px;color:#cbd5e1;margin-bottom:12px;">Add a person</h3>
        <form onsubmit="submitNewUser(event)">
            <div class="row">
                <div class="field"><label>Full name</label><input id="nu-name" maxlength="60" required placeholder="Dana Levi"></div>
                <div class="field"><label>Username</label><input id="nu-username" maxlength="40" pattern="[A-Za-z0-9._\\-]+" required placeholder="dana"></div>
            </div>
            <div class="row">
                <div class="field"><label>Temporary password</label><input id="nu-password" type="text" minlength="6" required placeholder="6+ characters"></div>
                <div class="field"><label>&nbsp;</label><label class="check"><input type="checkbox" id="nu-admin"> Admin</label></div>
            </div>
            <div class="error" id="nu-error"></div>
            <div class="actions"><button type="submit" class="btn-success">Add person</button></div>
        </form>`, true);
}

async function submitNewUser(e) {
    e.preventDefault();
    const body = {
        display_name: document.getElementById('nu-name').value.trim(),
        username: document.getElementById('nu-username').value.trim(),
        password: document.getElementById('nu-password').value,
        is_admin: document.getElementById('nu-admin').checked,
    };
    try {
        await api('/api/users', { method: 'POST', body });
        toast(`${body.display_name} added. Their username is "${body.username}".`);
        openTeam();
    } catch (ex) {
        document.getElementById('nu-error').textContent = ex.message;
    }
}

function openResetPassword(id) {
    openModal(`
        <h2>Reset password</h2>
        <p class="sub">Set a new password for <strong>${esc(personName(id))}</strong>. They'll be signed out everywhere.</p>
        <form onsubmit="submitResetPassword(event, ${id})">
            <div class="field"><label>New password</label><input id="rp-password" type="text" minlength="6" required></div>
            <div class="error" id="rp-error"></div>
            <div class="actions">
                <button type="button" class="btn-secondary" onclick="openTeam()">Back</button>
                <button type="submit" class="btn-success">Set password</button>
            </div>
        </form>`);
}

async function submitResetPassword(e, id) {
    e.preventDefault();
    try {
        await api(`/api/users/${id}`, { method: 'PATCH', body: { password: document.getElementById('rp-password').value } });
        toast('Password updated.');
        openTeam();
    } catch (ex) {
        document.getElementById('rp-error').textContent = ex.message;
    }
}

async function toggleAdmin(id, makeAdmin) {
    try {
        await api(`/api/users/${id}`, { method: 'PATCH', body: { is_admin: makeAdmin } });
        openTeam();
    } catch (ex) { toast(ex.message, true); }
}

async function deleteUser(id, button) {
    if (!button.dataset.armed) {
        button.dataset.armed = '1';
        button.textContent = 'Click again — deletes their tasks too';
        setTimeout(() => { if (button.isConnected) { delete button.dataset.armed; button.textContent = 'Delete'; } }, 4000);
        return;
    }
    try {
        await api(`/api/users/${id}`, { method: 'DELETE' });
        if (viewingId === id) switchBoard(me.id);
        toast('Person removed.');
        openTeam();
    } catch (ex) { toast(ex.message, true); }
}

// ---------------------------------------------------------------------------------------------
// tasks
// ---------------------------------------------------------------------------------------------
async function fetchTasks() {
    try {
        allTasks = await api(`/api/tasks?user_id=${viewingId}`);
    } catch (e) {
        petDo(p => p.feel('sad', 4));
        toast(`Couldn't load tasks: ${e.message}`, true);
        return;
    }
    renderTasks();
}

async function handleFormSubmit(e) {
    e.preventDefault();
    const title = document.getElementById('task-title').value.trim();

    // Easter egg: red pill theme hijack
    if (title.toLowerCase() === 'take the red pill') {
        takeTheRedPill();
        resetForm();
        return;
    }

    const id = document.getElementById('task-id').value;
    const ownerId = Number(document.getElementById('task-owner').value) || viewingId;
    const payload = {
        title,
        category: document.getElementById('task-category').value.trim(),
        priority: document.getElementById('task-priority').value,
        deadline: document.getElementById('task-deadline').value,
        owner_id: ownerId,
    };
    try {
        if (id) {
            await api(`/api/tasks/${id}`, { method: 'PUT', body: payload });
            if (ownerId !== viewingId) toast(`Task moved to ${personName(ownerId)}'s board.`);
        } else {
            await api('/api/tasks', { method: 'POST', body: payload });
            if (ownerId !== viewingId) toast(`Task sent to ${personName(ownerId)}.`);
        }
    } catch (ex) {
        toast(ex.message, true);
        petDo(p => p.feel('angry', 3));
        return;
    }
    resetForm();
    fetchTasks();
}

async function updateTaskStatus(id, newStatus) {
    const task = allTasks.find(t => t.id === id);
    if (!task || task.status === newStatus) return;
    try {
        await api(`/api/tasks/${id}`, { method: 'PUT', body: { status: newStatus } });
    } catch (ex) { toast(ex.message, true); return; }
    if (newStatus === 'Completed') {
        if (task.priority === 'Pass') {
            triggerConfetti();
            petDo(p => p.cheer());
        } else if (task.priority === 'Fail') {
            triggerFailAnimation();
            petDo(p => p.feel('angry', 6));
        }
    }
    fetchTasks();
}

async function deleteTask(id) {
    try { await api(`/api/tasks/${id}`, { method: 'DELETE' }); } catch (ex) { toast(ex.message, true); return; }
    fetchTasks();
}

function editTask(id) {
    const task = allTasks.find(t => t.id === id);
    if (!task) return;
    document.getElementById('task-id').value = task.id;
    document.getElementById('task-title').value = task.title;
    document.getElementById('task-category').value = task.category;
    document.getElementById('task-priority').value = task.priority;
    document.getElementById('task-deadline').value = task.deadline;
    document.getElementById('task-owner').value = String(task.owner_id);
    document.getElementById('submit-btn').innerText = 'Save Task';
    document.getElementById('submit-btn').className = 'btn-success';
    document.getElementById('cancel-btn').style.display = 'block';
    document.getElementById('task-title').focus();
}

function resetForm() {
    document.getElementById('task-form').reset();
    document.getElementById('task-id').value = '';
    document.getElementById('task-owner').value = String(viewingId);
    document.getElementById('submit-btn').innerText = 'Add Task';
    document.getElementById('submit-btn').className = 'btn-primary';
    document.getElementById('cancel-btn').style.display = 'none';
}

// ---- notes ----------------------------------------------------------------------------------
function openTaskNotes(id) {
    const task = allTasks.find(t => t.id === id);
    if (!task) return;
    openModal(`
        <h2>📝 Task Notes & History</h2>
        <p style="font-size:15px; font-weight:600; color:#fff; margin-bottom:4px;">${esc(task.title)}</p>
        <p style="font-size:12px; color:#94a3b8; margin-bottom:20px;">Category: ${esc(task.category)} | Priority: ${esc(task.priority)}${task.created_by && task.created_by !== task.owner_id ? ` | From: ${esc(task.created_by_name)}` : ''}</p>
        <label style="font-size:12px; color:#cbd5e1; font-weight:500; display:block; margin-bottom:6px;">What happened / Notes log:</label>
        <textarea id="modal-task-notes" rows="6" maxlength="10000" style="resize:vertical; margin-bottom:20px;" placeholder="Record progress, test failures, or log details here...">${esc(task.notes)}</textarea>
        <div class="actions">
            <button type="button" class="btn-secondary" onclick="closeModal()">Cancel</button>
            <button type="button" class="btn-success" onclick="saveTaskNotes(${task.id})">Save Notes</button>
        </div>`);
}

async function saveTaskNotes(id) {
    const notes = document.getElementById('modal-task-notes').value;
    try { await api(`/api/tasks/${id}`, { method: 'PUT', body: { notes } }); } catch (ex) { toast(ex.message, true); return; }
    closeModal();
    fetchTasks();
}

// ---- deep-dives -----------------------------------------------------------------------------
function expandColumn(colName) {
    const colTasks = allTasks.filter(t => t.status === colName);
    const list = colTasks.length === 0 ? '<p style="color:#94a3b8;">No tasks in this column.</p>' : colTasks.map(t => `
        <div style="background:rgba(255,255,255,0.03); padding:12px; border-radius:10px; margin-bottom:8px; border:1px solid rgba(255,255,255,0.05);">
            <div style="font-weight:600; color:#f8fafc; font-size:14px;">${esc(t.title)}</div>
            <div style="font-size:11px; color:#94a3b8; margin-top:4px;">Category: ${esc(t.category)} | Priority: ${esc(t.priority)} | Deadline: ${t.deadline ? esc(t.deadline) : 'none'}</div>
            ${t.notes ? `<div style="font-size:11px; color:#cbd5e1; margin-top:6px; background:rgba(0,0,0,0.2); padding:6px; border-radius:6px; white-space:pre-wrap;">Notes: ${esc(t.notes)}</div>` : ''}
        </div>`).join('');
    openModal(`
        <h2>Column Deep-Dive: ${esc(colName)}</h2>
        <p style="color:#cbd5e1; font-size:13px; margin-bottom:16px;">Items currently in <strong>${esc(colName)}</strong>: ${colTasks.length}</p>
        <hr style="border:0; border-top:1px solid rgba(255,255,255,0.1); margin-bottom:16px;">
        <div style="max-height:400px; overflow-y:auto;">${list}</div>`);
}

function expandAnalytics() {
    const total = allTasks.length;
    const completed = allTasks.filter(t => t.status === 'Completed').length;
    const passCount = allTasks.filter(t => t.status === 'Completed' && t.priority === 'Pass').length;
    const today = todayISO();
    const overdue = allTasks.filter(t => t.deadline && t.deadline < today && !['Completed', 'No Need'].includes(t.status)).length;
    const categories = {};
    allTasks.forEach(t => { categories[t.category] = (categories[t.category] || 0) + 1; });
    const catHtml = Object.keys(categories).map(cat => `<div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:13px;"><span>${esc(cat)}</span><span style="font-weight:700; color:#818cf8;">${categories[cat]} tasks</span></div>`).join('');
    const tile = (label, value, colour) => `<div style="background:rgba(0,0,0,0.3); padding:16px; border-radius:12px;"><div style="font-size:12px; color:#94a3b8;">${label}</div><div style="font-size:24px; font-weight:800; color:${colour};">${value}</div></div>`;
    openModal(`
        <h2>🚀 Advanced Analytics — ${esc(viewingId === me.id ? 'My board' : personName(viewingId))}</h2>
        <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:16px; margin-bottom:20px;">
            ${tile('Total tasks', total, '#fff')}
            ${tile('Pass rate', `${completed > 0 ? Math.round((passCount / completed) * 100) : 0}%`, '#10b981')}
            ${tile('Overdue', overdue, overdue ? '#fda4af' : '#fff')}
        </div>
        <h3 style="font-size:14px; margin-bottom:10px; color:#cbd5e1;">Category Breakdown</h3>
        <div style="max-height:220px; overflow-y:auto; margin-bottom:20px;">${catHtml || '<p style="color:#94a3b8;">No categories logged yet.</p>'}</div>`);
}

// ---- rendering ------------------------------------------------------------------------------
function renderTasks() {
    const searchQuery = document.getElementById('search-box').value.toLowerCase();
    COLUMNS.forEach(col => { document.getElementById(`col-${col}`).innerHTML = ''; });

    const filtered = allTasks.filter(t =>
        t.title.toLowerCase().includes(searchQuery) ||
        t.category.toLowerCase().includes(searchQuery) ||
        (t.notes && t.notes.toLowerCase().includes(searchQuery)));
    document.getElementById('global-counter').innerText = `${filtered.length} / ${allTasks.length}`;

    const counts = { 'To Do': 0, 'In Progress': 0, 'No Need': 0, 'Completed': 0 };
    const today = todayISO();

    filtered.forEach(task => {
        if (!(task.status in counts)) return;
        counts[task.status]++;
        const isFaded = task.status === 'Completed' || task.status === 'No Need';
        const overdue = task.deadline && task.deadline < today && !isFaded;
        const fromSomeoneElse = task.created_by && task.created_by !== task.owner_id;

        const card = document.createElement('div');
        card.className = `task-card${isFaded ? ' faded' : ''}`;
        card.draggable = true;
        card.ondragstart = (e) => dragTask(e, task.id);
        card.ondragend = dragEndTask;
        card.ondblclick = () => openTaskNotes(task.id);
        card.title = 'Double-click to view/edit notes';
        card.innerHTML = `
            <div class="task-card-header">
                <span class="priority-badge priority-${esc(task.priority)}">${esc(task.priority)}</span>
                <div class="task-actions">
                    <button onclick="editTask(${task.id})" class="action-icon edit" title="Edit">✎</button>
                    <button onclick="deleteTask(${task.id})" class="action-icon delete" title="Delete">🗑</button>
                </div>
            </div>
            <div class="task-title" style="${isFaded ? 'text-decoration:line-through;color:#94a3b8;' : ''}">${esc(task.title)}</div>
            <div class="task-footer">
                <div style="display:flex; justify-content:space-between; align-items:center; gap:6px; flex-wrap:wrap;">
                    <span class="task-category">${esc(task.category)}</span>
                    ${task.notes ? '<span class="notes-badge">has notes 📝</span>' : ''}
                </div>
                ${fromSomeoneElse ? `<span class="assigned-badge">from ${esc(task.created_by_name || 'a colleague')}</span>` : ''}
                <div class="deadline${overdue ? ' overdue' : ''}" style="${overdue ? '' : 'color:#64748b;'}">🗓 ${task.deadline ? esc(task.deadline) : 'No deadline'}${overdue ? ' · overdue' : ''}</div>
            </div>`;
        document.getElementById(`col-${task.status}`).appendChild(card);
    });

    COLUMNS.forEach(col => { document.getElementById(`count-${col}`).innerText = counts[col] || 0; });
    drawCharts(counts, allTasks.length);
}

function toggleColumn(colName) {
    document.getElementById(`col-box-${colName}`).classList.toggle('collapsed');
}

// ---- drag & drop ----------------------------------------------------------------------------
let draggedColumn = null;
function dragColumn(e) {
    if (!e.target.classList.contains('kanban-column')) return;
    draggedColumn = e.target;
    e.dataTransfer.setData('text/column', e.target.id);
    setTimeout(() => e.target.classList.add('column-dragging'), 0);
}
function allowDropColumn(e) { e.preventDefault(); }
function dropColumn(e) {
    e.preventDefault();
    const board = document.getElementById('kanban-board');
    const targetCol = e.target.closest('.kanban-column');
    if (draggedColumn && targetCol && draggedColumn !== targetCol) {
        const cols = Array.from(board.children);
        if (cols.indexOf(draggedColumn) < cols.indexOf(targetCol)) board.insertBefore(draggedColumn, targetCol.nextSibling);
        else board.insertBefore(draggedColumn, targetCol);
    }
}
function dragEndColumn() {
    if (draggedColumn) draggedColumn.classList.remove('column-dragging');
    draggedColumn = null;
}
function allowDrop(e) { e.preventDefault(); }
function dragTask(e, id) {
    e.stopPropagation();
    e.dataTransfer.setData('text/plain', id);
    e.dataTransfer.effectAllowed = 'move';
    setTimeout(() => e.target.classList.add('dragging'), 0);
}
function dragEndTask(e) { e.target.classList.remove('dragging'); }
function dropTask(e, targetStatus) {
    e.preventDefault();
    e.stopPropagation();
    const id = parseInt(e.dataTransfer.getData('text/plain'), 10);
    if (!isNaN(id)) updateTaskStatus(id, targetStatus);
}

// ---------------------------------------------------------------------------------------------
// charts
// ---------------------------------------------------------------------------------------------
function drawCharts(counts, total) {
    const dCtx = document.getElementById('donutChart').getContext('2d');
    dCtx.clearRect(0, 0, 120, 120);
    if (total > 0) {
        const colors = { 'To Do': '#f43f5e', 'In Progress': '#f59e0b', 'No Need': '#8b5cf6', 'Completed': '#10b981' };
        let startAngle = -0.5 * Math.PI;
        for (const key in counts) {
            const slice = (counts[key] / total) * 2 * Math.PI;
            dCtx.beginPath();
            dCtx.arc(60, 60, 40, startAngle, startAngle + slice);
            dCtx.lineWidth = 14;
            dCtx.strokeStyle = colors[key];
            dCtx.stroke();
            startAngle += slice;
        }
    } else {
        dCtx.beginPath(); dCtx.arc(60, 60, 40, 0, 2 * Math.PI); dCtx.lineWidth = 14; dCtx.strokeStyle = '#1e293b'; dCtx.stroke();
    }

    const completedTasks = allTasks.filter(t => t.status === 'Completed');
    const passCount = completedTasks.filter(t => t.priority === 'Pass').length;
    const failCount = completedTasks.filter(t => t.priority === 'Fail').length;
    const totalPF = passCount + failCount;
    const passPercent = totalPF === 0 ? 0 : Math.round((passCount / totalPF) * 100);
    const failPercent = totalPF === 0 ? 0 : Math.round((failCount / totalPF) * 100);
    document.getElementById('pass-fail-box').innerHTML = `
        <div style="display: flex; justify-content: space-between; width: 100%; margin-bottom: 12px;">
            <span style="color:#10b981; font-weight:700; font-size:13px;">Pass: ${passCount} <span style="font-weight:400">(${passPercent}%)</span></span>
            <span style="color:#f43f5e; font-weight:700; font-size:13px;">Fail: ${failCount} <span style="font-weight:400">(${failPercent}%)</span></span>
        </div>
        <div style="width: 100%; height: 16px; background: rgba(244, 63, 94, 0.3); border-radius: 8px; overflow: hidden; display: flex;">
            <div style="width: ${passPercent}%; height: 100%; background: #10b981; transition: width 0.5s;"></div>
        </div>`;

    const completed = counts['Completed'] || 0;
    const rate = total === 0 ? 0 : Math.round((completed / total) * 100);
    document.getElementById('score-text').innerText = rate + '%';
    const gCtx = document.getElementById('gaugeChart').getContext('2d');
    gCtx.clearRect(0, 0, 200, 100);
    gCtx.shadowBlur = 0;
    gCtx.beginPath(); gCtx.arc(100, 80, 60, Math.PI, 2 * Math.PI);
    gCtx.lineWidth = 12; gCtx.strokeStyle = 'rgba(255,255,255,0.05)'; gCtx.stroke();
    if (rate > 0) {
        gCtx.beginPath(); gCtx.arc(100, 80, 60, Math.PI, Math.PI + (rate / 100) * Math.PI);
        const grad = gCtx.createLinearGradient(40, 80, 160, 80);
        grad.addColorStop(0, '#f43f5e'); grad.addColorStop(1, '#10b981');
        gCtx.strokeStyle = grad; gCtx.shadowColor = '#10b981'; gCtx.shadowBlur = 15; gCtx.stroke();
        gCtx.shadowBlur = 0;
    }
}

// ---------------------------------------------------------------------------------------------
// effects & easter eggs
// ---------------------------------------------------------------------------------------------
const spaceCanvas = document.getElementById('space-canvas');
const sCtx = spaceCanvas.getContext('2d');
function sizeSpace() { spaceCanvas.width = window.innerWidth; spaceCanvas.height = window.innerHeight; }
sizeSpace();
window.addEventListener('resize', sizeSpace);
let stars = Array.from({ length: 60 }, () => ({
    x: Math.random() * spaceCanvas.width, y: Math.random() * spaceCanvas.height,
    size: Math.random() * 2 + 0.5, v: Math.random() * 0.5 + 0.1, op: Math.random(), d: Math.random() > 0.5 ? 1 : -1,
}));
let skyMode = 'stars';
let matrixDrops = [];

function drawSky() {
    if (skyMode === 'matrix') {
        const fontSize = 14;
        sCtx.fillStyle = 'rgba(0, 0, 0, 0.05)';
        sCtx.fillRect(0, 0, spaceCanvas.width, spaceCanvas.height);
        sCtx.fillStyle = '#0F0';
        sCtx.font = fontSize + 'px monospace';
        for (let i = 0; i < matrixDrops.length; i++) {
            sCtx.fillText(String.fromCharCode(33 + Math.random() * 94), i * fontSize, matrixDrops[i] * fontSize);
            if (matrixDrops[i] * fontSize > spaceCanvas.height && Math.random() > 0.975) matrixDrops[i] = 0;
            matrixDrops[i]++;
        }
    } else {
        sCtx.clearRect(0, 0, spaceCanvas.width, spaceCanvas.height);
        stars.forEach(s => {
            sCtx.beginPath();
            sCtx.arc(s.x, s.y, s.size, 0, Math.PI * 2);
            sCtx.fillStyle = `rgba(165, 180, 252, ${s.op})`;
            sCtx.fill();
            s.y -= s.v;
            s.op += 0.01 * s.d;
            if (s.op > 1 || s.op < 0.1) s.d *= -1;
            if (s.y < 0) s.y = spaceCanvas.height;
        });
    }
    requestAnimationFrame(drawSky);
}
drawSky();

function takeTheRedPill() {
    document.body.style.background = '#000000';
    document.body.style.color = '#00ff00';
    document.body.style.fontFamily = 'monospace';
    document.querySelectorAll('.kanban-column').forEach(c => {
        c.style.background = 'rgba(0, 20, 0, 0.8)';
        c.style.borderColor = '#00ff00';
    });
    matrixDrops = Array(Math.floor(spaceCanvas.width / 14)).fill(1);
    skyMode = 'matrix';
}

function triggerConfetti() {
    const canvas = document.getElementById('confetti-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth; canvas.height = window.innerHeight;
    const particles = Array.from({ length: 60 }, () => ({
        x: canvas.width / 2, y: canvas.height / 2,
        vx: (Math.random() - 0.5) * 18, vy: (Math.random() - 0.7) * 18,
        size: Math.random() * 6 + 4, alpha: 1,
        color: ['#6366f1', '#06b6d4', '#10b981', '#f59e0b', '#ec4899'][Math.floor(Math.random() * 5)],
    }));
    (function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        let alive = false;
        particles.forEach(p => {
            p.x += p.vx; p.y += p.vy; p.vy += 0.4; p.alpha -= 0.02;
            if (p.alpha > 0) {
                alive = true; ctx.globalAlpha = p.alpha; ctx.fillStyle = p.color;
                ctx.shadowColor = p.color; ctx.shadowBlur = 10;
                ctx.fillRect(p.x, p.y, p.size, p.size); ctx.shadowBlur = 0;
            }
        });
        ctx.globalAlpha = 1;
        if (alive) requestAnimationFrame(animate); else ctx.clearRect(0, 0, canvas.width, canvas.height);
    })();
}

function triggerFailAnimation() {
    const canvas = document.getElementById('confetti-canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = window.innerWidth; canvas.height = window.innerHeight;
    const particles = Array.from({ length: 80 }, () => ({
        x: Math.random() * canvas.width, y: -20,
        vx: (Math.random() - 0.5) * 4, vy: Math.random() * 5 + 5,
        size: Math.random() * 6 + 4, alpha: 1,
        color: ['#f43f5e', '#9f1239', '#4c0519', '#3f3f46'][Math.floor(Math.random() * 4)],
    }));
    const board = document.querySelector('.dashboard');
    board.style.transition = 'transform 0.05s';
    [[0, -8], [50, 8], [100, -8], [150, 8], [200, 0]].forEach(([t, x]) => setTimeout(() => { board.style.transform = `translateX(${x}px)`; }, t));
    (function animate() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        let alive = false;
        particles.forEach(p => {
            p.x += p.vx; p.y += p.vy; p.alpha -= 0.01;
            if (p.alpha > 0) {
                alive = true; ctx.globalAlpha = p.alpha; ctx.fillStyle = p.color;
                ctx.shadowColor = p.color; ctx.shadowBlur = 10;
                ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2); ctx.fill(); ctx.shadowBlur = 0;
            }
        });
        ctx.globalAlpha = 1;
        if (alive) requestAnimationFrame(animate); else ctx.clearRect(0, 0, canvas.width, canvas.height);
    })();
}

// Konami-style code: ↑ ↑ ↓ ↓ ← →  -> the singularity
const konami = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
let konamiIndex = 0;
document.addEventListener('keydown', (e) => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    if (e.key === konami[konamiIndex]) {
        konamiIndex++;
        if (konamiIndex === konami.length) { triggerSingularity(); konamiIndex = 0; }
    } else {
        konamiIndex = e.key === konami[0] ? 1 : 0;
    }
});

function triggerSingularity() {
    const cards = document.querySelectorAll('.task-card');
    const centerX = window.innerWidth / 2;
    const centerY = window.innerHeight / 2;
    const bhInterval = setInterval(() => {
        sCtx.beginPath();
        sCtx.arc(centerX, centerY, 40 + Math.random() * 10, 0, Math.PI * 2);
        sCtx.fillStyle = 'rgba(0, 0, 0, 0.8)';
        sCtx.shadowColor = '#a855f7'; sCtx.shadowBlur = 50; sCtx.fill(); sCtx.shadowBlur = 0;
    }, 50);
    cards.forEach(card => {
        const rect = card.getBoundingClientRect();
        card.style.position = 'fixed';
        card.style.left = rect.left + 'px';
        card.style.top = rect.top + 'px';
        card.style.width = rect.width + 'px';
        card.style.transition = `all ${2 + Math.random()}s cubic-bezier(0.5, 0, 0.1, 1)`;
        card.style.transform = 'scale(0) rotate(720deg)';
        card.style.opacity = '0';
        setTimeout(() => { card.style.left = centerX + 'px'; card.style.top = centerY + 'px'; }, 50);
    });
    setTimeout(() => {
        clearInterval(bhInterval);
        cards.forEach(card => { card.style.cssText = ''; });
        triggerConfetti();
        petDo(p => p.cheer());
    }, 4000);
}

init();
