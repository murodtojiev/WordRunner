/* =====================================================================
   WORDRUNNER — Admin panel logic
   ===================================================================== */
(function () {
  'use strict';

  const CATEGORIES = window.ADMIN_CATEGORIES || [];
  const CAT_LABEL = {
    synonym: 'Sinonim', antonym: 'Antonim', vocabulary: "Lug'at ma'nosi",
    grammar: 'Grammatika', plural: "Ko'plik", spelling: 'Imlo', idiom: 'Ibora',
  };
  const catLabel = (c) => CAT_LABEL[c] || c;
  const LETTERS = ['A', 'B', 'C', 'D'];

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  async function api(method, url, body) {
    const opts = { method, headers: { 'X-Admin-Request': '1' }, credentials: 'same-origin' };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch(url, opts); }
    catch (e) { throw new Error("Server bilan aloqa yo'q"); }
    let data = {};
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    if (!res.ok) {
      if (res.status === 403 || res.status === 404) {
        throw new Error("Ruxsat yo'q yoki sessiya tugagan. Qayta kiring.");
      }
      throw new Error(data.error || 'Xatolik yuz berdi (' + res.status + ')');
    }
    return data;
  }

  function toast(msg, isErr) {
    const el = document.createElement('div');
    el.className = 'toast' + (isErr ? ' err' : '');
    el.textContent = msg;
    $('toasts').appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const diff = (Date.now() - new Date(iso).getTime()) / 1000;
    if (diff < 60) return 'hozirgina';
    if (diff < 3600) return Math.floor(diff / 60) + ' daqiqa oldin';
    if (diff < 86400) return Math.floor(diff / 3600) + ' soat oldin';
    if (diff < 86400 * 30) return Math.floor(diff / 86400) + ' kun oldin';
    return new Date(iso).toLocaleDateString('uz-UZ');
  }

  function renderPager(el, page, pages, onGo) {
    el.innerHTML = '';
    if (pages <= 1) { el.hidden = true; return; }
    el.hidden = false;
    const add = (label, p, opts = {}) => {
      const b = document.createElement('button');
      b.textContent = label;
      if (opts.disabled) b.disabled = true;
      if (opts.active) b.classList.add('active');
      b.addEventListener('click', () => onGo(p));
      el.appendChild(b);
    };
    add('‹', page - 1, { disabled: page <= 1 });
    const win = new Set([1, pages, page - 1, page, page + 1]);
    let last = 0;
    [...win].filter((p) => p >= 1 && p <= pages).sort((a, b) => a - b).forEach((p) => {
      if (p - last > 1) { const s = document.createElement('span'); s.textContent = '…'; s.className = 'muted'; el.appendChild(s); }
      add(String(p), p, { active: p === page });
      last = p;
    });
    add('›', page + 1, { disabled: page >= pages });
  }

  // ------------------------------------------------------------------
  // Modal
  // ------------------------------------------------------------------
  const modal = $('modal');
  function openModal({ title, body, buttons }) {
    $('modalTitle').textContent = title;
    const bodyEl = $('modalBody');
    bodyEl.innerHTML = '';
    if (typeof body === 'string') bodyEl.innerHTML = body; else bodyEl.appendChild(body);
    const foot = $('modalFoot');
    foot.innerHTML = '';
    buttons.forEach((b) => {
      const btn = document.createElement('button');
      btn.className = 'btn ' + (b.cls || '');
      btn.textContent = b.label;
      btn.addEventListener('click', () => b.onClick(btn));
      foot.appendChild(btn);
    });
    modal.hidden = false;
    const first = bodyEl.querySelector('input[type=text], input[type=number], textarea, select');
    if (first) first.focus();
  }
  function closeModal() { modal.hidden = true; }
  $('modalClose').addEventListener('click', closeModal);
  modal.addEventListener('mousedown', (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !modal.hidden) closeModal(); });

  function confirmBox({ title, message, confirmLabel, extraHtml, onConfirm }) {
    openModal({
      title,
      body: '<p>' + message + '</p>' + (extraHtml || '') + '<div class="form-error" id="cfErr"></div>',
      buttons: [
        { label: 'Bekor qilish', onClick: closeModal },
        {
          label: confirmLabel || 'Tasdiqlash', cls: 'danger',
          onClick: async (btn) => {
            btn.disabled = true;
            try { await onConfirm(); closeModal(); }
            catch (e) { $('cfErr').textContent = e.message; btn.disabled = false; }
          },
        },
      ],
    });
  }

  // ------------------------------------------------------------------
  // Router + sidebar
  // ------------------------------------------------------------------
  const PAGES = {
    dashboard: { title: 'Dashboard', load: loadDashboard },
    users: { title: 'Foydalanuvchilar', load: loadUsers },
    questions: { title: 'English Runner savollari', load: loadQuestions },
    vocab: { title: "So'z topish lug'ati", load: loadVocab },
  };

  function route() {
    const name = (location.hash || '#dashboard').slice(1);
    const key = PAGES[name] ? name : 'dashboard';
    document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === 'page-' + key));
    document.querySelectorAll('.side-link[data-page]').forEach((a) => a.classList.toggle('active', a.dataset.page === key));
    $('pageTitle').textContent = PAGES[key].title;
    $('topbarActions').innerHTML = '';
    if (key === 'questions') addTopButton('+ Yangi savol', () => openQuestionForm());
    if (key === 'vocab') addTopButton("+ Yangi so'z", () => openVocabForm());
    if (key === 'dashboard' || key === 'users') addTopButton('↻ Yangilash', () => PAGES[key].load());
    closeSidebar();
    PAGES[key].load();
  }
  function addTopButton(label, fn) {
    const b = document.createElement('button');
    b.className = 'btn ' + (label.startsWith('+') ? 'primary' : '');
    b.textContent = label;
    b.addEventListener('click', fn);
    $('topbarActions').appendChild(b);
  }
  window.addEventListener('hashchange', route);

  const sidebar = $('sidebar'), scrim = $('scrim');
  function closeSidebar() { sidebar.classList.remove('open'); scrim.classList.remove('show'); }
  $('burger').addEventListener('click', () => { sidebar.classList.add('open'); scrim.classList.add('show'); });
  scrim.addEventListener('click', closeSidebar);

  // ------------------------------------------------------------------
  // 1. Dashboard
  // ------------------------------------------------------------------
  let dashData = null, playsGame = 'runner';

  async function loadDashboard() {
    try {
      dashData = await api('GET', '/admin/api/stats');
    } catch (e) { toast(e.message, true); return; }
    const d = dashData;
    const mp = d.most_played.overall;
    const mpText = mp ? (mp.level + '-bosqich') : '—';
    const mpSub = mp ? (mp.game === 'runner' ? 'English Runner' : "So'z topish") + ' · ' + mp.plays + ' marta' : "Hali ma'lumot yo'q";
    $('statGrid').innerHTML = [
      statCard('Jami foydalanuvchilar', d.total_users, d.active_week + ' ta oxirgi 7 kunda faol', 'var(--cyan)'),
      statCard('Bugungi faol', d.active_today, "Toshkent vaqti bo'yicha", 'var(--green)'),
      statCard("O'rtacha ball", d.avg_score, 'Jami ball / o\'yinchi', 'var(--amber)'),
      statCard("Eng ko'p o'ynalgan", mpText, mpSub, 'var(--purple)'),
    ].join('');
    renderPlays();
    renderLevels(d.users_by_level);
    renderTop(d.top_players);
  }
  function statCard(label, value, sub, accent) {
    return '<div class="stat" style="--accent:' + accent + '"><div class="label">' + esc(label) + '</div>' +
      '<div class="value">' + esc(value) + '</div><div class="sub">' + esc(sub) + '</div></div>';
  }
  function renderBars(el, rows, emptyMsg) {
    const max = Math.max(1, ...rows.map((r) => r.value));
    const top = Math.max(...rows.map((r) => r.value));
    if (!rows.length || top === 0) { el.innerHTML = '<div class="empty">' + emptyMsg + '</div>'; return; }
    el.innerHTML = rows.map((r) =>
      '<div class="bar-row' + (r.value === top ? ' top' : '') + '"><span class="name">' + esc(r.name) + '</span>' +
      '<div class="bar-track"><div class="bar-fill" style="width:' + (r.value / max * 100) + '%"></div></div>' +
      '<span class="val">' + r.value + '</span></div>').join('');
  }
  function renderPlays() {
    if (!dashData) return;
    const levels = playsGame === 'runner' ? 10 : 5;
    const data = dashData.plays_by_level[playsGame] || {};
    const rows = [];
    for (let l = 1; l <= levels; l++) rows.push({ name: l + '-bosqich', value: data[l] || 0 });
    renderBars($('playsChart'), rows, "Hali hech kim o'ynamagan");
  }
  function renderLevels(list) {
    const map = {};
    list.forEach((r) => { map[r.level] = r.count; });
    const rows = [];
    for (let l = 1; l <= 10; l++) rows.push({ name: l + '-bosqich', value: map[l] || 0 });
    renderBars($('levelsChart'), rows, "O'yinchilar yo'q");
  }
  function renderTop(list) {
    const medals = ['🥇', '🥈', '🥉', '4', '5'];
    if (!list.length) { $('topPlayers').innerHTML = '<div class="empty">Hali o\'yinchilar yo\'q</div>'; return; }
    $('topPlayers').innerHTML = list.map((p, i) =>
      '<div class="top-item"><div class="medal">' + medals[i] + '</div>' +
      (p.picture ? '<img src="' + esc(p.picture) + '" alt="" referrerpolicy="no-referrer">' : '<div class="ph"></div>') +
      '<div class="n">' + esc(p.name) + '</div><div class="s">⭐ ' + p.total_score + '</div></div>').join('');
  }
  $('playsSeg').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-game]');
    if (!b) return;
    playsGame = b.dataset.game;
    $('playsSeg').querySelectorAll('button').forEach((x) => x.classList.toggle('active', x === b));
    renderPlays();
  });

  // ------------------------------------------------------------------
  // 2. Users
  // ------------------------------------------------------------------
  const userState = { page: 1, q: '', sort: 'score', maxLevel: 10 };

  async function loadUsers() {
    try {
      const qs = new URLSearchParams({ page: userState.page, q: userState.q, sort: userState.sort });
      const d = await api('GET', '/admin/api/users?' + qs);
      userState.maxLevel = d.max_level;
      $('userCount').textContent = 'Jami: ' + d.total;
      $('userRows').innerHTML = d.users.length ? d.users.map(userRow).join('') :
        '<tr><td colspan="6"><div class="empty">Hech narsa topilmadi</div></td></tr>';
      renderPager($('userPager'), d.page, d.pages, (p) => { userState.page = p; loadUsers(); });
      renderBlocked(d.blocked);
    } catch (e) { toast(e.message, true); }
  }
  function userRow(u) {
    return '<tr data-id="' + u.id + '"><td><div class="user-cell">' +
      (u.picture ? '<img src="' + esc(u.picture) + '" alt="" referrerpolicy="no-referrer">' : '<div class="ph"></div>') +
      '<span class="nm">' + esc(u.name || '—') + '</span>' + (u.is_admin ? '<span class="badge admin">ADMIN</span>' : '') +
      '</div></td><td class="muted">' + esc(u.email || '—') + '</td>' +
      '<td class="num"><strong>' + u.total_score + '</strong></td>' +
      '<td class="num"><span class="badge lvl">Lvl ' + u.current_level + '</span></td>' +
      '<td class="muted small">' + esc(timeAgo(u.last_active)) + '</td>' +
      '<td class="actions">' +
      '<button class="btn sm" data-act="level">Bosqich</button>' +
      '<button class="btn sm" data-act="reset">Ball → 0</button>' +
      (u.is_admin ? '' : '<button class="btn sm danger" data-act="delete">O\'chirish</button>') +
      '</td></tr>';
  }
  function renderBlocked(list) {
    $('blockedCard').hidden = !list.length;
    $('blockedList').innerHTML = list.map((b) =>
      '<span class="chip">' + esc(b.email) + '<button data-email="' + esc(b.email) + '">Blokdan chiqarish</button></span>').join('');
  }
  $('blockedList').addEventListener('click', async (e) => {
    const b = e.target.closest('button[data-email]');
    if (!b) return;
    try {
      await api('DELETE', '/admin/api/blocked/' + encodeURIComponent(b.dataset.email));
      toast('Blokdan chiqarildi'); loadUsers();
    } catch (err) { toast(err.message, true); }
  });

  $('userSearch').addEventListener('input', debounce((e) => { userState.q = e.target.value.trim(); userState.page = 1; loadUsers(); }, 300));
  $('userSort').addEventListener('change', (e) => { userState.sort = e.target.value; userState.page = 1; loadUsers(); });

  $('userRows').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const tr = btn.closest('tr');
    const id = tr.dataset.id;
    const name = tr.querySelector('.nm').textContent;
    const act = btn.dataset.act;

    if (act === 'reset') {
      confirmBox({
        title: 'Ballni nolga tushirish',
        message: '<strong>' + esc(name) + '</strong> ning umumiy balli <strong>0</strong> ga tushiriladi. Davom etamizmi?',
        confirmLabel: 'Nolga tushirish',
        onConfirm: async () => { await api('PATCH', '/admin/api/users/' + id, { action: 'reset_score' }); toast('Ball nolga tushirildi'); loadUsers(); },
      });
    } else if (act === 'delete') {
      confirmBox({
        title: "O'yinchini o'chirish",
        message: '<strong>' + esc(name) + '</strong> butunlay o\'chiriladi (ball va bosqich ma\'lumotlari yo\'qoladi).',
        confirmLabel: "O'chirish",
        extraHtml: '<label class="check"><input type="checkbox" id="blockChk"> Qayta kirishni ham taqiqlash (email bloklanadi)</label>',
        onConfirm: async () => {
          const block = $('blockChk').checked ? '1' : '0';
          await api('DELETE', '/admin/api/users/' + id + '?block=' + block);
          toast("O'yinchi o'chirildi"); loadUsers();
        },
      });
    } else if (act === 'level') {
      const cur = parseInt(tr.querySelector('.badge.lvl').textContent.replace(/\D/g, ''), 10) || 1;
      let opts = '';
      for (let l = 1; l <= userState.maxLevel; l++) opts += '<option value="' + l + '"' + (l === cur ? ' selected' : '') + '>' + l + '-bosqich</option>';
      openModal({
        title: "Bosqichni o'zgartirish",
        body: '<p><strong>' + esc(name) + '</strong></p><div class="field"><label>Yangi bosqich</label><select id="lvlSel">' + opts + '</select></div>' +
          '<div class="form-error" id="cfErr"></div>',
        buttons: [
          { label: 'Bekor qilish', onClick: closeModal },
          {
            label: 'Saqlash', cls: 'primary',
            onClick: async (btn2) => {
              btn2.disabled = true;
              try {
                await api('PATCH', '/admin/api/users/' + id, { action: 'set_level', level: parseInt($('lvlSel').value, 10) });
                closeModal(); toast("Bosqich o'zgartirildi"); loadUsers();
              } catch (err) { $('cfErr').textContent = err.message; btn2.disabled = false; }
            },
          },
        ],
      });
    }
  });

  // ------------------------------------------------------------------
  // 3. Questions
  // ------------------------------------------------------------------
  const qState = { page: 1, q: '', category: '' };

  function initCategorySelect() {
    $('qCategory').innerHTML = '<option value="">Barcha kategoriyalar</option>' +
      CATEGORIES.map((c) => '<option value="' + c + '">' + esc(catLabel(c)) + '</option>').join('');
  }

  async function loadQuestions() {
    try {
      const qs = new URLSearchParams({ page: qState.page, q: qState.q, category: qState.category });
      const d = await api('GET', '/admin/api/questions?' + qs);
      $('qCount').textContent = 'Topildi: ' + d.total + ' / ' + d.all_total;
      window.__questions = {};
      d.questions.forEach((q) => { window.__questions[q.id] = q; });
      $('qRows').innerHTML = d.questions.length ? d.questions.map(questionRow).join('') :
        '<tr><td colspan="4"><div class="empty">Savollar topilmadi</div></td></tr>';
      renderPager($('qPager'), d.page, d.pages, (p) => { qState.page = p; loadQuestions(); });
    } catch (e) { toast(e.message, true); }
  }
  function questionRow(q) {
    return '<tr data-id="' + q.id + '"><td class="q-text">' + esc(q.question) + '</td>' +
      '<td><span class="badge cat">' + esc(catLabel(q.category)) + '</span> ' +
      '<span class="badge lvl">' + esc((DIFFS[q.difficulty] || '').split(' ')[0] || '—') + '</span></td>' +
      '<td><div class="opts">' + q.options.map((o, i) =>
        '<span class="opt' + (i === q.answer ? ' correct' : '') + '">' + LETTERS[i] + ') ' + esc(o) + '</span>').join('') + '</div></td>' +
      '<td class="actions"><button class="btn sm" data-act="edit">Tahrirlash</button>' +
      '<button class="btn sm danger" data-act="delete">O\'chirish</button></td></tr>';
  }
  $('qSearch').addEventListener('input', debounce((e) => { qState.q = e.target.value.trim(); qState.page = 1; loadQuestions(); }, 300));
  $('qCategory').addEventListener('change', (e) => { qState.category = e.target.value; qState.page = 1; loadQuestions(); });

  $('qRows').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.closest('tr').dataset.id;
    const q = (window.__questions || {})[id];
    if (!q) return;
    if (btn.dataset.act === 'edit') openQuestionForm(q);
    else confirmBox({
      title: "Savolni o'chirish",
      message: 'Bu savol o\'chiriladi:<br><em>' + esc(q.question) + '</em>',
      confirmLabel: "O'chirish",
      onConfirm: async () => { await api('DELETE', '/admin/api/questions/' + id); toast("Savol o'chirildi"); loadQuestions(); },
    });
  });

  const DIFFS = { 1: 'A1 · Boshlang\'ich', 2: 'A2 · Elementar', 3: 'B1 · O\'rta', 4: 'B2 · O\'rta-yuqori' };

  function openQuestionForm(q) {
    const isEdit = !!q;
    const data = q || { question: '', options: ['', '', '', ''], answer: 0, category: 'grammar', difficulty: 2 };
    const wrap = document.createElement('div');
    wrap.style.display = 'contents';
    wrap.innerHTML =
      '<div class="field"><label>Savol matni</label><input type="text" id="fQ" maxlength="300" placeholder="Masalan: Choose the synonym of “HAPPY”"></div>' +
      '<div class="field"><label>Kategoriya</label><select id="fCat">' +
      CATEGORIES.map((c) => '<option value="' + c + '">' + esc(catLabel(c)) + '</option>').join('') + '</select></div>' +
      '<div class="field"><label>Daraja</label><select id="fDiff">' +
      [1, 2, 3, 4].map((d) => '<option value="' + d + '">' + esc(DIFFS[d]) + '</option>').join('') + '</select></div>' +
      '<div class="field"><label>Variantlar (to\'g\'ri javobni belgilang)</label>' +
      [0, 1, 2, 3].map((i) => '<div class="opt-input"><input type="radio" name="fAns" value="' + i + '" title="To\'g\'ri javob">' +
        '<input type="text" class="fOpt" maxlength="100" placeholder="' + LETTERS[i] + ' varianti"></div>').join('') +
      '<div class="hint">Yashil tugma — to\'g\'ri javob. Variantlar bir-biridan farq qilsin.</div></div>' +
      '<div class="form-error" id="fErr"></div>';
    openModal({
      title: isEdit ? 'Savolni tahrirlash' : "Yangi savol qo'shish",
      body: wrap,
      buttons: [
        { label: 'Bekor qilish', onClick: closeModal },
        {
          label: 'Saqlash', cls: 'primary',
          onClick: async (btn) => {
            const payload = {
              question: $('fQ').value.trim(),
              category: $('fCat').value,
              difficulty: parseInt($('fDiff').value, 10),
              options: [...document.querySelectorAll('.fOpt')].map((i) => i.value.trim()),
              answer: parseInt((document.querySelector('input[name=fAns]:checked') || {}).value, 10),
            };
            if (Number.isNaN(payload.answer)) { $('fErr').textContent = "To'g'ri javobni belgilang"; return; }
            btn.disabled = true;
            try {
              if (isEdit) await api('PUT', '/admin/api/questions/' + q.id, payload);
              else await api('POST', '/admin/api/questions', payload);
              closeModal(); toast(isEdit ? 'Savol yangilandi' : "Savol qo'shildi"); loadQuestions();
            } catch (err) { $('fErr').textContent = err.message; btn.disabled = false; }
          },
        },
      ],
    });
    $('fQ').value = data.question;
    $('fCat').value = data.category;
    $('fDiff').value = data.difficulty || 2;
    document.querySelectorAll('.fOpt').forEach((i, idx) => { i.value = data.options[idx] || ''; });
    document.querySelectorAll('input[name=fAns]')[data.answer].checked = true;
  }

  // ------------------------------------------------------------------
  // 4. Vocabulary
  // ------------------------------------------------------------------
  const vState = { page: 1, q: '', level: '' };

  async function loadVocab() {
    try {
      const qs = new URLSearchParams({ page: vState.page, q: vState.q, level: vState.level });
      const d = await api('GET', '/admin/api/vocab?' + qs);
      $('vCount').textContent = 'Topildi: ' + d.total + ' / ' + d.all_total;
      window.__vocab = {};
      d.words.forEach((w) => { window.__vocab[w.id] = w; });
      renderLevelTabs(d.level_counts, d.all_total);
      $('vRows').innerHTML = d.words.length ? d.words.map((w) =>
        '<tr data-id="' + w.id + '"><td><strong>' + esc(w.uz_word) + '</strong></td><td>' + esc(w.en_translation) + '</td>' +
        '<td class="num"><span class="badge lvl">Lvl ' + w.level + '</span></td>' +
        '<td class="actions"><button class="btn sm" data-act="edit">Tahrirlash</button>' +
        '<button class="btn sm danger" data-act="delete">O\'chirish</button></td></tr>').join('') :
        '<tr><td colspan="4"><div class="empty">So\'zlar topilmadi</div></td></tr>';
      renderPager($('vPager'), d.page, d.pages, (p) => { vState.page = p; loadVocab(); });
    } catch (e) { toast(e.message, true); }
  }
  function renderLevelTabs(counts, total) {
    let html = '<button data-level=""' + (vState.level === '' ? ' class="active"' : '') + '>Barchasi<span class="c">' + total + '</span></button>';
    for (let l = 1; l <= 5; l++) {
      html += '<button data-level="' + l + '"' + (String(vState.level) === String(l) ? ' class="active"' : '') + '>' +
        l + '-bosqich<span class="c">' + (counts[l] || 0) + '</span></button>';
    }
    $('vLevelTabs').innerHTML = html;
  }
  $('vLevelTabs').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-level]');
    if (!b) return;
    vState.level = b.dataset.level; vState.page = 1; loadVocab();
  });
  $('vSearch').addEventListener('input', debounce((e) => { vState.q = e.target.value.trim(); vState.page = 1; loadVocab(); }, 300));

  $('vRows').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.closest('tr').dataset.id;
    const w = (window.__vocab || {})[id];
    if (!w) return;
    if (btn.dataset.act === 'edit') openVocabForm(w);
    else confirmBox({
      title: "So'zni o'chirish",
      message: '<strong>' + esc(w.uz_word) + '</strong> → ' + esc(w.en_translation) + ' juftligi o\'chiriladi.',
      confirmLabel: "O'chirish",
      onConfirm: async () => { await api('DELETE', '/admin/api/vocab/' + id); toast("So'z o'chirildi"); loadVocab(); },
    });
  });

  function openVocabForm(w) {
    const isEdit = !!w;
    const defLevel = isEdit ? w.level : (vState.level ? parseInt(vState.level, 10) : 1);
    const wrap = document.createElement('div');
    wrap.style.display = 'contents';
    wrap.innerHTML =
      '<div class="field"><label>O\'zbekcha</label><input type="text" id="fUz" maxlength="150" placeholder="masalan: stol"></div>' +
      '<div class="field"><label>Inglizcha</label><input type="text" id="fEn" maxlength="150" placeholder="e.g. desk"></div>' +
      '<div class="field"><label>Bosqich</label><select id="fLvl">' +
      [1, 2, 3, 4, 5].map((l) => '<option value="' + l + '">' + l + '-bosqich</option>').join('') + '</select></div>' +
      '<div class="form-error" id="fErr"></div>';
    openModal({
      title: isEdit ? "So'zni tahrirlash" : "Yangi so'z juftligi",
      body: wrap,
      buttons: [
        { label: 'Bekor qilish', onClick: closeModal },
        {
          label: 'Saqlash', cls: 'primary',
          onClick: async (btn) => {
            const payload = { uz_word: $('fUz').value.trim(), en_translation: $('fEn').value.trim(), level: parseInt($('fLvl').value, 10) };
            btn.disabled = true;
            try {
              if (isEdit) await api('PUT', '/admin/api/vocab/' + w.id, payload);
              else await api('POST', '/admin/api/vocab', payload);
              closeModal(); toast(isEdit ? "So'z yangilandi" : "So'z qo'shildi"); loadVocab();
            } catch (err) { $('fErr').textContent = err.message; btn.disabled = false; }
          },
        },
      ],
    });
    $('fUz').value = isEdit ? w.uz_word : '';
    $('fEn').value = isEdit ? w.en_translation : '';
    $('fLvl').value = String(defLevel);
    // Enter submits
    modal.querySelectorAll('input[type=text]').forEach((i) =>
      i.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') $('modalFoot').lastElementChild.click(); }));
  }

  // ------------------------------------------------------------------
  initCategorySelect();
  route();
})();
