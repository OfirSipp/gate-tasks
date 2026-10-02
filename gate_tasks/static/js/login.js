/* Sign-in and first-run setup. */
'use strict';

(function stars() {
    const canvas = document.getElementById('space-canvas');
    const ctx = canvas.getContext('2d');
    const size = () => { canvas.width = window.innerWidth; canvas.height = window.innerHeight; };
    size();
    window.addEventListener('resize', size);
    const dots = Array.from({ length: 60 }, () => ({
        x: Math.random() * canvas.width, y: Math.random() * canvas.height,
        r: Math.random() * 2 + 0.5, v: Math.random() * 0.5 + 0.1, op: Math.random(), d: Math.random() > 0.5 ? 1 : -1,
    }));
    (function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (const s of dots) {
            ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(165, 180, 252, ${s.op})`; ctx.fill();
            s.y -= s.v; s.op += 0.01 * s.d;
            if (s.op > 1 || s.op < 0.1) s.d *= -1;
            if (s.y < 0) s.y = canvas.height;
        }
        requestAnimationFrame(draw);
    })();
})();

async function post(path, body) {
    const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty */ }
    if (!res.ok) {
        let msg = data && data.detail;
        if (Array.isArray(msg)) msg = msg.map(d => `${d.loc?.slice(-1)[0] ?? ''}: ${d.msg}`).join('; ');
        throw new Error(msg || `Request failed (${res.status})`);
    }
    return data;
}

async function start() {
    const status = await (await fetch('/api/auth/status')).json();
    if (status.user) { window.location.href = '/'; return; }
    const form = document.getElementById(status.needs_setup ? 'setup-form' : 'login-form');
    form.style.display = '';
    form.querySelector('input').focus();
    if (status.needs_setup) {
        document.getElementById('legacy-note').textContent = 'Tasks from an older Gate Tasks (tasks_db.json) will be moved onto your board.';
    }
}

document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = document.getElementById('li-error');
    err.textContent = '';
    try {
        await post('/api/login', {
            username: document.getElementById('li-username').value.trim(),
            password: document.getElementById('li-password').value,
        });
        window.location.href = '/';
    } catch (ex) {
        err.textContent = ex.message;
    }
});

document.getElementById('setup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const err = document.getElementById('su-error');
    const password = document.getElementById('su-password').value;
    if (password !== document.getElementById('su-password2').value) { err.textContent = "The passwords don't match."; return; }
    try {
        await post('/api/setup', {
            display_name: document.getElementById('su-name').value.trim(),
            username: document.getElementById('su-username').value.trim(),
            password,
        });
        window.location.href = '/';
    } catch (ex) {
        err.textContent = ex.message;
    }
});

start();
