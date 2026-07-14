// Batch Track Prep suggestions. Loaded after app-prep.js so it can use shared AutoSet state.

    function batchTrackResult(trackId) {
      return batchTrackMap.get(Number(trackId) || 0) || null;
    }

    function batchScopeTracks() {
      const visible = Array.isArray(currentRows.tracks) ? currentRows.tracks : [];
      const selected = visible.filter(track => batchTrackIds.has(Number(track.id)));
      return selected.length ? selected : visible;
    }

    function batchSuggestionValue(result, type, field = 'time_sec') {
      const list = Array.isArray(result?.suggestions?.marks) ? result.suggestions.marks : [];
      const mark = list.find(item => String(item?.type || '').toUpperCase() === type);
      if (mark && field === 'time_sec') return Number(mark.time_sec);
      const loops = Array.isArray(result?.suggestions?.loops) ? result.suggestions.loops : [];
      const loop = loops.find(item => String(item?.type || '').toUpperCase() === type);
      if (!loop) return null;
      if (field === 'range') return Number.isFinite(Number(loop.start_sec)) && Number.isFinite(Number(loop.end_sec))
        ? `${fmtTime(loop.start_sec)} - ${fmtTime(loop.end_sec)}`
        : null;
      if (field === 'start_sec') return Number(loop.start_sec);
      if (field === 'end_sec') return Number(loop.end_sec);
      return null;
    }

    function batchResultStatusText(result) {
      if (!result) return 'Пусто';
      if (result.batch_status === 'saved') return 'Сохранено';
      if (result.batch_status === 'conflict') return result.batch_message || 'Конфликт';
      if (result.batch_status === 'error') return result.batch_message || 'Ошибка';
      if (!result.ok) return 'Ошибка';
      return 'Предпросмотр';
    }

    function renderBatchSuggestPanel() {
      const box = $('batchSuggestTable');
      if (!box) return;
      const rows = [];
      rows.push(`
        <div class="batch-suggest-row head">
          <div class="batch-suggest-cell"></div>
          <div class="batch-suggest-cell">Трек</div>
          <div class="batch-suggest-cell">IN</div>
          <div class="batch-suggest-cell">OUT</div>
          <div class="batch-suggest-cell">OUTRO LOOP</div>
          <div class="batch-suggest-cell">АВАРИЙНАЯ</div>
          <div class="batch-suggest-cell">Оценка</div>
          <div class="batch-suggest-cell">Замечания</div>
          <div class="batch-suggest-cell">Статус</div>
          <div class="batch-suggest-cell"></div>
        </div>
      `);
      if (!batchTrackSuggestions.length) {
        rows.push('<div class="empty">Пакетный предпросмотр не загружен.</div>');
        box.innerHTML = rows.join('');
        return;
      }
      for (const result of batchTrackSuggestions) {
        const mixIn = batchSuggestionValue(result, 'MIX_IN');
        const mixOut = batchSuggestionValue(result, 'MIX_OUT');
        const outroLoop = batchSuggestionValue(result, 'OUTRO_LOOP', 'range');
        const emergencyLoop = batchSuggestionValue(result, 'EMERGENCY_LOOP', 'range');
        const warnings = Array.isArray(result.warnings) && result.warnings.length ? result.warnings.join('; ') : '';
        const title = `${result.artist || ''}${result.artist && result.title ? ' - ' : ''}${result.title || result.filename || ''}`.trim() || `Track ${result.track_id}`;
        const checked = result.selected ? 'checked' : '';
        const status = batchResultStatusText(result);
        const statusClass = result.batch_status || (result.ok ? 'preview' : 'error');
        rows.push(`
          <div class="batch-suggest-row" data-track-id="${esc(result.track_id)}" data-status="${esc(statusClass)}">
            <div class="batch-suggest-cell"><input type="checkbox" data-batch-result-select="1" data-track-id="${esc(result.track_id)}" ${checked}></div>
            <div class="batch-suggest-cell wrap" title="${esc(title)}">${esc(title)}</div>
            <div class="batch-suggest-cell">${Number.isFinite(Number(mixIn)) ? esc(fmtTime(mixIn)) : '<span class="muted">-</span>'}</div>
            <div class="batch-suggest-cell">${Number.isFinite(Number(mixOut)) ? esc(fmtTime(mixOut)) : '<span class="muted">-</span>'}</div>
            <div class="batch-suggest-cell">${outroLoop ? esc(outroLoop) : '<span class="muted">-</span>'}</div>
            <div class="batch-suggest-cell">${emergencyLoop ? esc(emergencyLoop) : '<span class="muted">-</span>'}</div>
            <div class="batch-suggest-cell">${result.confidence != null ? esc(Number(result.confidence).toFixed(2)) : '<span class="muted">-</span>'}</div>
            <div class="batch-suggest-cell wrap" title="${esc(warnings)}">${warnings ? esc(warnings) : '<span class="muted">-</span>'}</div>
            <div class="batch-suggest-cell">${esc(status)}</div>
            <div class="batch-suggest-cell"><button type="button" data-batch-open-track="${esc(result.track_id)}">Открыть</button></div>
          </div>
        `);
      }
      box.innerHTML = rows.join('');
    }

    function syncBatchSuggestControls() {
      const hasResults = batchTrackSuggestions.length > 0;
      const anySelected = batchTrackSuggestions.some(item => item.selected !== false && item.ok !== false);
      const hasVisible = (currentRows.tracks || []).length > 0;
      const runBtn = $('batchSuggestRun');
      const acceptBtn = $('batchSuggestAccept');
      const replaceBtn = $('batchSuggestReplace');
      const openBtn = $('batchSuggestOpen');
      const clearBtn = $('batchSuggestClear');
      if (runBtn) runBtn.disabled = batchTrackBusy || !hasVisible;
      if (acceptBtn) acceptBtn.disabled = batchTrackBusy || !hasResults || !anySelected;
      if (replaceBtn) replaceBtn.disabled = batchTrackBusy || !hasResults || !anySelected;
      if (openBtn) openBtn.disabled = batchTrackBusy || !hasResults || !anySelected;
      if (clearBtn) clearBtn.disabled = batchTrackBusy || !hasResults;
      const status = $('batchSuggestStatus');
      if (status) {
        if (batchTrackBusy) status.textContent = 'Анализирую треки...';
        else if (batchTrackWarnings.length) status.textContent = batchTrackWarnings.join('; ');
        else if (hasResults) status.textContent = `${batchTrackSuggestions.length} треков в предпросмотре`;
        else status.textContent = 'Нет пакетного предпросмотра';
      }
      renderBatchSuggestPanel();
    }

    function clearBatchSuggestState(clearPreview = true) {
      batchTrackBusy = false;
      batchTrackWarnings = [];
      batchTrackSuggestions = [];
      batchTrackMap = new Map();
      batchPreviewTrackId = 0;
      batchPreviewMode = '';
      if (clearPreview && trackPrepSuggestions && (trackPrepSuggestions.marks?.length || trackPrepSuggestions.loops?.length)) {
        clearTrackPrepSuggestionsState();
        redrawTrackPrep();
      }
      syncBatchSuggestControls();
    }

    function applyBatchPreviewToCurrentTrack(trackId) {
      const result = batchTrackResult(trackId);
      if (!result || !result.ok) return false;
      batchPreviewMode = 'batch';
      applyTrackPrepSuggestions(result);
      return true;
    }

    function batchTrackMetaPayload(result) {
      return {
        track_id: Number(result.track_id) || 0,
        file_path: result.file_path || result.path || '',
        duration_sec: Number(result.duration_sec || 0) || 0,
        bpm: Number.isFinite(Number(result.bpm)) ? Number(result.bpm) : null,
        marks: (result.suggestions?.marks || []).map(item => ({ ...item, source: 'manual' })),
        loops: (result.suggestions?.loops || []).map(item => ({ ...item, source: 'manual' })),
        source: 'manual',
        confidence: Number(result.confidence ?? 1)
      };
    }

    async function openBatchTrack(trackId) {
      const id = Number(trackId) || 0;
      const result = batchTrackResult(id);
      const track = (currentRows.tracks || []).find(item => Number(item.id) === id) || (result ? {
        id,
        label: result.title || result.filename || `Track ${id}`,
        filename: result.filename || result.title || `Track ${id}`,
        path: result.file_path || result.path || '',
        rel: result.rel || '',
        genre: result.genre || '',
        bpm: result.bpm || '',
        camelot: result.camelot || '',
        length: result.length || result.duration_sec || 0,
      } : null);
      if (!track) return;
      batchPreviewTrackId = id;
      batchPreviewMode = 'batch';
      selectTrack(track);
    }

    async function batchSuggestTracks() {
      const tracks = batchScopeTracks();
      const ids = tracks.map(track => Number(track.id) || 0).filter(Boolean);
      if (!ids.length) {
        prepStatus('Нет видимых треков для анализа', true);
        return;
      }
      batchTrackBusy = true;
      batchTrackWarnings = [];
      syncBatchSuggestControls();
      try {
        const res = await fetch('/api/batch_suggest_track_marks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track_ids: ids })
        });
        const data = await res.json();
        if (!data?.ok) throw new Error(data?.error || data?.reason || 'Пакетный подбор не удался');
        batchTrackWarnings = Array.isArray(data.warnings) ? data.warnings.map(w => String(w)).filter(Boolean) : [];
        batchTrackSuggestions = (data.results || []).map(item => ({
          ...item,
          selected: item.ok !== false,
          batch_status: item.ok === false ? 'error' : 'preview',
          batch_message: item.ok === false ? (item.error || 'Ошибка') : ''
        }));
        batchTrackMap = new Map(batchTrackSuggestions.map(item => [Number(item.track_id) || 0, item]));
        batchPreviewTrackId = 0;
        batchPreviewMode = '';
        syncBatchSuggestControls();
      } catch (err) {
        batchTrackBusy = false;
        batchTrackWarnings = [String(err)];
        syncBatchSuggestControls();
      } finally {
        batchTrackBusy = false;
        syncBatchSuggestControls();
      }
    }

    async function acceptBatchSuggestions(replaceExisting = false) {
      const selected = batchTrackSuggestions.filter(item => item.selected !== false && item.ok !== false);
      if (!selected.length) return;
      batchTrackBusy = true;
      syncBatchSuggestControls();
      try {
        for (const item of selected) {
          const existingRes = await fetch(`/api/track_marks?track_id=${encodeURIComponent(item.track_id)}`);
          const existing = await existingRes.json();
          if (!replaceExisting && existing?.exists) {
            item.batch_status = 'conflict';
            item.batch_message = 'Marks already saved';
            continue;
          }
          const payload = batchTrackMetaPayload(item);
          const saveRes = await fetch('/api/track_marks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const saveData = await saveRes.json();
          if (!saveData?.ok) throw new Error(saveData?.error || 'Не удалось сохранить');
          item.batch_status = 'saved';
          item.batch_message = replaceExisting ? 'Заменено и сохранено' : 'Сохранено';
        }
      } catch (err) {
        batchTrackWarnings = [String(err)];
      } finally {
        batchTrackBusy = false;
        syncBatchSuggestControls();
      }
    }

    function clearBatchPreview() {
      if (batchPreviewMode === 'batch') {
        clearTrackPrepSuggestionsState();
        redrawTrackPrep();
      }
      clearBatchSuggestState(false);
      renderBatchSuggestPanel();
    }

