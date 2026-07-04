// Track Prep persistence and Engine DJ export. Loaded before waveform so loadTrackPrepMarks is available.
    async function loadTrackPrepMarks(trackId) {

      resetTrackPrepState();
      if (!trackId) return;
      try {
        const res = await fetch(`/api/track_marks?track_id=${encodeURIComponent(trackId)}`);
        const data = await res.json();
        if (lastWaveTrackId !== Number(trackId)) return;
        if (!data?.ok) {
          prepStatus('Could not load manual marks', true);
          return;
        }
        trackPrep = {
          marks: (data.marks || []).map(normalizePrepMark).filter(Boolean),
          loops: (data.loops || []).map(normalizePrepLoop).filter(Boolean),
          exists: !!data.exists,
          source: data.source || 'manual',
          confidence: Number(data.confidence ?? 1)
        };
        if (!selectedPrepMark()) selectedPrepMarkType = '';
        trackPrepDirty = false;
        if (batchPreviewMode === 'batch' && batchPreviewTrackId === Number(trackId)) {
          applyBatchPreviewToCurrentTrack(trackId);
        }
        syncTrackPrepControls();
      } catch {
        prepStatus('Could not load manual marks', true);
      }
    }

    function normalizeTrackPrepForSave() {
      trackPrep.marks = (trackPrep.marks || []).map(mark => {
        const raw = mark.raw_time_sec == null ? mark.time_sec : mark.raw_time_sec;
        const snapped = snapTimeToGrid(raw, mark.snap || trackPrepSnap);
        return normalizePrepMark({ ...mark, time_sec: snapped, raw_time_sec: raw }) || mark;
      });
      const beatSec = estimateBeatSeconds();
      trackPrep.loops = (trackPrep.loops || []).map(loop => {
        const raw = loop.raw_start_sec == null ? loop.start_sec : loop.raw_start_sec;
        const start = snapTimeToGrid(raw, loop.snap || trackPrepSnap);
        const lengthBeats = Number(loop.length_beats || 0);
        const end = beatSec > 0 && lengthBeats > 0 ? clampTrackTime(start + beatSec * lengthBeats) : loop.end_sec;
        return normalizePrepLoop({ ...loop, start_sec: start, end_sec: end, raw_start_sec: raw }) || loop;
      }).filter(Boolean);
    }

    function trackPrepPayload() {
      const detail = window.__waveDetail || {};
      return {
        track_id: selectedTrack?.id,
        file_path: detail.path || selectedTrack?.path || selectedTrack?.rel || '',
        duration_sec: currentPrepDuration(),
        bpm: currentPrepBpm() || detail.bpm || selectedTrack?.bpm || null,
        marks: trackPrep.marks || [],
        loops: trackPrep.loops || [],
        source: 'manual',
        confidence: 1
      };
    }

    async function saveTrackPrepMarks() {
      if (!selectedTrack?.id || !window.__waveDetail) return;
      normalizeTrackPrepForSave();
      redrawTrackPrep();
      const btn = $('trackPrepSave');
      if (btn) btn.disabled = true;
      prepStatus('Saving manual marks...');
      try {
        const res = await fetch('/api/track_marks', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(trackPrepPayload())
        });
        const data = await res.json();
        if (!data?.ok) throw new Error(data?.error || 'Не удалось сохранить');
        trackPrep = {
          marks: (data.marks || []).map(normalizePrepMark).filter(Boolean),
          loops: (data.loops || []).map(normalizePrepLoop).filter(Boolean),
          exists: true,
          source: data.source || 'manual',
          confidence: Number(data.confidence ?? 1)
        };
        trackPrepDirty = false;
        trackPrepExportStatus = 'Только AutoSet';
        trackPrepExportBad = false;
        trackPrepExportConflict = false;
        redrawTrackPrep();
        prepStatus('Ручные метки сохранены');
      } catch (err) {
        prepStatus(String(err), true);
      } finally {
        syncTrackPrepControls();
      }
    }

    function trackPrepConflictMessage(conflicts) {
      const first = Array.isArray(conflicts) ? conflicts[0] : null;
      if (!first) return 'Конфликт: слот cue уже занят';
      const kind = first.type === 'loop' ? 'loop' : 'cue';
      return `Конфликт: слот ${kind} уже занят`;
    }

    function trackPrepExportError(data) {
      const reason = data?.reason || data?.error || 'export_failed';
      const labels = {
        missing_db: 'База Engine DB не найдена',
        missing_track_marks: 'Сначала сохраните метки',
        empty_track_marks: 'Нет меток для экспорта',
        missing_performance_data: 'Нет Engine PerformanceData',
        db_locked: 'Engine DB заблокирована',
        backup_failed: 'Не удалось создать backup Engine DB',
        codec_error: 'Не удалось прочитать Engine cue/loop',
        nothing_to_export: 'Нечего экспортировать'
      };
      return labels[reason] || String(data?.error || reason || 'Экспорт не удался');
    }

    async function exportTrackPrepToEngine(overwriteExisting = false) {
      if (!selectedTrack?.id) return;
      if (trackPrepDirty || !trackPrep.exists) {
        setTrackPrepExportStatus('Сначала сохраните метки', true, false);
        return;
      }
      trackPrepExportBusy = true;
      setTrackPrepExportStatus(overwriteExisting ? 'Перезаписываю слоты Engine...' : 'Экспорт в Engine DJ...');
      try {
        const res = await fetch('/api/export_track_marks_to_engine', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ track_id: selectedTrack.id, overwrite_existing: !!overwriteExisting })
        });
        const data = await res.json();
        if (data?.ok) {
          const backup = data.backup_path ? ` - Backup created: ${data.backup_path}` : '';
          setTrackPrepExportStatus(`Exported to Engine DJ${backup}`, false, false);
          return;
        }
        if (data?.reason === 'conflict') {
          setTrackPrepExportStatus(trackPrepConflictMessage(data.conflicts), true, true);
          return;
        }
        setTrackPrepExportStatus(trackPrepExportError(data), true, false);
      } catch (err) {
        setTrackPrepExportStatus(`Export failed: ${err}`, true, false);
      } finally {
        trackPrepExportBusy = false;
        syncTrackPrepControls();
      }
    }


