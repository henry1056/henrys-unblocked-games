async function api(path, opts = {}) {
  const headers = {};
  if (opts.body && !(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { headers, credentials: 'same-origin', ...opts });
  let data = null;
  try { data = await res.json(); } catch (_) {}
  if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
  return data;
}

async function getMe() {
  try { return await api('/api/auth/me'); } catch (_) { return null; }
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
}

async function renderHeader(activePath) {
  const mount = document.getElementById('nav-links');
  if (!mount) return;
  const me = await getMe();
  mount.innerHTML = '';

  const link = (href, label) => {
    const a = el('a', { href, text: label });
    if (href === activePath) a.classList.add('active');
    return a;
  };

  mount.appendChild(link('/', 'Games'));
  mount.appendChild(link('/servers.html', 'Servers'));
  mount.appendChild(link('/chat.html', 'Chat'));
  mount.appendChild(link('/613tube.html', '📺 613 Tube'));
  mount.appendChild(link('/casino.html', '🎰 Casino'));

  if (me) {
    if (me.role === 'trusted' || me.role === 'admin') mount.appendChild(link('/upload.html', 'Upload'));
    if (me.role === 'admin') mount.appendChild(link('/admin.html', 'Admin'));
    if (me.role === 'admin') mount.appendChild(link('/terminal.html', '💻 Terminal'));

    // Coin balance display
    try {
      const bal = await api('/api/economy/balance');
      const coin = el('span', { class: 'pill coin-pill', text: `🪙 ${bal.coins.toLocaleString()}` });
      mount.appendChild(coin);
    } catch(_) {}

    mount.appendChild(link('/settings.html', '⚙ Settings'));

    const pillClass = me.role === 'admin' ? 'pill role-admin' : me.role === 'trusted' ? 'pill role-trusted' : 'pill';
    mount.appendChild(el('span', { class: pillClass, text: `${me.username} · ${me.role}` }));
    if (me.timedOutMinutes) mount.appendChild(el('span', { class: 'pill', text: `⏱ ${me.timedOutMinutes}m timeout` }));

    const logoutBtn = el('button', { text: 'Log out' });
    logoutBtn.addEventListener('click', async () => {
      await api('/api/auth/logout', { method: 'POST' });
      window.location.href = '/';
    });
    mount.appendChild(logoutBtn);
  } else {
    mount.appendChild(link('/login.html', 'Log in'));
    mount.appendChild(link('/register.html', 'Sign up'));
  }
}

function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// Auto-fill title from filename (strips extension, replaces - and _ with space, title-cases)
function titleFromFilename(filename) {
  return filename
    .replace(/\.[^/.]+$/, '')
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}
