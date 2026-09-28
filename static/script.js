(() => {
  'use strict';

  // =====================================================================
  // 0. Screen references
  // =====================================================================
  const mapScreen          = document.getElementById('mapScreen');
  const gameStage          = document.getElementById('gameStage');
  const levelPath          = document.getElementById('levelPath');
  const leaderboardList    = document.getElementById('leaderboardList');

  // =====================================================================
  // 1. DOM references (game)
  // =====================================================================
  const canvas        = document.getElementById('gameCanvas');
  const ctx           = canvas.getContext('2d');
  const heartsEl      = document.getElementById('hearts');
  const scoreValueEl  = document.getElementById('scoreValue');
  const levelValueEl  = document.getElementById('levelValue');
  const progressFill  = document.getElementById('progressBarFill');
  const progressText  = document.getElementById('progressText');
  const questionPanel = document.getElementById('questionPanel');
  const questionText  = document.getElementById('questionText');
  const optionsGrid   = document.getElementById('optionsGrid');
  const timerRingFill = document.getElementById('timerRingFill');
  const timerNumber   = document.getElementById('timerNumber');
  const gameOverScreen     = document.getElementById('gameOverScreen');
  const retryBtn           = document.getElementById('retryBtn');
  const backToMapBtnGO     = document.getElementById('backToMapBtnGO');
  const finalScoreEl       = document.getElementById('finalScore');
  const finalClearedEl     = document.getElementById('finalCleared');
  const hitFlash           = document.getElementById('hitFlash');
  const levelCompleteScreen = document.getElementById('levelCompleteScreen');
  const completedLevelNum   = document.getElementById('completedLevelNum');
  const levelScoreEarned    = document.getElementById('levelScoreEarned');
  const backToMapBtn        = document.getElementById('backToMapBtn');

  // =====================================================================
  // 2. Constants
  // =====================================================================
  const MAX_LIVES       = 3;
  const WORDS_PER_LEVEL = 15;
  const RUN_SPEED       = 260;
  const STOP_GAP        = 130;
  const SPAWN_GAP_MIN   = 480;
  const SPAWN_GAP_MAX   = 680;
  const QUEUE_TARGET    = 3;
  const ANSWER_TIME     = 5;
  const JUMP_DURATION   = 0.5;
  const HIT_DURATION    = 0.55;
  const RING_RADIUS     = 52;
  const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS;

  timerRingFill.style.strokeDasharray = RING_CIRCUMFERENCE.toFixed(1);

  // =====================================================================
  // 3. State
  // =====================================================================
  let currentLevel = parseInt(document.body.dataset.currentLevel || '1', 10);
  let playingLevel = 1;

  let W = 0, H = 0, groundY = 0, horizonY = 0, playerScreenX = 0;
  let lives, score, cleared, wordsCorrect;
  let obstacles = [];
  let player = null;
  let activeObstacle = null;
  let currentQuestion = null;
  let answerLocked = false;
  let running = false;
  let lastTime = 0;
  let groundOffset = 0;
  let clockSec = 0;
  let timerDeadline = 0;
  let timerRAF = null;
  let levelScore = 0; // score earned this level

  // =====================================================================
  // 4. Init: load leaderboard + attach level node listeners
  // =====================================================================
  initMap();
  fetchLeaderboard();

  function initMap() {
    const nodes = levelPath.querySelectorAll('.level-node');
    nodes.forEach(node => {
      const level = parseInt(node.dataset.level, 10);
      if (level <= currentLevel) {
        node.addEventListener('click', () => startLevel(level));
        node.style.cursor = 'pointer';
      }
    });
  }

  function refreshMapUI() {
    const nodes = levelPath.querySelectorAll('.level-node');
    nodes.forEach(node => {
      const level = parseInt(node.dataset.level, 10);
      // Remove old classes
      node.classList.remove('completed', 'current', 'locked');
      // Update circle content
      const circle = node.querySelector('.level-circle');

      if (level < currentLevel) {
        node.classList.add('completed');
        circle.innerHTML = `<span class="level-num">${level}</span>`;
        node.style.cursor = 'pointer';
        // Re-attach click handler
        node.onclick = () => startLevel(level);
      } else if (level === currentLevel) {
        node.classList.add('current');
        circle.innerHTML = `<span class="level-num">${level}</span>`;
        node.style.cursor = 'pointer';
        node.onclick = () => startLevel(level);
      } else {
        node.classList.add('locked');
        circle.innerHTML = `<span class="level-lock">🔒</span>`;
        node.style.cursor = 'default';
        node.onclick = null;
      }
    });

    // Update user bar badge
    const badge = document.getElementById('userLevelBadge');
    if (badge) badge.textContent = '🎯 Lvl ' + currentLevel;
  }

  // =====================================================================
  // 5. Leaderboard
  // =====================================================================
  function fetchLeaderboard() {
    fetch('/api/leaderboard')
      .then(r => r.ok ? r.json() : [])
      .then(data => renderLeaderboard(data))
      .catch(() => {
        leaderboardList.innerHTML = '<div class="leaderboard-loading">Could not load</div>';
      });
  }

  function renderLeaderboard(data) {
    if (!data.length) {
      leaderboardList.innerHTML = '<div class="leaderboard-loading">No players yet</div>';
      return;
    }
    leaderboardList.innerHTML = '';
    data.forEach((user, i) => {
      const rank = i + 1;
      const rankClass = rank <= 3 ? ` rank-${rank}` : '';
      const medals = ['', '🥇', '🥈', '🥉'];
      const medal = medals[rank] || `${rank}.`;

      const row = document.createElement('div');
      row.className = 'lb-row' + rankClass;
      row.innerHTML = `
        <span class="lb-rank">${medal}</span>
        <img class="lb-avatar" src="${escapeAttr(user.picture || '')}" alt="">
        <span class="lb-name">${escapeHtml(user.name || 'Player')}</span>
        <span class="lb-score">${user.total_score}</span>
      `;
      leaderboardList.appendChild(row);
    });
  }

  // =====================================================================
  // 6. Screen transitions
  // =====================================================================
  function showMap() {
    gameStage.classList.add('hidden');
    mapScreen.classList.remove('hidden');
    document.body.style.overflow = '';
    running = false;
    refreshMapUI();
    fetchLeaderboard();
  }

  function showGame() {
    mapScreen.classList.add('hidden');
    gameStage.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }

  // =====================================================================
  // 7. Sizing
  // =====================================================================
  function resize() {
    const dpr = window.devicePixelRatio || 1;
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    horizonY = H * 0.5;
    groundY = H * 0.76;
    playerScreenX = Math.max(90, W * 0.22);
  }
  window.addEventListener('resize', resize);

  // =====================================================================
  // 8. State setup
  // =====================================================================
  function resetState() {
    lives = MAX_LIVES;
    score = 0;
    cleared = 0;
    wordsCorrect = 0;
    levelScore = 0;
    obstacles = [];
    activeObstacle = null;
    currentQuestion = null;
    answerLocked = false;
    groundOffset = 0;

    player = {
      state: 'running',
      runTime: 0,
      jumpT: 0,
      hitT: 0,
      size: 46,
    };

    renderHearts();
    updateHud();
    fillObstacleQueue();
  }

  function renderHearts() {
    heartsEl.innerHTML = '';
    for (let i = 0; i < MAX_LIVES; i++) {
      const span = document.createElement('span');
      const alive = i < lives;
      span.className = 'heart' + (alive ? '' : ' lost');
      span.textContent = alive ? '❤️' : '🖤';
      heartsEl.appendChild(span);
    }
  }

  function updateHud() {
    scoreValueEl.textContent = String(score).padStart(4, '0');
    levelValueEl.textContent = String(playingLevel).padStart(2, '0');
    const pct = Math.min(100, (wordsCorrect / WORDS_PER_LEVEL) * 100);
    progressFill.style.width = pct + '%';
    progressText.textContent = `${wordsCorrect} / ${WORDS_PER_LEVEL}`;
  }

  function fillObstacleQueue() {
    let lastX = obstacles.length ? obstacles[obstacles.length - 1].worldX : 620;
    while (obstacles.length < QUEUE_TARGET) {
      const gap = SPAWN_GAP_MIN + Math.random() * (SPAWN_GAP_MAX - SPAWN_GAP_MIN);
      const worldX = obstacles.length ? obstacles[obstacles.length - 1].worldX + gap : lastX;
      obstacles.push({ worldX, resolved: false, id: Math.random().toString(36).slice(2) });
    }
  }

  // =====================================================================
  // 9. Main loop
  // =====================================================================
  function loop(t) {
    if (!running) return;
    const dt = Math.min(0.05, (t - lastTime) / 1000 || 0);
    lastTime = t;
    clockSec = t / 1000;
    update(dt);
    render();
    requestAnimationFrame(loop);
  }

  function update(dt) {
    if (player.state === 'running') {
      player.runTime += dt;
      groundOffset += dt;
      for (const obs of obstacles) {
        if (!obs.resolved) obs.worldX -= RUN_SPEED * dt;
      }
      const next = obstacles.find(o => !o.resolved);
      if (next && next.worldX <= STOP_GAP) {
        next.worldX = STOP_GAP;
        triggerObstacle(next);
      }
    } else if (player.state === 'jumping') {
      player.jumpT += dt;
      if (player.jumpT >= JUMP_DURATION) finishJump();
    } else if (player.state === 'hit') {
      player.hitT += dt;
      if (player.hitT >= HIT_DURATION) finishHit();
    }
  }

  // =====================================================================
  // 10. Obstacle + quiz flow
  // =====================================================================
  function triggerObstacle(obs) {
    player.state = 'stopped';
    activeObstacle = obs;
    fetchQuestion();
  }

  async function fetchQuestion() {
    try {
      const res = await fetch('/api/question');
      const data = await res.json();
      currentQuestion = data;
      showQuestionUI(data);
      startTimer();
    } catch (err) {
      console.error('Word Runner: failed to load question', err);
      resolveAnswer(true);
    }
  }

  function showQuestionUI(data) {
    answerLocked = false;
    questionText.textContent = data.question;
    optionsGrid.innerHTML = '';
    data.options.forEach((opt, i) => {
      const btn = document.createElement('button');
      btn.className = 'option-btn';
      btn.type = 'button';
      btn.innerHTML = `<span class="opt-key">${i + 1}</span>${escapeHtml(opt)}`;
      btn.addEventListener('click', () => selectAnswer(i));
      optionsGrid.appendChild(btn);
    });
    timerRingFill.classList.remove('warn', 'danger');
    timerRingFill.style.strokeDashoffset = '0';
    timerNumber.textContent = String(ANSWER_TIME);
    questionPanel.classList.remove('hidden');
  }

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeAttr(str) {
    return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function startTimer() {
    timerDeadline = performance.now() + ANSWER_TIME * 1000;
    timerRAF = requestAnimationFrame(tickTimer);
  }

  function cancelTimer() {
    if (timerRAF) cancelAnimationFrame(timerRAF);
    timerRAF = null;
  }

  function tickTimer(now) {
    if (answerLocked) return;
    const remaining = Math.max(0, (timerDeadline - now) / 1000);
    const ratio = remaining / ANSWER_TIME;
    const offset = RING_CIRCUMFERENCE * (1 - ratio);
    timerRingFill.style.strokeDashoffset = offset.toFixed(1);
    timerNumber.textContent = String(Math.ceil(remaining));
    timerRingFill.classList.toggle('warn', ratio <= 0.5 && ratio > 0.2);
    timerRingFill.classList.toggle('danger', ratio <= 0.2);

    if (remaining <= 0) {
      handleTimeout();
      return;
    }
    timerRAF = requestAnimationFrame(tickTimer);
  }

  function selectAnswer(index) {
    if (answerLocked) return;
    answerLocked = true;
    cancelTimer();
    lockOptionButtons();
    checkAnswer(index).then(data => handleAnswerResult(index, data));
  }

  function handleTimeout() {
    if (answerLocked) return;
    answerLocked = true;
    cancelTimer();
    lockOptionButtons();
    checkAnswer(-1).then(data => handleAnswerResult(-1, data));
  }

  function lockOptionButtons() {
    optionsGrid.querySelectorAll('.option-btn').forEach(b => { b.disabled = true; });
  }

  function checkAnswer(index) {
    return fetch('/api/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: currentQuestion.id, selected: index }),
    }).then(r => r.json());
  }

  function handleAnswerResult(selectedIndex, data) {
    const buttons = optionsGrid.querySelectorAll('.option-btn');
    if (buttons[data.correctIndex]) buttons[data.correctIndex].classList.add('correct');
    if (selectedIndex >= 0 && selectedIndex !== data.correctIndex && buttons[selectedIndex]) {
      buttons[selectedIndex].classList.add('wrong');
    }
    setTimeout(() => resolveAnswer(!!data.correct), 500);
  }

  function resolveAnswer(isCorrect) {
    questionPanel.classList.add('hidden');
    if (isCorrect) {
      cleared += 1;
      score += 100;
      levelScore += 100;
      wordsCorrect += 1;
      updateHud();
      player.state = 'jumping';
      player.jumpT = 0;
    } else {
      loseLife();
      flashHit();
      player.state = 'hit';
      player.hitT = 0;
    }
  }

  function finishJump() {
    if (activeObstacle) {
      activeObstacle.resolved = true;
      obstacles = obstacles.filter(o => o !== activeObstacle);
      fillObstacleQueue();
    }
    activeObstacle = null;

    // Check level completion
    if (wordsCorrect >= WORDS_PER_LEVEL) {
      levelComplete();
      return;
    }

    player.state = 'running';
  }

  function finishHit() {
    if (activeObstacle) {
      activeObstacle.resolved = true;
      obstacles = obstacles.filter(o => o !== activeObstacle);
      fillObstacleQueue();
    }
    activeObstacle = null;
    if (lives <= 0) {
      gameOver();
    } else {
      player.state = 'running';
    }
  }

  function loseLife() {
    lives = Math.max(0, lives - 1);
    renderHearts();
  }

  function flashHit() {
    hitFlash.classList.add('active');
    setTimeout(() => hitFlash.classList.remove('active'), 160);
  }

  // =====================================================================
  // 11. Level complete
  // =====================================================================
  function levelComplete() {
    running = false;
    player.state = 'stopped';

    // Save the run score
    saveScore(levelScore);

    // Tell backend to advance level
    fetch('/api/level-up', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: playingLevel }),
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data && data.current_level) {
          currentLevel = data.current_level;
          const badge = document.getElementById('userLevelBadge');
          if (badge) badge.textContent = '🎯 Lvl ' + currentLevel;
        }
      })
      .catch(() => {});

    // Show level complete UI
    completedLevelNum.textContent = String(playingLevel);
    levelScoreEarned.textContent = String(levelScore);
    levelCompleteScreen.classList.remove('hidden');
  }

  // =====================================================================
  // 12. Game over
  // =====================================================================
  function gameOver() {
    running = false;
    player.state = 'dead';
    finalScoreEl.textContent = String(levelScore);
    finalClearedEl.textContent = String(wordsCorrect);
    gameOverScreen.classList.remove('hidden');
    if (levelScore > 0) saveScore(levelScore);
  }

  function saveScore(runScore) {
    fetch('/api/save-score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ score: runScore }),
    })
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data && typeof data.total_score !== 'undefined') {
          const scoreBar = document.getElementById('userTotalScore');
          if (scoreBar) scoreBar.textContent = '⭐ ' + data.total_score;
        }
      })
      .catch(() => {});
  }

  // =====================================================================
  // 13. Rendering
  // =====================================================================
  function render() {
    ctx.clearRect(0, 0, W, H);

    let shakeX = 0, shakeY = 0;
    if (player.state === 'hit') {
      const s = Math.sin(player.hitT * 70) * (1 - player.hitT / HIT_DURATION);
      shakeX = s * 6;
      shakeY = Math.cos(player.hitT * 55) * 3 * (1 - player.hitT / HIT_DURATION);
    }

    ctx.save();
    ctx.translate(shakeX, shakeY);

    drawGrid();
    drawHorizonGlow();
    drawObstacles();
    drawPlayer();

    ctx.restore();
  }

  function drawGrid() {
    const vanishX = W / 2;
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 220, 255, 0.16)';
    ctx.lineWidth = 1;

    const numLines = 12;
    for (let i = -numLines; i <= numLines; i++) {
      if (i === 0) continue;
      const spread = i * 46;
      ctx.beginPath();
      ctx.moveTo(vanishX, horizonY);
      ctx.lineTo(vanishX + spread * 3.2, H);
      ctx.stroke();
    }

    const rows = 9;
    const scrollT = groundOffset % 1;
    for (let r = 0; r <= rows; r++) {
      const t = (r + scrollT) / rows;
      if (t > 1) continue;
      const y = horizonY + Math.pow(t, 2.3) * (H - horizonY);
      ctx.globalAlpha = Math.max(0, 0.5 - t * 0.4);
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(W, y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.restore();
  }

  function drawHorizonGlow() {
    ctx.save();
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.55)';
    ctx.lineWidth = 2;
    ctx.shadowColor = 'rgba(0, 240, 255, 0.9)';
    ctx.shadowBlur = 16;
    ctx.beginPath();
    ctx.moveTo(0, horizonY);
    ctx.lineTo(W, horizonY);
    ctx.stroke();
    ctx.restore();
  }

  function drawObstacles() {
    for (const obs of obstacles) {
      if (obs.resolved) continue;
      const x = playerScreenX + obs.worldX;
      if (x < -80 || x > W + 80) continue;

      const isActive = obs === activeObstacle;
      const obsW = 34;
      const obsH = 96;
      const y = groundY - obsH;

      const pulse = isActive ? 0.6 + Math.sin(clockSec * 8) * 0.4 : 1;

      ctx.save();
      ctx.shadowColor = `rgba(255, 43, 109, ${0.7 * pulse})`;
      ctx.shadowBlur = 22;
      const grad = ctx.createLinearGradient(x, y, x, y + obsH);
      grad.addColorStop(0, '#ff2b6d');
      grad.addColorStop(1, '#8a0f38');
      ctx.fillStyle = grad;
      roundRect(ctx, x - obsW / 2, y, obsW, obsH, 6);
      ctx.fill();

      ctx.save();
      ctx.beginPath();
      roundRect(ctx, x - obsW / 2, y, obsW, obsH, 6);
      ctx.clip();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.35)';
      ctx.lineWidth = 5;
      for (let sx = -obsH; sx < obsW + obsH; sx += 14) {
        ctx.beginPath();
        ctx.moveTo(x - obsW / 2 + sx, y + obsH);
        ctx.lineTo(x - obsW / 2 + sx + obsH, y);
        ctx.stroke();
      }
      ctx.restore();
      ctx.restore();
    }
  }

  function drawPlayer() {
    const size = player.size;
    let x = playerScreenX;
    let y = groundY - size / 2;
    let scaleX = 1, scaleY = 1, glow = 'rgba(0, 240, 255, 0.85)';
    let fillTop = '#00f0ff', fillBottom = '#2b6fff';

    if (player.state === 'running') {
      y -= Math.abs(Math.sin(player.runTime * 9)) * 6;
    } else if (player.state === 'stopped') {
      y -= Math.sin(clockSec * 4) * 2;
      scaleX = 1 + Math.sin(clockSec * 4) * 0.02;
    } else if (player.state === 'jumping') {
      const p = player.jumpT / JUMP_DURATION;
      y -= Math.sin(p * Math.PI) * 82;
      x += p * 58;
      scaleY = 1 - Math.sin(p * Math.PI) * 0.15;
      scaleX = 1 + Math.sin(p * Math.PI) * 0.1;
    } else if (player.state === 'hit') {
      const p = player.hitT / HIT_DURATION;
      x -= (1 - p) * 22;
      fillTop = '#ff2b6d';
      fillBottom = '#8a0f38';
      glow = 'rgba(255, 43, 109, 0.85)';
    } else if (player.state === 'dead') {
      scaleY = 0.6;
    }

    ctx.save();
    ctx.translate(x, y);
    ctx.scale(scaleX, scaleY);
    ctx.shadowColor = glow;
    ctx.shadowBlur = 24;

    const grad = ctx.createLinearGradient(-size / 2, -size / 2, size / 2, size / 2);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBottom);
    ctx.fillStyle = grad;
    roundRect(ctx, -size / 2, -size / 2, size, size, 12);
    ctx.fill();

    ctx.shadowBlur = 0;
    ctx.fillStyle = 'rgba(6, 7, 15, 0.55)';
    roundRect(ctx, -size * 0.28, -size * 0.12, size * 0.56, size * 0.22, 5);
    ctx.fill();

    ctx.restore();

    ctx.save();
    ctx.globalAlpha = 0.35;
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.ellipse(playerScreenX, groundY + 4, size * 0.42, 7, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  // =====================================================================
  // 14. Flow control
  // =====================================================================
  function startLevel(level) {
    playingLevel = level;
    showGame();
    gameOverScreen.classList.add('hidden');
    levelCompleteScreen.classList.add('hidden');
    resize();
    resetState();
    running = true;
    lastTime = performance.now();
    requestAnimationFrame(loop);
  }

  // Make startLevel available globally (for inline onclick in template)
  window.startLevel = startLevel;

  // Retry = restart same level
  retryBtn.addEventListener('click', () => {
    gameOverScreen.classList.add('hidden');
    startLevel(playingLevel);
  });

  // Back to map from game over
  backToMapBtnGO.addEventListener('click', () => {
    gameOverScreen.classList.add('hidden');
    showMap();
  });

  // Back to map from level complete
  backToMapBtn.addEventListener('click', () => {
    levelCompleteScreen.classList.add('hidden');
    showMap();
  });

  // Keyboard shortcuts
  window.addEventListener('keydown', (e) => {
    if (!questionPanel.classList.contains('hidden') && /^[1-4]$/.test(e.key)) {
      selectAnswer(Number(e.key) - 1);
      return;
    }
  });

  resize();
})();
