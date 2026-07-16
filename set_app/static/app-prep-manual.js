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

      const beats = Math.max(
        1,
        Math.min(
          512,
          Number(lengthBeats) || 0
        )
      );

      const anchorMark = selectedPrepMark();

      const raw = clampTrackTime(
        anchorMark
          ? Number(anchorMark.time_sec)
          : currentPlaybackTime()
      );

      const loopSnap =
        beats <= 8
          ? 'bar'
          : 'phrase16';

      const bounds = exactLoopBounds(
        raw,
        beats,
        loopSnap
      );

      if (!bounds) {
        prepStatus(
          '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438\u0442\u044c \u0433\u0440\u0430\u043d\u0438\u0446\u044b loop',
          true
        );
        return;
      }

      const start = bounds.start_sec;
      const end = bounds.end_sec;

      if (!(end > start)) {
        prepStatus(
          '\u041a\u043e\u043d\u0435\u0446 loop \u0432\u044b\u0445\u043e\u0434\u0438\u0442 \u0437\u0430 \u0434\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c \u0442\u0440\u0435\u043a\u0430',
          true
        );
        return;
      }

      const type =
        $('trackPrepLoopType')?.value ===
        'EMERGENCY_LOOP'
          ? 'EMERGENCY_LOOP'
          : 'OUTRO_LOOP';

      const role =
        type === 'EMERGENCY_LOOP'
          ? 'EMERGENCY LOOP'
          : 'OUTRO LOOP';

      const loop = normalizePrepLoop({
        id: `${type.toLowerCase()}_${beats}_${Math.round(start * 1000)}`,
        type,
        name: `${role} ${beats}`,
        start_sec: start,
        end_sec: end,
        raw_start_sec: anchorMark
          ? start
          : raw,
        length_beats: beats,
        start_beat_index:
          bounds.start_beat_index,
        end_beat_index:
          bounds.end_beat_index,
        grid_source:
          bounds.grid_source,
        snap: loopSnap,
        from_mark_type:
          anchorMark?.type || undefined,
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

