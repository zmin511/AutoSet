    const $ = (id) => document.getElementById(id);
    let selectedTrack = null;
    let currentPath = '';
    let timer = null;
    let lastBuiltSetFolder = '';
    let styleGroups = [];
    let genreOptions = [];
    let currentRows = { dirs: [], tracks: [], rel: '', parent: '' };
    let styleSuggestions = new Map();
    let selectedStyleFiles = new Set();
    let sortState = { key: '', dir: 'asc' };
    let picker = { kind: 'folder', target: 'musicRoot', path: '', parent: '' };

    function esc(s) {
      return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    function fmtLen(seconds) {
      const m = Math.floor((seconds || 0) / 60);
      const s = String((seconds || 0) % 60).padStart(2, '0');
      return seconds ? `${m}:${s}` : '';
    }

    function metaLine(track) {
      return `${track.genre || 'genre?'} · ${track.bpm || '?'} BPM · ${track.camelot || 'key?'} · ${fmtLen(track.length) || 'len?'}`;
    }

    function keyClass(camelot) {
      const m = String(camelot || '').match(/^(\d{1,2})[AB]$/i);
      return m ? `key-${m[1]}` : '';
    }

    function camelotSortValue(camelot) {
      const m = String(camelot || '').match(/^(\d{1,2})([AB])$/i);
      if (!m) return 999;
      return Number(m[1]) * 2 + (m[2].toUpperCase() === 'B' ? 1 : 0);
    }

    function genreClass(genre) {
      const g = String(genre || '').toLowerCase();
      if (g.includes('house')) return 'genre-house';
      if (g.includes('techno')) return 'genre-techno';
      if (g.includes('dnb') || g.includes('drum')) return 'genre-dnb';
      if (g.includes('trance')) return 'genre-trance';
      if (g.includes('dance') || g.includes('electronic')) return 'genre-dance';
      if (g.includes('rock')) return 'genre-rock';
      if (g.includes('pop')) return 'genre-pop';
      return '';
    }

    function genreColorLabel(genre) {
      const g = String(genre || '').toLowerCase();
      if (g.includes('house')) return 'House: зеленая полоса';
      if (g.includes('techno')) return 'Techno: фиолетовая полоса';
      if (g.includes('dnb') || g.includes('drum')) return 'Drum & Bass: красная полоса';
      if (g.includes('trance')) return 'Trance: желтая полоса';
      if (g.includes('dance') || g.includes('electronic')) return 'Dance/Electronic: синяя полоса';
      if (g.includes('rock')) return 'Rock: серая полоса';
      if (g.includes('pop')) return 'Pop: розовая полоса';
      return '';
    }

    function normPath(path) {
      return String(path || '').replace(/\//g, '\\').toLowerCase();
    }

    function suggestionForTrack(track) {
      return styleSuggestions.get(normPath(track.path || track.rel || '')) || null;
    }

    function selectableSuggestion(item) {
      return item && item.action !== 'skipped_confidence';
    }

    function selectedSuggestionFiles(all = false) {
      const files = [];
      styleSuggestions.forEach(item => {
        if (!selectableSuggestion(item)) return;
        if (all || selectedStyleFiles.has(item.file)) files.push(item.file);
      });
      return files;
    }

    function normStyle(value) {
      return String(value || '')
        .toLowerCase()
        .replace(/&/g, ' and ')
        .replace(/[^a-zа-я0-9]+/gi, '_')
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '')
        .replace(/^breakbeat$/, 'break_beat')
        .replace(/^funky$/, 'funky_house')
        .replace(/^groove$/, 'funky_house')
        .replace(/^jackin$/, 'jackin_house')
        .replace(/^deep_tech$/, 'minimal_deep_tech')
        .replace(/^soul_funk$/, 'soul_and_funk');
    }

    async function loadStyles() {
      const [styleRes, genreRes] = await Promise.all([fetch('/api/styles'), fetch('/api/genres')]);
      const data = await styleRes.json();
      const genreData = await genreRes.json();
      styleGroups = data.groups || [];
      genreOptions = genreData.genres || [];
      $('genreOptionsList').innerHTML = genreOptions.map(g => `<option value="${esc(g)}"></option>`).join('');
      renderStyleGrid();
    }

    function genreSelect(track) {
      const current = track.genre || '';
      return `<input class="genre-select" id="selectedGenre" list="genreOptionsList" value="${esc(current)}" placeholder="Жанр">`;
    }

    function tagWriteStatusMessage(data, successText) {
      if (!data?.ok) return successText;
      if (data.file_tags_warning) return `В Engine DB записано, но файл не обновлён: ${data.file_tags_warning}`;
      if (data.file_tags_updated || data.engine_db_updated) return `${successText}: Engine DB и файл`;
      return successText;
    }

    function selectedMarkup(track, withStatus = true) {
      const title = track.label || track.filename || '';
      const initials = (String(title).match(/[A-Za-zА-Яа-я0-9]/g) || ['A']).slice(0, 2).join('').toUpperCase();
      return `
        <div class="track-card">
          <div class="track-cover" title="Cover art">${esc(initials)}</div>
          <div class="track-info">
            <div class="track-title" title="${esc(title)}">${esc(title)}</div>
            <div class="selected-meta">
              ${genreSelect(track)}
              <span>${esc(track.camelot || 'key?')}</span>
              <span>${esc(track.bpm || '?')} BPM</span>
              <span>${fmtLen(track.length) || 'len?'}</span>
              <span>${esc(track.bitrate || '')} kbps</span>
            </div>
            <div class="selected-meta"><span>${energyStars(track)}</span></div>
            ${withStatus ? `<div class="selected-meta"><span>${track.id ? 'Можно строить сет' : 'Нет в Engine DB: сначала импортируй/проанализируй трек в Engine'}</span></div>` : ''}
          </div>
        </div>
      `;
    }

    function wireGenreSelect() {
      const select = $('selectedGenre');
      if (!select || !selectedTrack?.id) return;
      let lastSaved = select.value;
      const saveGenre = async () => {
        const genre = select.value.trim();
        if (!genre || genre === lastSaved) return;
        $('status').textContent = 'Сохраняю жанр...';
        try {
          const res = await fetch('/api/update-genre', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ track_id: selectedTrack.id, genre })
          });
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || 'update failed');
          selectedTrack.genre = genre;
          lastSaved = genre;
          applyInferredStyles(selectedTrack);
          $('status').className = data.file_tags_warning ? 'status bad' : 'status ok';
          $('status').textContent = tagWriteStatusMessage(data, 'Жанр сохранён');
          if ($('search').value.trim()) search(); else browse(currentPath);
        } catch (err) {
          $('status').className = 'status bad';
          $('status').textContent = `Ошибка сохранения жанра: ${err}`;
        }
      };
      select.addEventListener('change', saveGenre);
      select.addEventListener('blur', saveGenre);
      select.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          saveGenre();
        }
      });
    }

    function renderStyleGrid() {
      const box = $('styleGrid');
      box.innerHTML = styleGroups.map(group => `
        <div class="style-group">
          <div class="style-title">${esc(group.name)}</div>
          <div class="style-grid">
            ${(group.styles || []).map(style => `
              <label class="style-chip" title="${esc(style.title || `${style.count || 0} tracks`)}">
                <input type="checkbox" value="${esc(style.value)}">
                <span>${esc(style.label)}</span>
              </label>
            `).join('')}
          </div>
        </div>
      `).join('');
    }

    function inferStyles(track) {
      const text = `${track.genre || ''} ${track.label || ''} ${track.filename || ''}`.toLowerCase();
      const explicit = String(track.genre || '').split(/[,;/|<>]+/).map(normStyle).filter(Boolean);
      const picked = new Set(explicit);
      const add = (...values) => values.filter(Boolean).forEach(v => picked.add(v));

      if (text.includes('tech house') || text.includes('techhouse')) add('house', 'tech_house', 'deep_house', 'progressive_house', 'minimal_deep_tech');
      else if (text.includes('deep house')) add('house', 'deep_house', 'soulful_house', 'chill_house', 'progressive_house');
      else if (text.includes('progressive house')) add('house', 'progressive_house', 'deep_house', 'tech_house');
      else if (text.includes('afro house')) add('house', 'afro_house', 'deep_house', 'progressive_house');
      else if (text.includes('disco house')) add('house', 'disco_house', 'nu_disco', 'funky_house');
      else if (text.includes('electro house')) add('house', 'electro_house', 'tech_house', 'electro');
      else if (text.includes('house')) add('house', 'deep_house', 'tech_house', 'progressive_house', 'afro_house', 'disco_house', 'funky_house', 'electro_house');

      if (text.includes('melodic techno')) add('techno', 'melodic_techno', 'minimal_deep_tech', 'progressive_house');
      else if (text.includes('minimal') || text.includes('deep tech')) add('techno', 'minimal_deep_tech', 'tech_house');
      else if (text.includes('techno') || text.includes('boris brejcha')) add('techno', 'minimal_deep_tech', 'melodic_techno');

      if (text.includes('trance')) add('trance', 'progressive_trance');
      if (text.includes('nu disco')) add('nu_disco', 'disco', 'disco_house', 'funky_house');
      else if (text.includes('disco')) add('disco', 'nu_disco', 'disco_house', 'funky_house');
      if (text.includes('indie dance')) add('indie_dance', 'nu_disco', 'electro');
      if (text.includes('electro')) add('electro', 'electro_house', 'indie_dance');
      if (text.includes('drum') || text.includes('dnb')) add('drum_and_bass');
      if (text.includes('breakbeat') || text.includes('break beat')) add('break_beat', 'garage');
      if (text.includes('uk garage')) add('garage', 'uk_garage', 'break_beat');
      else if (text.includes('garage')) add('garage', 'uk_garage', 'break_beat');
      if (text.includes('chill') || text.includes('ambient') || text.includes('downtempo') || text.includes('lounge')) add('chill', 'ambient', 'downtempo', 'lounge');
      if (text.includes('rus') || text.includes('рус')) add('rus');
      if (text.includes('pop')) add('pop');
      if (text.includes('rock')) add('rock');
      return picked;
    }

    function applyInferredStyles(track) {
      const picked = inferStyles(track);
      document.querySelectorAll('#styleGrid input[type="checkbox"]').forEach(input => {
        input.checked = picked.has(input.value);
      });
    }

    function selectedStyles() {
      return Array.from(document.querySelectorAll('#styleGrid input[type="checkbox"]:checked')).map(input => input.value);
    }

    function energyStars(track) {
      const computed = Number(track.energy_rating || 0);
      const engine = Number(track.rating || 0);
      const engineRaw = Number(track.rating_raw || 0);
      const rating = Math.max(0, Math.min(5, computed || engine));
      const synced = !!computed && engine === computed && engineRaw === computed * 20;
      const stateClass = rating ? (synced ? 'synced' : 'unsynced') : 'empty';
      const stateText = synced ? 'записано в Engine' : (computed ? 'рассчитано, еще не записано в Engine' : 'нет waveform-расчета');
      const energy = (typeof track.energy === 'number') ? `, waveform ${track.energy}` : '';
      const engineText = engineRaw ? `, Engine rating ${engineRaw}` : '';
      const title = rating ? `Энергия трека ${rating}/5: ${stateText}${energy}${engineText}` : 'Энергия не рассчитана';
      const text = rating ? `${'★'.repeat(rating)}${'☆'.repeat(5 - rating)}` : '-----';
      return `<span class="stars ${stateClass}" title="${esc(title)}">${text}</span>`;
    }


    const transitionScores = new Map();
    let transitionScoresRequestToken = 0;

    function transitionForTrack(track) {
      if (!track?.id || !selectedTrack?.id) return null;

      if (Number(track.id) === Number(selectedTrack.id)) {
        return null;
      }

      return transitionScores.get(String(track.id)) || null;
    }

    function transitionClassLabel(value) {
      const key = String(value || '').toLowerCase();

      if (key === 'safe') return 'SAFE';
      if (key === 'compatible') return 'COMP';
      if (key === 'risky') return 'RISK';
      if (key === 'rejected') return 'REJECT';

      return '?';
    }

    function transitionPercent(value) {
      const score = Number(value);

      if (!Number.isFinite(score)) return '';

      return `${Math.round(score * 100)}%`;
    }

    function transitionTooltip(track) {
      if (!selectedTrack?.id) {
        return '\u0421\u043d\u0430\u0447\u0430\u043b\u0430 '
          + '\u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 '
          + '\u043e\u043f\u043e\u0440\u043d\u044b\u0439 '
          + '\u0442\u0440\u0435\u043a';
      }

      if (Number(track?.id) === Number(selectedTrack.id)) {
        return '\u041e\u043f\u043e\u0440\u043d\u044b\u0439 '
          + '\u0442\u0440\u0435\u043a';
      }

      const result = transitionForTrack(track);

      if (!result?.available) {
        return result?.error
          || '\u041f\u0440\u043e\u0444\u0438\u043b\u044c '
          + '\u043f\u0435\u0440\u0435\u0445\u043e\u0434\u0430 '
          + '\u043e\u0442\u0441\u0443\u0442\u0441\u0442\u0432\u0443\u0435\u0442';
      }

      const components = result.components || {};

      const lines = [
        `\u041f\u0435\u0440\u0435\u0445\u043e\u0434 \u043e\u0442: ${selectedTrack.label || selectedTrack.filename || selectedTrack.id}`,
        `\u041a \u0442\u0440\u0435\u043a\u0443: ${track.label || track.filename || track.id}`,
        '',
        `\u041a\u043b\u0430\u0441\u0441: ${transitionClassLabel(result.class)}`,
        `\u0418\u0442\u043e\u0433: ${transitionPercent(result.score)}`,
      ];

      const labels = {
        bpm: 'BPM',
        camelot: 'Camelot',
        energy: 'Energy',
        genre: 'Genre',
      };

      Object.entries(labels).forEach(([key, label]) => {
        const value = Number(components[key]);

        if (Number.isFinite(value)) {
          lines.push(`${label}: ${Math.round(value * 100)}%`);
        }
      });

      return lines.join('\n');
    }

    function transitionCellMarkup(track) {
      if (!selectedTrack?.id) {
        return '<span class="transition-empty">\u2014</span>';
      }

      if (Number(track?.id) === Number(selectedTrack.id)) {
        return '<span class="transition-reference">'
          + '\u041e\u041f\u041e\u0420\u0410'
          + '</span>';
      }

      const result = transitionForTrack(track);

      if (!result?.available) {
        return '<span class="transition-empty">\u2014</span>';
      }

      const className = String(
        result.class || 'rejected'
      ).toLowerCase();

      return `
        <span class="transition-badge transition-${esc(className)}">
          <span class="transition-label">
            ${esc(transitionClassLabel(className))}
          </span>
          <span class="transition-score">
            ${esc(transitionPercent(result.score))}
          </span>
        </span>
      `;
    }

    async function loadTransitionScoresForTracks(tracks) {
      const referenceId = Number(selectedTrack?.id || 0);

      transitionScores.clear();

      if (!referenceId) {
        return;
      }

      const candidateIds = (tracks || [])
        .map(track => Number(track?.id || 0))
        .filter(id => id && id !== referenceId);

      if (!candidateIds.length) {
        return;
      }

      const token = ++transitionScoresRequestToken;
      const params = new URLSearchParams();

      params.set(
        'reference_track_id',
        String(referenceId)
      );

      params.set(
        'candidate_track_ids',
        candidateIds.join(',')
      );

      try {
        const response = await fetch(
          `/api/transition-scores?${params.toString()}`
        );

        const data = await response.json();

        if (
          token !== transitionScoresRequestToken
          || Number(selectedTrack?.id || 0) !== referenceId
        ) {
          return;
        }

        if (!data.ok) {
          console.warn(
            'Transition scores unavailable:',
            data.error || data
          );
          return;
        }

        Object.entries(data.scores || {}).forEach(
          ([trackId, result]) => {
            transitionScores.set(
              String(trackId),
              result
            );
          }
        );

      } catch (error) {
        console.warn(
          'Transition score request failed:',
          error
        );
      }
    }

    function trackRow(track) {
      const btn = document.createElement('div');
      btn.tabIndex = 0;
      btn.className = `item ${genreClass(track.genre)}` + (selectedTrack?.id && selectedTrack.id === track.id ? ' selected' : '');
      const colorTitle = genreColorLabel(track.genre);
      if (colorTitle) btn.title = `Цвет строки: ${colorTitle}. Он показывает основную группу жанра и помогает быстро ориентироваться в списке.`;
      const suggestion = suggestionForTrack(track);
      const suggestionAllowed = selectableSuggestion(suggestion);
      const suggestionFile = suggestion?.file || '';
      const suggestionChecked = suggestionAllowed && selectedStyleFiles.has(suggestionFile);
      const batchChecked = batchTrackIds.has(Number(track.id));
      const suggestionTitle = suggestion
        ? `${suggestion.additions.join(', ')} -> ${suggestion.new_genre} (${suggestion.source || 'Online'}; ${suggestion.confidence})
${suggestion.reason || ''}`
        : 'Нет предложений по подстилям';
      const marks = [
        track.has_cue ? '<span class="dot cue" title="Есть cue-маркер"></span>' : '',
        track.has_loop ? '<span class="dot loop" title="Есть loop"></span>' : '',
      ].filter(Boolean).join('');
      btn.innerHTML = `
        <input class="batch-check" type="checkbox" data-batch-select="track" data-id="${esc(track.id)}" ${batchChecked ? 'checked' : ''} title="Отметить трек для пакетных подсказок">
        <button class="play ${playingPath === (track.rel || track.path) ? 'active' : ''}" type="button" title="Воспроизвести этот трек" aria-label="Воспроизвести этот трек"></button>
        <div class="title"><span class="name">${esc(track.label || track.filename)}</span><span class="sub">${esc(track.path || track.rel || '')}</span></div>
        <div class="marks">${marks}</div>
        <div
          class="cell transition-cell"
          title="${esc(transitionTooltip(track))}"
        >
          ${transitionCellMarkup(track)}
        </div>
        <div class="cell genre-cell">${esc(track.genre || '')}</div>
        <div class="cell suggest-cell ${suggestion ? '' : 'empty'}" title="${esc(suggestionTitle)}">
          ${suggestion ? `
            <input class="suggest-check" type="checkbox" data-file="${esc(suggestionFile)}" ${suggestionChecked ? 'checked' : ''} ${suggestionAllowed ? '' : 'disabled'}>
            <span class="suggest-tags">+ ${esc((suggestion.additions || []).join(', '))}</span>
            <span class="suggest-confidence">${esc(suggestion.source || suggestion.confidence || '')}</span>
          ` : '<span class="suggest-tags">-</span>'}
        </div>
        <div class="cell">${energyStars(track)}</div>
        <div class="cell tag ${keyClass(track.camelot)}">${esc(track.camelot || '')}</div>
        <div class="cell tag">${esc(track.bpm || '')}</div>
        <div class="cell">${esc(fmtLen(track.length))}</div>
      `;
      btn.onclick = (event) => {
        const batchBox = event.target.classList.contains('batch-check') ? event.target : event.target.closest('.batch-check');
        if (batchBox) {
          event.stopPropagation();
          const id = Number(batchBox.dataset.id || track.id || 0);
          if (batchBox.checked) batchTrackIds.add(id);
          else batchTrackIds.delete(id);
          syncBatchSuggestControls();
          return;
        }
        if (event.target.classList.contains('play')) {
          event.stopPropagation();
          playTrack(track);
        } else if (event.target.classList.contains('suggest-check')) {
          event.stopPropagation();
          const file = event.target.dataset.file || '';
          if (event.target.checked) selectedStyleFiles.add(file);
          else selectedStyleFiles.delete(file);
        } else {
          selectTrack(track);
        }
      };
      return btn;
    }

    function renderHeader(box) {
      const head = document.createElement('div');
      head.className = 'item head';

      head.innerHTML = `
        <div></div>
        <div></div>
        <div>\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 / \u043f\u0443\u0442\u044c</div>
        <div></div>

        <button
          class="sort-head transition-head ${sortState.key === 'transition' ? 'active' : ''}"
          data-sort="transition"
        >
          \u041f\u0435\u0440\u0435\u0445\u043e\u0434 ${sortState.key === 'transition' ? (sortState.dir === 'asc' ? '\u2191' : '\u2193') : ''}
        </button>

        <button
          class="sort-head ${sortState.key === 'genre' ? 'active' : ''}"
          data-sort="genre"
        >
          \u0416\u0430\u043d\u0440 ${sortState.key === 'genre' ? (sortState.dir === 'asc' ? '\u2191' : '\u2193') : ''}
        </button>

        <div>\u041f\u043e\u0434\u0441\u0442\u0438\u043b\u0438</div>

        <button
          class="sort-head ${sortState.key === 'energy' ? 'active' : ''}"
          data-sort="energy"
        >
          \u042d\u043d\u0435\u0440\u0433\u0438\u044f ${sortState.key === 'energy' ? (sortState.dir === 'asc' ? '\u2191' : '\u2193') : ''}
        </button>

        <button
          class="sort-head ${sortState.key === 'camelot' ? 'active' : ''}"
          data-sort="camelot"
        >
          Key ${sortState.key === 'camelot' ? (sortState.dir === 'asc' ? '\u2191' : '\u2193') : ''}
        </button>

        <button
          class="sort-head ${sortState.key === 'bpm' ? 'active' : ''}"
          data-sort="bpm"
        >
          BPM ${sortState.key === 'bpm' ? (sortState.dir === 'asc' ? '\u2191' : '\u2193') : ''}
        </button>

        <button
          class="sort-head ${sortState.key === 'length' ? 'active' : ''}"
          data-sort="length"
        >
          \u0414\u043b\u0438\u0442. ${sortState.key === 'length' ? (sortState.dir === 'asc' ? '\u2191' : '\u2193') : ''}
        </button>
      `;

      head.querySelectorAll('[data-sort]').forEach(button => {
        button.onclick = event => {
          event.stopPropagation();
          setSort(button.dataset.sort);
        };
      });

      box.appendChild(head);
    }

    function sortedTracks(tracks) {
      const out = [...tracks];

      if (!sortState.key) return out;

      const dir = sortState.dir === 'asc' ? 1 : -1;

      out.sort((a, b) => {
        let av;
        let bv;

        if (sortState.key === 'bpm') {
          av = Number(a.bpm || 0);
          bv = Number(b.bpm || 0);

        } else if (sortState.key === 'length') {
          av = Number(a.length || 0);
          bv = Number(b.length || 0);

        } else if (sortState.key === 'camelot') {
          av = camelotSortValue(a.camelot);
          bv = camelotSortValue(b.camelot);

        } else if (sortState.key === 'energy') {
          av = Number(a.energy_rating || a.rating || 0);
          bv = Number(b.energy_rating || b.rating || 0);

        } else if (sortState.key === 'transition') {
          const aTransition = transitionForTrack(a);
          const bTransition = transitionForTrack(b);

          const priority = {
            safe: 4,
            compatible: 3,
            risky: 2,
            rejected: 1,
          };

          av = aTransition?.available
            ? (
                (priority[String(aTransition.class || '')] || 0) * 10
                + Number(aTransition.score || 0)
              )
            : -1;

          bv = bTransition?.available
            ? (
                (priority[String(bTransition.class || '')] || 0) * 10
                + Number(bTransition.score || 0)
              )
            : -1;

        } else {
          av = String(a.genre || '').toLowerCase();
          bv = String(b.genre || '').toLowerCase();
        }

        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;

        return String(a.label || '').localeCompare(
          String(b.label || ''),
          'ru'
        );
      });

      return out;
    }

    function setSort(key) {
      if (sortState.key === key) {
        sortState.dir = sortState.dir === 'asc' ? 'desc' : 'asc';
      } else {
        sortState.key = key;
        sortState.dir = 'asc';
      }
      renderRows();
    }

    function renderRows() {
      renderCrumbs(currentRows.rel || '');
      const box = $('browser');
      box.innerHTML = '';
      renderHeader(box);
      if ((currentRows.rel || '') && currentRows.parent !== undefined) {
        const up = document.createElement('button');
        up.className = 'item folder-row';
        up.innerHTML = '<div></div><div class="folder">..</div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>';
        up.onclick = () => browse(currentRows.parent || '');
        box.appendChild(up);
      }
      currentRows.dirs.forEach(dir => {
        const btn = document.createElement('button');
        btn.className = 'item folder-row';
        btn.innerHTML = `<div></div><div class="folder">${esc(dir.name)}</div><div></div><div></div><div></div><div>Папка</div><div></div><div></div><div></div>`;
        btn.onclick = () => browse(dir.rel);
        box.appendChild(btn);
      });
      sortedTracks(currentRows.tracks || []).forEach(track => box.appendChild(trackRow(track)));
    }

    function renderCrumbs(rel) {
      const box = $('crumbs');
      box.innerHTML = '';
      const root = document.createElement('button');
      root.type = 'button';
      root.textContent = 'Music';
      root.onclick = () => browse('');
      box.appendChild(root);
      let acc = '';
      rel.split('/').filter(Boolean).forEach(part => {
        const sep = document.createElement('span');
        sep.textContent = '/';
        box.appendChild(sep);
        acc = acc ? `${acc}/${part}` : part;
        const targetPath = acc;
        const b = document.createElement('button');
        b.type = 'button';
        b.textContent = part;
        b.onclick = () => browse(targetPath);
        box.appendChild(b);
      });
    }

    async function loadConfig() {
      const res = await fetch('/api/config');
      const cfg = await res.json();
      $('musicRoot').value = cfg.music_root || '';
      $('dbPath').value = cfg.db_path || '';
      const provider = cfg.library_provider || {};
      const repo = cfg.repository_url || 'https://github.com/zmin511/AutoSet';
      $('paths').innerHTML = `
        <span>Версия</span><span>${esc(cfg.app_name || 'AutoSet')} · v${esc(cfg.version || '0.3.0')}</span>
        <span>Библиотека</span><span>${esc(provider.name || 'Denon Engine DJ')} · ${esc(provider.status || '')}</span>
        <span>База</span><span title="${esc(cfg.db_path)}">${esc(cfg.db_path)}</span>
        <span>Сеты</span><span title="${esc(cfg.sets_dir)}">${esc(cfg.sets_dir)}</span>
        <span>GitHub</span><span><a href="${esc(repo)}" target="_blank" rel="noreferrer">AutoSet</a></span>
      `;
      $('status').className = cfg.ready ? 'status ok' : 'status bad';
      $('status').textContent = cfg.ready ? `Готово · ${cfg.startup_refresh || ''}` : 'Не найдена база или builder';
    }

    async function savePaths() {
      $('savePaths').disabled = true;
      $('status').className = 'status';
      $('status').textContent = 'Сохраняю пути...';
      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            music_root: $('musicRoot').value,
            db_path: $('dbPath').value
          })
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || 'save failed');
        currentPath = '';
        selectedTrack = null;
        $('build').disabled = true;
        $('selected').textContent = 'Выбери трек из папки или поиска.';
        await loadConfig();
        await loadStyles();
        await browse('');
        $('status').className = data.ready ? 'status ok' : 'status bad';
        $('status').textContent = data.ready ? 'Пути сохранены' : 'Пути сохранены, но база или папка музыки не найдены';
      } catch (err) {
        $('status').className = 'status bad';
        $('status').textContent = `Ошибка сохранения путей: ${err}`;
      } finally {
        $('savePaths').disabled = false;
      }
    }

    function pickerTitle(kind) {
      return kind === 'db' ? 'Выбор базы Engine DJ' : 'Выбор музыкальной библиотеки';
    }

    function pickerStartPath(kind, value) {
      if (!value) return '';
      if (kind === 'db' && /\.[a-z0-9]+$/i.test(value)) {
        return value.replace(/[\\/][^\\/]*$/, '');
      }
      return value;
    }

    async function openPicker(kind, targetId) {
      picker = { kind, target: targetId, path: pickerStartPath(kind, $(targetId).value), parent: '' };
      $('pickerTitle').textContent = pickerTitle(kind);
      $('pickerSelect').textContent = kind === 'db' ? 'Выбрать эту папку' : 'Выбрать эту папку';
      $('pickerModal').classList.add('open');
      await loadPicker(picker.path);
    }

    function closePicker() {
      $('pickerModal').classList.remove('open');
    }

    async function loadPicker(path) {
      $('pickerList').innerHTML = '';
      $('pickerPath').textContent = 'Загрузка...';
      const res = await fetch(`/api/disk-tree?kind=${encodeURIComponent(picker.kind)}&path=${encodeURIComponent(path || '')}`);
      const data = await res.json();
      if (data.error) {
        $('pickerPath').textContent = data.error;
        return;
      }
      picker.path = data.path || '';
      picker.parent = data.parent || '';
      $('pickerPath').textContent = picker.path || data.root || '';
      $('pickerUp').disabled = !picker.parent;
      renderPicker(data);
    }

    function renderPicker(data) {
      const box = $('pickerList');
      box.innerHTML = '';
      if (picker.parent) {
        const up = document.createElement('button');
        up.className = 'picker-row';
        up.innerHTML = '<span>..</span><span>Вверх</span>';
        up.onclick = () => loadPicker(picker.parent);
        box.appendChild(up);
      }
      (data.dirs || []).forEach(dir => {
        const row = document.createElement('button');
        row.className = 'picker-row';
        row.innerHTML = `<span>DIR</span><span>${esc(dir.name)}</span>`;
        row.title = dir.path;
        row.ondblclick = () => loadPicker(dir.path);
        row.onclick = () => loadPicker(dir.path);
        box.appendChild(row);
      });
      (data.files || []).forEach(file => {
        const row = document.createElement('button');
        row.className = 'picker-row';
        row.innerHTML = `<span>DB</span><span>${esc(file.name)}</span>`;
        row.title = file.path;
        row.onclick = () => {
          $(picker.target).value = file.path;
          closePicker();
        };
        box.appendChild(row);
      });
      if (!box.children.length) {
        const empty = document.createElement('div');
        empty.className = 'picker-path';
        empty.textContent = 'Папка пустая или нет доступных элементов.';
        box.appendChild(empty);
      }
    }

    function selectPickerPath() {
      $(picker.target).value = picker.path;
      closePicker();
    }

    async function browse(rel = currentPath) {
      currentPath = rel || '';
      $('search').value = '';

      styleSuggestions.clear();
      selectedStyleFiles.clear();

      $('status').className = 'status';
      $('status').textContent =
        '\u041e\u0442\u043a\u0440\u044b\u0432\u0430\u044e '
        + '\u043f\u0430\u043f\u043a\u0443...';

      const response = await fetch(
        `/api/browse?path=${encodeURIComponent(currentPath)}`
      );

      const data = await response.json();

      if (data.error) {
        $('status').className = 'status bad';
        $('status').textContent = data.error;
        return;
      }

      currentPath = data.rel || '';
      currentRows = data;

      renderRows();

      await loadTransitionScoresForTracks(
        data.tracks || []
      );

      renderRows();

      $('status').textContent =
        `\u041f\u0430\u043f\u043e\u043a: ${data.dirs.length}, `
        + `\u0442\u0440\u0435\u043a\u043e\u0432: ${data.tracks.length}`;
    }

    async function search() {
      const query = $('search').value.trim();

      if (!query) {
        browse(currentPath);
        return;
      }

      styleSuggestions.clear();
      selectedStyleFiles.clear();

      $('status').className = 'status';
      $('status').textContent =
        '\u041f\u043e\u0438\u0441\u043a...';

      const response = await fetch(
        `/api/search?q=${encodeURIComponent(query)}&limit=${$('limit').value}`
      );

      const data = await response.json();

      $('crumbs').innerHTML =
        `<span>\u041f\u043e\u0438\u0441\u043a: ${esc(query)}</span>`;

      currentRows = {
        rel: '',
        parent: '',
        dirs: [],
        tracks: data.tracks || [],
      };

      renderRows();

      await loadTransitionScoresForTracks(
        data.tracks || []
      );

      renderRows();

      $('status').textContent =
        `\u041d\u0430\u0439\u0434\u0435\u043d\u043e: ${data.tracks.length}`;
    }

    function selectTrack(track) {
      selectedTrack = track;
      $('build').disabled = !track.id;
      $('enginePlaylist').disabled = !track.id;
      lastBuiltSetFolder = '';
      applyInferredStyles(track);
      $('selected').innerHTML = selectedMarkup(track);
      wireGenreSelect();
      updateKeyStepHint();
      preparePlayerForTrack(track);
      warmBlobMediaSource(track);
      updatePlayerBar();
      loadWaveform(track.id);
      if ($('search').value.trim()) search(); else browse(currentPath);
    }

    function playTrack(track) {
      selectedTrack = track;
      applyInferredStyles(track);
      $('selected').innerHTML = selectedMarkup(track, false);
      wireGenreSelect();
      wirePlayerBar();
      $('build').disabled = !track.id;
      $('enginePlaylist').disabled = !track.id;
      lastBuiltSetFolder = '';
      updateKeyStepHint();
      if (!preparePlayerForTrack(track)) return;
      warmBlobMediaSource(track);
      startSelectedPlayback();
      loadWaveform(track.id);
      if ($('search').value.trim()) search(); else browse(currentPath);
    }
