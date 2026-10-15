/* =====================================================================
   Word Match Game — Uzbek ↔ English Translation Matching
   ===================================================================== */

(function () {
  'use strict';

  let currentLevel = 1;
  let score = 0;
  let matchedCount = 0;
  let totalCards = 4;
  let selectedUzCard = null;
  let gameWords = [];

  const board = document.getElementById('matchBoard');
  const scoreEl = document.getElementById('matchScore');
  const matchCountEl = document.getElementById('matchCount');
  const levelNumEl = document.getElementById('matchLevelNum');
  const completeOverlay = document.getElementById('matchCompleteOverlay');
  const finalScoreEl = document.getElementById('matchFinalScore');
  const levelsRow = document.getElementById('matchLevelsRow');
  const nextLevelBtn = document.getElementById('matchNextLevelBtn');

  // Level button click handlers
  if (levelsRow) {
    levelsRow.addEventListener('click', (e) => {
      const btn = e.target.closest('.match-level-btn');
      if (!btn) return;
      const level = parseInt(btn.dataset.level);
      if (level) {
        currentLevel = level;
        levelsRow.querySelectorAll('.match-level-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        startLevel(level);
      }
    });
  }

  // Next level button
  if (nextLevelBtn) {
    nextLevelBtn.addEventListener('click', () => {
      if (currentLevel < 5) {
        currentLevel++;
        levelsRow.querySelectorAll('.match-level-btn').forEach(b => b.classList.remove('active'));
        const nextBtn = levelsRow.querySelector(`[data-level="${currentLevel}"]`);
        if (nextBtn) nextBtn.classList.add('active');
        startLevel(currentLevel);
      } else {
        window.location.href = '/games';
      }
    });
  }

  function startLevel(level) {
    score = 0;
    matchedCount = 0;
    selectedUzCard = null;
    scoreEl.textContent = '0';
    levelNumEl.textContent = level;
    completeOverlay.classList.add('hidden');
    board.innerHTML = '<div class="match-loading">So'zlar yuklanmoqda...</div>';

    fetch(`/api/vocab?level=${level}`)
      .then(r => r.json())
      .then(data => {
        gameWords = data.words;
        totalCards = gameWords.length;
        matchCountEl.textContent = `0 / ${totalCards}`;
        renderBoard(data.words, data.all_translations);
      })
      .catch(err => {
        board.innerHTML = '<div class="match-loading">Xatolik. Qayta urinib ko'ring.</div>';
        console.error(err);
      });
  }

  function renderBoard(words, allTranslations) {
    board.innerHTML = '';

    // Create two columns: Uzbek words on left, English translations on right
    const uzColumn = document.createElement('div');
    uzColumn.className = 'match-column match-column-uz';

    const enColumn = document.createElement('div');
    enColumn.className = 'match-column match-column-en';

    // Shuffle English translations
    const shuffledEn = [...words].sort(() => Math.random() - 0.5);

    words.forEach((word, i) => {
      const uzCard = document.createElement('button');
      uzCard.className = 'match-card match-card-uz';
      uzCard.innerHTML = `<span class="match-card-text">${word.uz_word}</span><span class="match-card-lang">🇺🇿 O'zbekcha</span>`;
      uzCard.dataset.id = word.id;
      uzCard.dataset.answer = word.en_translation;
      uzCard.addEventListener('click', () => selectUzCard(uzCard));
      uzColumn.appendChild(uzCard);
    });

    shuffledEn.forEach((word, i) => {
      const enCard = document.createElement('button');
      enCard.className = 'match-card match-card-en';
      enCard.innerHTML = `<span class="match-card-text">${word.en_translation}</span><span class="match-card-lang">🇬🇧 English</span>`;
      enCard.dataset.translation = word.en_translation;
      enCard.addEventListener('click', () => selectEnCard(enCard));
      enColumn.appendChild(enCard);
    });

    board.appendChild(uzColumn);
    board.appendChild(enColumn);
  }

  function selectUzCard(card) {
    if (card.classList.contains('matched')) return;
    // Deselect previous
    board.querySelectorAll('.match-card-uz.selected').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    selectedUzCard = card;
  }

  function selectEnCard(card) {
    if (card.classList.contains('matched')) return;
    if (!selectedUzCard) {
      // Shake the english card to hint user should pick uzbek first
      card.classList.add('shake');
      setTimeout(() => card.classList.remove('shake'), 500);
      return;
    }

    const correctAnswer = selectedUzCard.dataset.answer;
    const selectedTranslation = card.dataset.translation;

    if (correctAnswer === selectedTranslation) {
      // Correct match!
      selectedUzCard.classList.add('matched');
      card.classList.add('matched');
      selectedUzCard.classList.remove('selected');

      score += 25;
      matchedCount++;
      scoreEl.textContent = score;
      matchCountEl.textContent = `${matchedCount} / ${totalCards}`;

      // Animate disappearance
      setTimeout(() => {
        selectedUzCard.style.opacity = '0';
        selectedUzCard.style.transform = 'scale(0.8)';
        card.style.opacity = '0';
        card.style.transform = 'scale(0.8)';
        selectedUzCard = null;

        // Check if level complete
        if (matchedCount >= totalCards) {
          setTimeout(() => showLevelComplete(), 400);
        }
      }, 600);

    } else {
      // Wrong match
      selectedUzCard.classList.add('wrong');
      card.classList.add('wrong');
      setTimeout(() => {
        selectedUzCard.classList.remove('wrong', 'selected');
        card.classList.remove('wrong');
        selectedUzCard = null;
      }, 700);
    }
  }

  function showLevelComplete() {
    finalScoreEl.textContent = score;
    completeOverlay.classList.remove('hidden');

    // Save score to server
    fetch('/api/save-score', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ score: score })
    }).catch(console.error);

    if (currentLevel >= 5) {
      nextLevelBtn.textContent = '🏠 O\'yinlarga qaytish';
    } else {
      nextLevelBtn.textContent = 'Keyingi bosqich →';
    }
  }

  // Start first level on load
  startLevel(1);

})();
