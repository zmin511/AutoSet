// Track Prep rendering and waveform display item sync. Loaded before modules call redrawTrackPrep.
    function renderTrackPrepList() {
      const box = $('trackPrepList');
      if (!box) return;
      const marks = [...(trackPrep.marks || [])].sort((a, b) => {
        const ai = PREP_MARKS.findIndex(m => m.type === a.type);
        const bi = PREP_MARKS.findIndex(m => m.type === b.type);
        return ai - bi;
      });
      const loops = [...(trackPrep.loops || [])].sort((a, b) => Number(a.start_sec) - Number(b.start_sec));
      const rows = [];
      for (const mark of marks) {
        const selected = mark.type === selectedPrepMarkType ? ' selected' : '';
        rows.push(`<span class="prep-item mark${selected}" data-prep-select="mark" data-id="${esc(mark.type)}" title="Select mark">${esc(prepMarkLabel(mark.type))} ${esc(fmtTime(mark.time_sec))}<button class="prep-delete" type="button" data-prep-delete="mark" data-id="${esc(mark.type)}" title="Delete">x</button></span>`);
      }
      for (const loop of loops) {
        const role = loopRoleLabel(loop, true);
        rows.push(`<span class="prep-item loop" title="${esc(loop.length_beats || '')} beats">${esc(role)} ${esc(fmtTime(loop.start_sec))} - ${esc(fmtTime(loop.end_sec))}<button class="prep-delete" type="button" data-prep-delete="loop" data-id="${esc(loop.id)}" title="Delete">x</button></span>`);
      }
      const suggestedMarks = Array.isArray(trackPrepSuggestions?.marks) ? trackPrepSuggestions.marks : [];
      const suggestedLoops = Array.isArray(trackPrepSuggestions?.loops) ? trackPrepSuggestions.loops : [];
      for (const mark of suggestedMarks) {
        const title = [mark.reason, mark.confidence != null ? `confidence ${Number(mark.confidence).toFixed(2)}` : ''].filter(Boolean).join(' · ');
        rows.push(`<span class="prep-item mark suggested" title="${esc(title || 'Suggested mark')}">${esc(prepMarkLabel(mark.type))} ${esc(fmtTime(mark.time_sec))}</span>`);
      }
      for (const loop of suggestedLoops) {
        const role = loopRoleLabel(loop, true);
        const title = [loop.reason, loop.length_beats ? `${loop.length_beats} beats` : '', loop.confidence != null ? `confidence ${Number(loop.confidence).toFixed(2)}` : ''].filter(Boolean).join(' · ');
        rows.push(`<span class="prep-item loop suggested" title="${esc(title || 'Suggested loop')}">${esc(role)} ${esc(fmtTime(loop.start_sec))} - ${esc(fmtTime(loop.end_sec))}</span>`);
      }
      box.innerHTML = rows.length ? rows.join('') : '<span>Нет ручных меток</span>';
    }

    function syncTrackPrepControls() {
      const hasTrack = !!selectedTrackId();
      const hasDetail = !!window.__waveDetail;
      const ready = canNavigateWaveform();
      const hasSuggestions = ((trackPrepSuggestions?.marks || []).length + (trackPrepSuggestions?.loops || []).length) > 0;
      const prep = $('trackPrep');
      if (!prep) return;
      const overwrite = $('trackPrepOverwrite');
      const suggest = $('trackPrepSuggest');
      const accept = $('trackPrepAccept');
      const clearSuggest = $('trackPrepClearSuggest');
      const replaceSuggest = $('trackPrepReplaceSuggest');
      if (overwrite) overwrite.hidden = !trackPrepExportConflict;
      if (suggest) suggest.disabled = !ready || trackPrepSuggestBusy;
      if (accept) accept.disabled = !ready || trackPrepSuggestBusy || !hasSuggestions;
      if (clearSuggest) clearSuggest.disabled = !ready || trackPrepSuggestBusy || !hasSuggestions;
      if (replaceSuggest) {
        replaceSuggest.hidden = !trackPrepSuggestConflict;
        replaceSuggest.disabled = !ready || trackPrepSuggestBusy || !trackPrepSuggestConflict;
      }
      prep.querySelectorAll('button, select').forEach(el => {
        const exportButton = el.id === 'trackPrepExport' || el.id === 'trackPrepOverwrite';
        const suggestButton = el.id === 'trackPrepSuggest' || el.id === 'trackPrepAccept' || el.id === 'trackPrepClearSuggest' || el.id === 'trackPrepReplaceSuggest';
        el.disabled = !ready || (trackPrepExportBusy && exportButton) || (trackPrepSuggestBusy && suggestButton);
      });
      if (overwrite) overwrite.disabled = !ready || !trackPrepExportConflict || trackPrepExportBusy;
      const snap = $('trackPrepSnap');
      if (snap && snap.value !== trackPrepSnap) snap.value = trackPrepSnap;
      if (!hasTrack) prepStatus('Выберите трек Engine');
      else if (!hasDetail) prepStatus('Waveform загружается...');
      else if (!ready) prepStatus('Трек загружается...');
      else if (trackPrepSuggestBusy) prepStatus('Подбираю метки...');
      else if (trackPrepSuggestConflict) prepStatus(trackPrepSuggestConflictText || 'Конфликт подсказок', true);
      else if (trackPrepDirty && hasSuggestions) prepStatus('Есть несохранённые метки; подсказки готовы');
      else if (trackPrepDirty) prepStatus('Есть несохранённые метки');
      else if (trackPrepExportStatus) prepStatus(trackPrepExportStatus, trackPrepExportBad);
      else if (hasSuggestions) {
        const warnings = Array.isArray(trackPrepSuggestions?.warnings) ? trackPrepSuggestions.warnings.filter(Boolean) : [];
        const text = warnings.length ? `Подсказки готовы: ${warnings.join('; ')}` : 'Подсказки готовы';
        prepStatus(text);
      }
      else if (trackPrep.exists) prepStatus('Только AutoSet');
      else prepStatus('Нет сохранённых ручных меток');
    }

    function refreshWaveDisplayItems() {
      const detail = window.__waveDetail;
      const duration = Number(detail?.duration_sec || 0) || playbackDuration();
      const fracFor = (time) => duration > 0 ? Math.max(0, Math.min(1, Number(time) / duration)) : 0;
      window.__waveMarkers = Array.isArray(detail?.beat_grid)
        ? detail.beat_grid.map(b => ({
            kind: 'beat',
            pos_s: Number(b.time_sec),
            pos_frac: fracFor(b.time_sec)
          }))
        : [];

      const engineCues = Array.isArray(detail?.cues) ? detail.cues.map(c => {
        const pos = Number(c?.time_sec);
        return {
          slot: c?.slot,
          label: c?.name || 'Cue',
          name: c?.name || 'Cue',
          pos_s: pos,
          time_sec: pos,
          pos_frac: fracFor(pos),
          color: c?.color || 'rgba(73,160,236,0.95)',
          source: 'engine',
          type: c?.type || 'cue'
        };
      }).filter(c => Number.isFinite(c.pos_frac)) : [];

      const manualCues = (trackPrep.marks || []).map(mark => {
        const pos = Number(mark.time_sec);
        const label = mark.name || prepMarkLabel(mark.type);
        return {
          id: mark.id,
          label,
          name: label,
          pos_s: pos,
          time_sec: pos,
          pos_frac: fracFor(pos),
          color: PREP_MARK_COLORS[mark.type] || '#37c58f',
          source: 'manual',
          type: mark.type
        };
      }).filter(c => Number.isFinite(c.pos_frac));

      const suggestedCues = (trackPrepSuggestions.marks || []).map(mark => {
        const pos = Number(mark.time_sec);
        const label = mark.name || prepMarkLabel(mark.type);
        return {
          id: `suggested_${mark.type}`,
          label,
          name: label,
          pos_s: pos,
          time_sec: pos,
          pos_frac: fracFor(pos),
          color: PREP_MARK_COLORS[mark.type] || '#ffe08a',
          source: 'suggested',
          type: mark.type,
          reason: mark.reason || '',
          confidence: Number(mark.confidence ?? 0)
        };
      }).filter(c => Number.isFinite(c.pos_frac));

      window.__waveCues = [...engineCues, ...manualCues, ...suggestedCues].sort((a, b) => Number(a.pos_s) - Number(b.pos_s));
      window.__waveMarkers.push(...window.__waveCues.map(c => ({
        kind: c.source === 'manual' ? 'prep' : (c.source === 'suggested' ? 'prep' : 'cue'),
        pos_s: Number(c.pos_s),
        pos_frac: Number(c.pos_frac),
        type: c.type,
        source: c.source
      })));

      const engineLoops = Array.isArray(detail?.loops) ? detail.loops.map(l => {
        const s = Number(l?.start_sec);
        const e = Number(l?.end_sec);
        return {
          slot: l?.slot,
          label: l?.name || 'Loop',
          name: l?.name || 'Loop',
          start_s: s,
          end_s: e,
          start_sec: s,
          end_sec: e,
          start_frac: fracFor(s),
          end_frac: fracFor(e),
          color: l?.color || 'rgba(255,138,61,0.82)',
          source: 'engine',
          type: l?.type || 'loop'
        };
      }).filter(l => Number.isFinite(l.start_frac) && Number.isFinite(l.end_frac)) : [];

      const manualLoops = (trackPrep.loops || []).map(loop => {
        const s = Number(loop.start_sec);
        const e = Number(loop.end_sec);
        return {
          id: loop.id,
          label: loop.name || 'Loop',
          name: loop.name || 'Loop',
          start_s: s,
          end_s: e,
          start_sec: s,
          end_sec: e,
          start_frac: fracFor(s),
          end_frac: fracFor(e),
          length_beats: loop.length_beats,
          from_mark_type: loop.from_mark_type,
          color: loop.type === 'EMERGENCY_LOOP' ? 'rgba(239,107,115,0.9)' : 'rgba(255,138,61,0.86)',
          source: 'manual',
          type: loop.type
        };
      }).filter(l => Number.isFinite(l.start_frac) && Number.isFinite(l.end_frac));

      const suggestedLoops = (trackPrepSuggestions.loops || []).map(loop => {
        const s = Number(loop.start_sec);
        const e = Number(loop.end_sec);
        return {
          id: `suggested_${loop.type}_${s.toFixed(3)}`,
          label: loop.name || 'Loop',
          name: loop.name || 'Loop',
          start_s: s,
          end_s: e,
          start_sec: s,
          end_sec: e,
          start_frac: fracFor(s),
          end_frac: fracFor(e),
          length_beats: loop.length_beats,
          from_mark_type: loop.from_mark_type,
          color: loop.type === 'EMERGENCY_LOOP' ? 'rgba(239,107,115,0.9)' : 'rgba(255,224,108,0.92)',
          source: 'suggested',
          type: loop.type,
          reason: loop.reason || '',
          confidence: Number(loop.confidence ?? 0)
        };
      }).filter(l => Number.isFinite(l.start_frac) && Number.isFinite(l.end_frac));

      window.__waveLoops = [...engineLoops, ...manualLoops, ...suggestedLoops].sort((a, b) => Number(a.start_s) - Number(b.start_s));
    }

    function redrawTrackPrep() {
      refreshWaveDisplayItems();
      renderTrackPrepList();
      syncTrackPrepControls();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    }



