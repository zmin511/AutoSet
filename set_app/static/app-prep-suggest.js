// Single-track Track Prep suggestions. Loaded before batch because batch preview reuses applyTrackPrepSuggestions.
    function clearTrackPrepSuggestionsState() {
      trackPrepSuggestions = { marks: [], loops: [], warnings: [] };
      trackPrepSuggestBusy = false;
      trackPrepSuggestConflict = false;
      trackPrepSuggestConflictText = '';
    }

    function normalizeTrackPrepSuggestionMark(mark) {
      const base = normalizePrepMark({ ...mark, source: 'suggested' });
      if (!base) return null;
      return { ...base, source: 'suggested', reason: String(mark?.reason || '') };
    }

    function normalizeTrackPrepSuggestionLoop(loop) {
      const base = normalizePrepLoop({ ...loop, source: 'suggested' });
      if (!base) return null;
      return { ...base, source: 'suggested', reason: String(loop?.reason || '') };
    }

    function applyTrackPrepSuggestions(data) {
      const marks = (data?.suggestions?.marks || data?.marks || []).map(normalizeTrackPrepSuggestionMark).filter(Boolean);
      const loops = (data?.suggestions?.loops || data?.loops || []).map(normalizeTrackPrepSuggestionLoop).filter(Boolean);
      trackPrepSuggestions = {
        marks,
        loops,
        warnings: Array.isArray(data?.warnings) ? data.warnings.map(w => String(w)).filter(Boolean) : []
      };
      trackPrepSuggestBusy = false;
      trackPrepSuggestConflict = false;
      trackPrepSuggestConflictText = '';
      redrawTrackPrep();
      syncTrackPrepControls();
    }





    function trackPrepSuggestionConflictMessage(kind, type) {
      if (kind === 'loop') {
        return `${String(type || '').toUpperCase() === 'EMERGENCY_LOOP' ? 'EMERGENCY LOOP' : 'OUTRO LOOP'} уже есть`;
      }
      return `${prepMarkLabel(type)} уже есть`;
    }

    function trackPrepHasSuggestionConflicts(replaceExisting = false) {
      const markConflicts = [];
      for (const mark of (trackPrepSuggestions.marks || [])) {
        if ((trackPrep.marks || []).some(existing => String(existing.type || '').toUpperCase() === String(mark.type || '').toUpperCase())) {
          markConflicts.push(mark);
        }
      }
      const loopConflicts = [];
      for (const loop of (trackPrepSuggestions.loops || [])) {
        if ((trackPrep.loops || []).some(existing => String(existing.type || '').toUpperCase() === String(loop.type || '').toUpperCase())) {
          loopConflicts.push(loop);
        }
      }
      if (!replaceExisting && (markConflicts.length || loopConflicts.length)) {
        const first = markConflicts[0] || loopConflicts[0];
        const kind = markConflicts[0] ? 'cue' : 'loop';
        trackPrepSuggestConflict = true;
        trackPrepSuggestConflictText = first ? trackPrepSuggestionConflictMessage(kind, first.type) : 'Конфликт подсказок';
        syncTrackPrepControls();
        return true;
      }
      return false;
    }

    async function suggestTrackPrepMarks() {
      if (!selectedTrack?.id || !window.__waveDetail) return;
      batchPreviewMode = 'single';
      batchPreviewTrackId = 0;
      trackPrepSuggestBusy = true;
      trackPrepSuggestConflict = false;
      trackPrepSuggestConflictText = '';
      syncTrackPrepControls();
      try {
        const res = await fetch('/api/suggest_track_marks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track_id: selectedTrack.id })
        });
        const data = await res.json();
        if (!data?.ok) throw new Error(data?.error || data?.reason || 'Не удалось подобрать метки');
        applyTrackPrepSuggestions(data);
      } catch (err) {
        trackPrepSuggestBusy = false;
        prepStatus(`Не удалось подобрать метки: ${err}`, true);
        syncTrackPrepControls();
      }
    }

    function acceptTrackPrepSuggestions(replaceExisting = false) {
      if (!selectedTrack?.id || !window.__waveDetail) return;
      const marks = Array.isArray(trackPrepSuggestions?.marks) ? trackPrepSuggestions.marks : [];
      const loops = Array.isArray(trackPrepSuggestions?.loops) ? trackPrepSuggestions.loops : [];
      if (!marks.length && !loops.length) return;
      if (trackPrepHasSuggestionConflicts(replaceExisting)) return;

      if (replaceExisting) {
        const markTypes = new Set(marks.map(mark => String(mark.type || '').toUpperCase()));
        const loopTypes = new Set(loops.map(loop => String(loop.type || '').toUpperCase()));
        trackPrep.marks = (trackPrep.marks || []).filter(mark => !markTypes.has(String(mark.type || '').toUpperCase()));
        trackPrep.loops = (trackPrep.loops || []).filter(loop => !loopTypes.has(String(loop.type || '').toUpperCase()));
      }

      for (const mark of marks) {
        const payload = normalizePrepMark({
          type: mark.type,
          name: mark.name || prepMarkLabel(mark.type),
          time_sec: mark.time_sec,
          raw_time_sec: mark.raw_time_sec,
          snap: mark.snap || trackPrepSnap,
          confidence: Number(mark.confidence ?? 1),
          source: 'manual'
        });
        if (payload) trackPrep.marks.push(payload);
      }
      for (const loop of loops) {
        const payload = normalizePrepLoop({
          type: loop.type,
          name: loop.name || (loop.type === 'EMERGENCY_LOOP' ? 'EMERGENCY LOOP' : 'OUTRO LOOP'),
          start_sec: loop.start_sec,
          end_sec: loop.end_sec,
          raw_start_sec: loop.raw_start_sec,
          length_beats: loop.length_beats,
          from_mark_type: loop.from_mark_type,
          confidence: Number(loop.confidence ?? 1),
          source: 'manual'
        });
        if (payload) trackPrep.loops.push(payload);
      }

      clearTrackPrepSuggestionsState();
      selectedPrepMarkType = (trackPrep.marks[0] && trackPrep.marks[0].type) || selectedPrepMarkType;
      clearTrackPrepExportState();
      trackPrepDirty = true;
      redrawTrackPrep();
      prepStatus(replaceExisting ? 'Подсказки приняты и заменили старые метки' : 'Подсказки приняты; сохраните метки');
    }

    function clearTrackPrepSuggestions() {
      clearTrackPrepSuggestionsState();
      batchPreviewMode = '';
      batchPreviewTrackId = 0;
      redrawTrackPrep();
      prepStatus('Подсказки очищены');
    }


