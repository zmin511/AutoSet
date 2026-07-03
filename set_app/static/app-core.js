    const $ = (id) => document.getElementById(id);
    let selectedTrack = null;
    let currentPath = '';
    let timer = null;
    let playingPath = '';
    let audioPreparingTrackId = 0;
    let audioReadyTrackId = 0;
    let audioFallbackTrackId = 0;
    let audioLoadingTrackId = 0;
    let audioFallbackTimer = null;
    let audioPendingSeekSec = null;
    let playbackCursorSec = 0;
    let playbackCursorPinned = false;
    let mediaBlobUrl = '';
    let mediaBlobPath = '';
    let mediaBlobWarmupTrackId = 0;
    let mediaBlobWarmupPath = '';
    let mediaBlobWarmupPromise = null;
    let playbackStartSeq = 0;
    let webAudioCtx = null;
    let webAudioGain = null;
    let webAudioSource = null;
    let webAudioBuffer = null;
    let webAudioPath = '';
    let webAudioStartedAt = 0;
    let webAudioOffsetSec = 0;
    let webAudioPlaying = false;
    let webAudioTimer = null;
    let webAudioSeekTimer = null;
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
        <div>Название / путь</div>
        <div></div>
        <button class="sort-head ${sortState.key === 'genre' ? 'active' : ''}" data-sort="genre">Жанр ${sortState.key === 'genre' ? (sortState.dir === 'asc' ? '↑' : '↓') : ''}</button>
        <div>Подстили</div>
        <button class="sort-head ${sortState.key === 'energy' ? 'active' : ''}" data-sort="energy">Энергия ${sortState.key === 'energy' ? (sortState.dir === 'asc' ? '↑' : '↓') : ''}</button>
        <button class="sort-head ${sortState.key === 'camelot' ? 'active' : ''}" data-sort="camelot">Key ${sortState.key === 'camelot' ? (sortState.dir === 'asc' ? '↑' : '↓') : ''}</button>
        <button class="sort-head ${sortState.key === 'bpm' ? 'active' : ''}" data-sort="bpm">BPM ${sortState.key === 'bpm' ? (sortState.dir === 'asc' ? '↑' : '↓') : ''}</button>
        <button class="sort-head ${sortState.key === 'length' ? 'active' : ''}" data-sort="length">Длит. ${sortState.key === 'length' ? (sortState.dir === 'asc' ? '↑' : '↓') : ''}</button>
      `;
      head.querySelectorAll('[data-sort]').forEach(btn => {
        btn.onclick = (event) => {
          event.stopPropagation();
          setSort(btn.dataset.sort);
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
        } else {
          av = String(a.genre || '').toLowerCase();
          bv = String(b.genre || '').toLowerCase();
        }
        if (av < bv) return -1 * dir;
        if (av > bv) return 1 * dir;
        return String(a.label || '').localeCompare(String(b.label || ''), 'ru');
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
        up.className = 'item';
        up.innerHTML = '<div></div><div class="folder">..</div><div></div><div></div><div></div><div></div><div></div><div></div><div></div>';
        up.onclick = () => browse(currentRows.parent || '');
        box.appendChild(up);
      }
      currentRows.dirs.forEach(dir => {
        const btn = document.createElement('button');
        btn.className = 'item';
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
      $('status').textContent = 'Открываю папку...';
      const res = await fetch(`/api/browse?path=${encodeURIComponent(currentPath)}`);
      const data = await res.json();
      if (data.error) {
        $('status').className = 'status bad';
        $('status').textContent = data.error;
        return;
      }
      currentPath = data.rel || '';
      currentRows = data;
      renderRows();
      $('status').textContent = `Папок: ${data.dirs.length}, треков: ${data.tracks.length}`;
    }

    async function search() {
      const q = $('search').value.trim();
      if (!q) {
        browse(currentPath);
        return;
      }
      styleSuggestions.clear();
      selectedStyleFiles.clear();
      $('status').className = 'status';
      $('status').textContent = 'Поиск...';
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&limit=${$('limit').value}`);
      const data = await res.json();
      $('crumbs').innerHTML = `<span>Поиск: ${esc(q)}</span>`;
      currentRows = { rel: '', parent: '', dirs: [], tracks: data.tracks || [] };
      renderRows();
      $('status').textContent = `Найдено: ${data.tracks.length}`;
    }

    function selectedTrackId(track = selectedTrack) {
      const id = Number(track?.id || 0);
      return Number.isFinite(id) && id > 0 ? id : 0;
    }

    function playbackDuration() {
      const player = $('player');
      const candidates = [
        Number(window.__waveDetail?.duration_sec || 0),
        Number(selectedTrack?.length || 0),
        Number(webAudioBuffer?.duration || 0),
        player ? Number(player.duration) : 0
      ];
      for (const value of candidates) {
        if (Number.isFinite(value) && value > 0) return value;
      }
      return 0;
    }

    function durationForSeek() {
      const candidates = [
        Number(window.__waveDetail?.duration_sec || 0),
        Number(selectedTrack?.length || 0),
        Number(webAudioBuffer?.duration || 0),
        Number($('player')?.duration || 0)
      ];
      for (const value of candidates) {
        if (Number.isFinite(value) && value > 0) return value;
      }
      return 0;
    }

    function pinPlaybackCursor(timeSec, options = {}) {
      const duration = durationForSeek() || playbackDuration();
      const raw = Number(timeSec);
      const t = Math.max(0, Math.min(duration || Math.max(0, raw || 0), Number.isFinite(raw) ? raw : 0));
      playbackCursorSec = t;
      playbackCursorPinned = true;
      audioPendingSeekSec = t;
      webAudioOffsetSec = t;
      waveLastFrac = duration > 0 ? t / duration : 0;
      if (options.centerZoom) centerZoomOnTime(t);
      else if (followPlayhead) updateFollowWaveWindow();
      syncWaveScrollControl();
      updatePlayerBar();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
      return t;
    }

    function pendingSeekTime() {
      if (audioPendingSeekSec === null || audioPendingSeekSec === undefined || audioPendingSeekSec === '') return null;
      const pending = Number(audioPendingSeekSec);
      return Number.isFinite(pending) && pending >= 0 ? pending : null;
    }

    function currentPlaybackTime() {
      const player = $('player');
      const dur = playbackDuration();
      if (webAudioPlaying) {
        const webCur = currentWebAudioTime();
        if (Number.isFinite(webCur) && webCur >= 0) {
          playbackCursorSec = webCur;
          playbackCursorPinned = true;
          return dur > 0 ? Math.min(dur, webCur) : webCur;
        }
      }
      const cur = Number(player?.currentTime);
      const cursor = Number(playbackCursorSec);
      const hasPinned = playbackCursorPinned && Number.isFinite(cursor) && cursor >= 0;
      const pending = pendingSeekTime();
      // If browser fired play but the audio is still near 0 while a later seek is pending,
      // keep the user-selected red cursor instead of snapping the UI back to the start.
      if (player && !player.paused && Number.isFinite(cur) && cur >= 0) {
        if (pending != null && cur < pending - 0.75) return Math.min(dur || pending, pending);
        if (pending == null && hasPinned && cursor > 1 && cur < 1 && cur < cursor - 0.75) return Math.min(dur || cursor, cursor);
        playbackCursorSec = cur;
        playbackCursorPinned = true;
        return cur;
      }
      if (pending != null) return Math.min(dur || pending, pending);
      if (hasPinned) return Math.min(dur || cursor, cursor);
      if (Number.isFinite(cur) && cur > 0) return cur;
      return 0;
    }

    function clearAudioFallbackTimer() {
      if (audioFallbackTimer) window.clearTimeout(audioFallbackTimer);
      audioFallbackTimer = null;
    }

    function audioNavigationReady() {
      const trackId = selectedTrackId();
      if (!trackId) return false;
      if (audioReadyTrackId === trackId || audioFallbackTrackId === trackId) return true;
      const player = $('player');
      return !!player && player.readyState >= 1 && playbackDuration() > 0;
    }

    function canNavigateWaveform() {
      // Navigation must work as soon as a track and duration are known, even before
      // HTML audio/WebAudio has started. Do not require audio readiness here.
      return !!selectedTrackId() && durationForSeek() > 0;
    }

    function applyPendingSeekIfReady() {
      const player = $('player');
      const pending = pendingSeekTime();
      if (!player || pending == null || player.readyState < 1) return;
      const duration = playbackDuration();
      const target = Math.max(0, Math.min(duration || pending, pending));
      try {
        player.currentTime = target;
        playbackCursorSec = target;
        playbackCursorPinned = true;
        audioPendingSeekSec = null;
      } catch {}
    }

    function markAudioReadyForTrack(trackId, fallback = false) {
      trackId = Number(trackId) || 0;
      if (!trackId || trackId !== selectedTrackId()) return;
      if (fallback) audioFallbackTrackId = trackId;
      else {
        audioReadyTrackId = trackId;
        audioFallbackTrackId = 0;
      }
      audioLoadingTrackId = 0;
      clearAudioFallbackTimer();
      applyPendingSeekIfReady();
      updatePlayerBar();
      syncTrackPrepControls();
      syncWaveScrollControl();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    }

    function maybeEnableAudioFallback(trackId) {
      trackId = Number(trackId) || 0;
      if (!trackId || trackId !== selectedTrackId()) return;
      if (audioReadyTrackId === trackId) return;
      if (playbackDuration() > 0) markAudioReadyForTrack(trackId, true);
    }

    function currentCursorSnapshot(defaultTime = 0) {
      const pending = pendingSeekTime();
      if (pending != null) return pending;
      const cursor = Number(playbackCursorSec);
      if (playbackCursorPinned && Number.isFinite(cursor) && cursor >= 0) return cursor;
      const player = $('player');
      const cur = Number(player?.currentTime);
      if (Number.isFinite(cur) && cur >= 0) return cur;
      return Math.max(0, Number(defaultTime) || 0);
    }

    function restoreCursorSnapshot(timeSec, options = {}) {
      const duration = durationForSeek() || playbackDuration();
      const raw = Number(timeSec);
      const t = Math.max(0, Math.min(duration || Math.max(0, raw || 0), Number.isFinite(raw) ? raw : 0));
      playbackCursorSec = t;
      playbackCursorPinned = true;
      audioPendingSeekSec = t;
      webAudioOffsetSec = t;
      waveLastFrac = duration > 0 ? t / duration : 0;
      if (options.centerZoom) centerZoomOnTime(t);
      return t;
    }

    function warmBlobMediaSource(track = selectedTrack) {
      const player = $('player');
      const trackId = selectedTrackId(track);
      const mediaPath = mediaPathForTrack(track);
      if (!trackId || !mediaPath) return Promise.resolve(false);
      if (mediaBlobUrl && mediaBlobPath === mediaPath) {
        audioFallbackTrackId = trackId;
        return Promise.resolve(true);
      }
      if (mediaBlobWarmupTrackId === trackId && mediaBlobWarmupPath === mediaPath && mediaBlobWarmupPromise) return mediaBlobWarmupPromise;
      mediaBlobWarmupTrackId = trackId;
      mediaBlobWarmupPath = mediaPath;
      mediaBlobWarmupPromise = (async () => {
        const res = await fetch(`/media?path=${encodeURIComponent(mediaPath)}&warmup=1`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`/media ${res.status}`);
        const blob = await res.blob();
        if (selectedTrackId() !== trackId || mediaPathForTrack(selectedTrack) !== mediaPath) return false;
        if (mediaBlobUrl) {
          try { URL.revokeObjectURL(mediaBlobUrl); } catch {}
        }
        mediaBlobUrl = URL.createObjectURL(blob);
        mediaBlobPath = mediaPath;
        audioFallbackTrackId = trackId;
        if (player && player.paused && !webAudioPlaying) {
          const keep = currentCursorSnapshot(0);
          player.src = mediaBlobUrl;
          player.preload = 'auto';
          player.muted = false;
          restoreCursorSnapshot(keep);
          try { player.load(); } catch {}
          waitForAudioReady(player, 1800).then(() => markAudioReadyForTrack(trackId, true)).catch(() => maybeEnableAudioFallback(trackId));
        } else {
          maybeEnableAudioFallback(trackId);
        }
        return true;
      })().catch((err) => {
        console.warn('audio warmup failed', err);
        return false;
      }).finally(() => {
        if (mediaBlobWarmupTrackId === trackId && mediaBlobWarmupPath === mediaPath) mediaBlobWarmupPromise = null;
      });
      return mediaBlobWarmupPromise;
    }

    function preparePlayerForTrack(track, options = {}) {
      const player = $('player');
      const trackId = selectedTrackId(track);
      if (!player || !trackId) return false;
      const preserveCursor = !!options.preserveCursor;
      const savedCursor = currentCursorSnapshot(0);
      const before = player.getAttribute('src') || '';
      if (!setPlayerSource(track)) return false;
      const after = player.getAttribute('src') || '';
      const changed = before !== after;
      const alreadyPreparing = !changed && audioPreparingTrackId === trackId;
      audioPreparingTrackId = trackId;
      audioLoadingTrackId = trackId;
      if (!alreadyPreparing) {
        stopWebAudioPlayback(false);
        if (webAudioPath && webAudioPath !== mediaPathForTrack(track)) {
          webAudioBuffer = null;
          webAudioPath = '';
        }
        audioReadyTrackId = 0;
        audioFallbackTrackId = 0;
        if (preserveCursor) {
          restoreCursorSnapshot(savedCursor);
        } else {
          audioPendingSeekSec = null;
          playbackCursorSec = 0;
          playbackCursorPinned = false;
          webAudioOffsetSec = 0;
        }
        clearAudioFallbackTimer();
      }
      updatePlayerBar();
      syncTrackPrepControls();
      syncWaveScrollControl();
      if (!changed && playbackDuration() > 0 && (player.readyState >= 1 || audioNavigationReady())) {
        markAudioReadyForTrack(trackId, player.readyState < 1);
        return true;
      }
      if (!alreadyPreparing) {
        try { player.load(); } catch {}
      }
      if (!audioFallbackTimer) {
        audioFallbackTimer = window.setTimeout(() => maybeEnableAudioFallback(trackId), 900);
      }
      return true;
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

    function setPlayerSource(track) {
      const mediaPath = mediaPathForTrack(track);
      if (!mediaPath) return false;
      playingPath = mediaPath;
      const player = $('player');
      if (!player) return false;
      if (mediaBlobUrl && mediaBlobPath && mediaBlobPath !== mediaPath) {
        try { URL.revokeObjectURL(mediaBlobUrl); } catch {}
        mediaBlobUrl = '';
        mediaBlobPath = '';
      }
      if (mediaBlobUrl && mediaBlobPath === mediaPath) {
        if (player.src !== mediaBlobUrl) player.src = mediaBlobUrl;
      } else {
        const src = `/media?path=${encodeURIComponent(mediaPath)}`;
        const absoluteSrc = new URL(src, window.location.href).href;
        if (player.src !== absoluteSrc) player.src = absoluteSrc;
      }
      player.preload = 'auto';
      player.muted = false;
      return true;
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

