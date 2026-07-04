// Manual Track Prep actions. Loaded after app-prep.js so it can use shared AutoSet state.
    async function resetTrackPrepMarks() {
      if (!selectedTrack?.id) return;
      if (!window.confirm('Сбросить ручные метки и петли для этого трека?')) return;
      const btn = $('trackPrepReset');
      if (btn) btn.disabled = true;
      try {
        await fetch(`/api/track_marks?track_id=${encodeURIComponent(selectedTrack.id)}`, { method: 'DELETE' });
      } catch {}
      resetTrackPrepState();
      refreshWaveDisplayItems();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
      prepStatus('Manual marks reset');
    }

    function addTrackPrepMark(type) {
      if (!window.__waveDetail) return;
      const markType = String(type || '').toUpperCase();
      if (!PREP_MARKS.some(item => item.type === markType)) return;
      const raw = clampTrackTime(currentPlaybackTime());
      const snapped = snapTargetForPlacement(raw);
      const existing = (trackPrep.marks || []).findIndex(mark => mark.type === markType);
      if (existing >= 0 && !window.confirm(`${prepMarkLabel(markType)} уже есть. Заменить?`)) return;
      clearTrackPrepExportState();
      const mark = normalizePrepMark({
        type: markType,
        name: prepMarkLabel(markType),
        time_sec: snapped,
        raw_time_sec: raw,
        snap: trackPrepSnap,
        confidence: 1
      });
      if (!mark) return;
      if (existing >= 0) trackPrep.marks.splice(existing, 1, mark);
      else trackPrep.marks.push(mark);
      selectedPrepMarkType = mark.type;
      trackPrepDirty = true;
      redrawTrackPrep();
    }

    function addTrackPrepLoop(lengthBeats) {
      if (!window.__waveDetail) return;
      const beats = Math.max(1, Math.min(512, Number(lengthBeats) || 0));
      const beatSec = estimateBeatSeconds();
      if (!(beatSec > 0)) {
        prepStatus('Для петель нужен BPM или beat-grid', true);
        return;
      }
      const anchorMark = selectedPrepMark();
      const raw = clampTrackTime(anchorMark ? Number(anchorMark.time_sec) : currentPlaybackTime());
      const start = snapTargetForPlacement(raw);
      const end = clampTrackTime(start + beatSec * beats);
      if (!(end > start)) {
        prepStatus('Конец петли выходит за длительность трека', true);
        return;
      }
      const type = $('trackPrepLoopType')?.value === 'EMERGENCY_LOOP' ? 'EMERGENCY_LOOP' : 'OUTRO_LOOP';
      const role = type === 'EMERGENCY_LOOP' ? 'Аварийная петля' : 'Loop';
      const loop = normalizePrepLoop({
        id: `${type.toLowerCase()}_${beats}_${Math.round(start * 1000)}`,
        type,
        name: `${role} ${beats}`,
        start_sec: start,
        end_sec: end,
        raw_start_sec: anchorMark ? start : raw,
        length_beats: beats,
        snap: trackPrepSnap,
        from_mark_type: anchorMark?.type || undefined,
        confidence: 1
      });
      if (!loop) return;
      clearTrackPrepExportState();
      trackPrep.loops.push(loop);
      trackPrepDirty = true;
      redrawTrackPrep();
    }

    function deleteTrackPrepItem(kind, id) {
      if (kind === 'mark') {
        trackPrep.marks = (trackPrep.marks || []).filter(mark => mark.type !== id);
        if (selectedPrepMarkType === id) selectedPrepMarkType = '';
      } else if (kind === 'loop') {
        trackPrep.loops = (trackPrep.loops || []).filter(loop => loop.id !== id);
      }
      clearTrackPrepExportState();
      trackPrepDirty = true;
      redrawTrackPrep();
    }

