    let lastWaveTrackId = 0;
    let lastWavePeaks = null;
    window.__waveMarkers = [];
    window.__waveCues = [];
    window.__waveLoops = [];
    window.__waveRGB = null;
    window.__waveDetail = null;
    const prepConfig = window.AutoSetPrepConfig || {};
    const PREP_MARKS = prepConfig.PREP_MARKS || [];
    const PREP_MARK_COLORS = prepConfig.PREP_MARK_COLORS || {};
    let trackPrep = { marks: [], loops: [], exists: false, source: 'manual', confidence: 1 };
    let trackPrepSnap = 'beat';
    let trackPrepDirty = false;
    let selectedPrepMarkType = '';
    let trackPrepSuggestions = { marks: [], loops: [], warnings: [] };
    let trackPrepSuggestBusy = false;
    let trackPrepSuggestConflict = false;
    let trackPrepSuggestConflictText = '';
    let trackPrepExportStatus = '';
    let trackPrepExportBad = false;
    let trackPrepExportConflict = false;
    let trackPrepExportBusy = false;
    let batchTrackIds = new Set();
    let batchTrackSuggestions = [];
    let batchTrackMap = new Map();
    let batchTrackBusy = false;
    let batchTrackWarnings = [];
    let batchPreviewTrackId = 0;
    let batchPreviewMode = '';
    let waveDragActive = false;
    let waveDragMode = '';
    let waveLastFrac = null;
    let waveZoomDrag = null;
    let waveHover = { active: false, time_sec: null, snap_time_sec: null, snap_kind: '', snapped: false };
    let overviewHover = { active: false, time_sec: null, label: '' };
    const WAVE_SNAP_PREVIEW_PX = 10;
    const DEFAULT_WAVE_ZOOM = 10.0;
    const MAX_WAVE_ZOOM = 12;
    let waveZoom = DEFAULT_WAVE_ZOOM;
    let waveOffsetSec = 0;
    let followPlayhead = true;


    function overviewMarkerHintAtTime(timeSec) {
      const duration = playbackDuration();
      const threshold = Math.max(0.8, duration ? duration * 0.012 : 1.2);
      const items = [];
      const addMark = (label, time, extra = '') => {
        const t = Number(time);
        if (!Number.isFinite(t)) return;
        const dist = Math.abs(t - timeSec);
        if (dist <= threshold) items.push({ dist, text: `${label} ${fmtTime(t)}${extra}`.trim() });
      };
      for (const cue of window.__waveCues || []) addMark(cue.label || cue.name || 'Cue', cue.pos_s);
      for (const loop of window.__waveLoops || []) {
        const s = Number(loop.start_s);
        const e = Number(loop.end_s);
        if (!Number.isFinite(s) || !Number.isFinite(e)) continue;
        const dist = Math.min(Math.abs(s - timeSec), Math.abs(e - timeSec), (timeSec >= s && timeSec <= e) ? 0 : Infinity);
        if (dist <= threshold) items.push({ dist, text: `${loopRoleLabel(loop, true)} ${fmtTime(s)}-${fmtTime(e)}` });
      }
      items.sort((a, b) => a.dist - b.dist);
      const base = `Position ${fmtTimePrecise(timeSec, true)}`;
      return items.length ? `${base}\n${items.slice(0, 4).map(i => i.text).join('\n')}` : base;
    }

    function setupWaveCanvas(canvas) {
      if (!canvas) return null;
      const ctx = canvas.getContext('2d');
      if (!ctx) return null;
      const cssW = Math.max(1, canvas.clientWidth || canvas.getBoundingClientRect().width || 1);
      const cssH = Math.max(1, canvas.clientHeight || canvas.getBoundingClientRect().height || 1);
      const dpr = window.devicePixelRatio || 1;
      const pixelW = Math.max(1, Math.floor(cssW * dpr));
      const pixelH = Math.max(1, Math.floor(cssH * dpr));
      if (canvas.width !== pixelW) canvas.width = pixelW;
      if (canvas.height !== pixelH) canvas.height = pixelH;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      return { ctx, w: cssW, h: cssH, dpr: 1, actualDpr: dpr };
    }

    function maxWaveZoom() {
      return MAX_WAVE_ZOOM;
    }

    function sampleWave(arr, sec, duration) {
      if (!Array.isArray(arr) || !arr.length || !duration) return 0;
      const pos = Math.max(0, Math.min(arr.length - 1, (Number(sec) / duration) * (arr.length - 1)));
      const i = Math.floor(pos);
      const j = Math.min(arr.length - 1, i + 1);
      const f = pos - i;
      const a = Math.max(0, Math.min(255, Number(arr[i]) || 0));
      const b = Math.max(0, Math.min(255, Number(arr[j]) || 0));
      return a + (b - a) * f;
    }

    function prepMarkLabel(type) {
      const item = PREP_MARKS.find(m => m.type === String(type || '').toUpperCase());
      return item ? item.label : String(type || '').replace(/_/g, ' ');
    }

    function prepStatus(text, bad = false) {
      const el = $('trackPrepStatus');
      if (!el) return;
      el.textContent = text || '';
      el.className = `track-prep-status ${bad ? 'bad' : ''}`;
    }

    function clearTrackPrepExportState() {
      trackPrepExportStatus = '';
      trackPrepExportBad = false;
      trackPrepExportConflict = false;
      trackPrepExportBusy = false;
    }

    function setTrackPrepExportStatus(text = '', bad = false, conflict = false) {
      trackPrepExportStatus = text || '';
      trackPrepExportBad = !!bad;
      trackPrepExportConflict = !!conflict;
      syncTrackPrepControls();
    }

    function currentPrepDuration() {
      const detailDuration = Number(window.__waveDetail?.duration_sec || 0);
      if (Number.isFinite(detailDuration) && detailDuration > 0) return detailDuration;
      const playerDuration = Number($('player')?.duration || 0);
      if (Number.isFinite(playerDuration) && playerDuration > 0) return playerDuration;
      const trackDuration = Number(selectedTrack?.length || 0);
      return Number.isFinite(trackDuration) && trackDuration > 0 ? trackDuration : 0;
    }

    function currentPrepBpm() {
      const detailBpm = Number(window.__waveDetail?.bpm || 0);
      if (Number.isFinite(detailBpm) && detailBpm > 0) return detailBpm;
      const trackBpm = Number(selectedTrack?.bpm || 0);
      return Number.isFinite(trackBpm) && trackBpm > 0 ? trackBpm : 0;
    }

    function clampTrackTime(value) {
      const duration = currentPrepDuration();
      const max = duration > 0 ? duration : 24 * 60 * 60;
      const time = Number(value);
      return Number.isFinite(time) ? Math.max(0, Math.min(max, time)) : 0;
    }

    function median(values) {
      const clean = values.filter(v => Number.isFinite(v)).sort((a, b) => a - b);
      if (!clean.length) return 0;
      return clean[Math.floor(clean.length / 2)];
    }

    function estimateBeatSeconds() {
      const bpm = currentPrepBpm();
      if (bpm > 0) return 60 / bpm;
      const beats = Array.isArray(window.__waveDetail?.beat_grid) ? window.__waveDetail.beat_grid : [];
      const times = beats.map(b => Number(b?.time_sec)).filter(t => Number.isFinite(t)).sort((a, b) => a - b);
      const diffs = [];
      for (let i = 1; i < Math.min(times.length, 80); i++) {
        const diff = times[i] - times[i - 1];
        if (diff > 0.15 && diff < 2.5) diffs.push(diff);
      }
      return median(diffs);
    }

    function snapUnitBeats(snap = trackPrepSnap) {
      if (snap === 'bar') return 4;
      if (snap === 'phrase16') return 16;
      if (snap === 'phrase32') return 32;
      return 1;
    }

    function snapTimeToGrid(value, snap = trackPrepSnap) {
      const time = clampTrackTime(value);
      const duration = currentPrepDuration();
      const beats = Array.isArray(window.__waveDetail?.beat_grid) ? window.__waveDetail.beat_grid : [];
      const unitBeats = snapUnitBeats(snap);
      const candidates = beats
        .filter(b => {
          const beatNo = Number(b?.beat || 0);
          if (!Number.isFinite(Number(b?.time_sec))) return false;
          if (unitBeats === 1) return true;
          if (unitBeats === 4) return !!b?.is_bar_start || ((beatNo - 1) % 4 === 0);
          return ((beatNo - 1) % unitBeats) === 0 || (unitBeats === 16 && !!b?.is_phrase_start);
        })
        .map(b => Number(b.time_sec));
      if (candidates.length) {
        let best = candidates[0];
        let bestDist = Math.abs(time - best);
        for (const candidate of candidates) {
          const dist = Math.abs(time - candidate);
          if (dist < bestDist) {
            best = candidate;
            bestDist = dist;
          }
        }
        return clampTrackTime(best);
      }
      const beatSec = estimateBeatSeconds();
      if (beatSec > 0) {
        const step = beatSec * unitBeats;
        return clampTrackTime(Math.round(time / step) * step);
      }
      return duration ? Math.min(duration, time) : time;
    }


    function prepMarkTypeValid(type) {
      const markType = String(type || '').toUpperCase();
      return PREP_MARKS.some(item => item.type === markType);
    }

    function selectedPrepMark() {
      const markType = String(selectedPrepMarkType || '').toUpperCase();
      if (!markType) return null;
      return (trackPrep.marks || []).find(mark => mark.type === markType) || null;
    }

    function selectPrepMark(type) {
      const markType = String(type || '').toUpperCase();
      if (!prepMarkTypeValid(markType)) return false;
      const exists = (trackPrep.marks || []).some(mark => mark.type === markType);
      if (!exists) return false;
      selectedPrepMarkType = markType;
      renderTrackPrepList();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
      return true;
    }

    function loopRoleLabel(loopOrType, upper = false) {
      const type = String(loopOrType?.type || loopOrType || '').toUpperCase();
      const label = type === 'EMERGENCY_LOOP' ? 'Emergency' : 'Outro';
      return upper ? label.toUpperCase() : label;
    }

    function waveWindowState() {
      const canvas = $('waveZoomCanvas');
      const detail = window.__waveDetail;
      const duration = Number(detail?.duration_sec || 0) || playbackDuration();
      const zoom = Math.max(1, Math.min(maxWaveZoom(), Number(waveZoom) || 1));
      const windowSec = duration > 0 ? duration / zoom : 0;
      const maxOffset = Math.max(0, duration - windowSec);
      const width = Math.max(1, canvas?.getBoundingClientRect?.().width || canvas?.clientWidth || 1024);
      return { duration, zoom, windowSec, maxOffset, width };
    }

    function centerZoomOnTime(timeSec) {
      const state = waveWindowState();
      if (!(state.duration > 0) || !(state.windowSec > 0)) return;
      const t = Math.max(0, Math.min(state.duration, Number(timeSec) || 0));
      waveOffsetSec = Math.max(0, Math.min(state.maxOffset, t - state.windowSec / 2));
    }

    function exactLoopBounds(
      rawStart,
      lengthBeats,
      snap = trackPrepSnap
    ) {
      const beats = Array.isArray(
        window.__waveDetail?.beat_grid
      )
        ? window.__waveDetail.beat_grid
        : [];

      const requestedBeats = Math.max(
        1,
        Math.min(
          512,
          Number(lengthBeats) || 1
        )
      );

      const start = snapTimeToGrid(
        rawStart,
        snap
      );

      const validBeats = beats
        .map((beat, index) => ({
          time_sec: Number(beat?.time_sec),
          beat: Number(beat?.beat || index + 1),
          index
        }))
        .filter(item => Number.isFinite(item.time_sec))
        .sort((a, b) => a.time_sec - b.time_sec);

      if (validBeats.length) {
        let startIndex = 0;
        let bestDistance = Infinity;

        validBeats.forEach((item, index) => {
          const distance = Math.abs(
            item.time_sec - start
          );

          if (distance < bestDistance) {
            bestDistance = distance;
            startIndex = index;
          }
        });

        const endIndex =
          startIndex + requestedBeats;

        if (endIndex < validBeats.length) {
          const exactStart =
            validBeats[startIndex].time_sec;
          const exactEnd =
            validBeats[endIndex].time_sec;

          if (exactEnd > exactStart) {
            return {
              start_sec: Number(
                exactStart.toFixed(3)
              ),
              end_sec: Number(
                exactEnd.toFixed(3)
              ),
              start_beat_index: startIndex,
              end_beat_index: endIndex,
              grid_source: 'engine_grid'
            };
          }
        }
      }

      const beatSec = estimateBeatSeconds();

      if (!(beatSec > 0)) {
        return null;
      }

      const end = clampTrackTime(
        start + beatSec * requestedBeats
      );

      if (!(end > start)) {
        return null;
      }

      return {
        start_sec: Number(start.toFixed(3)),
        end_sec: Number(end.toFixed(3)),
        start_beat_index: null,
        end_beat_index: null,
        grid_source: 'bpm_fallback'
      };
    }


    function snapLabelForMode(snap = trackPrepSnap) {
      if (snap === 'bar') return 'Bar';
      if (snap === 'phrase16') return '16 beats';
      if (snap === 'phrase32') return '32 beats';
      return 'Beat';
    }

    function snapCandidatesForMode(snap = trackPrepSnap) {
      const beats = Array.isArray(window.__waveDetail?.beat_grid) ? window.__waveDetail.beat_grid : [];
      const unitBeats = snapUnitBeats(snap);
      const out = [];
      beats.forEach((beat, index) => {
        const time = Number(beat?.time_sec);
        if (!Number.isFinite(time)) return;
        const beatNo = Number(beat?.beat || index + 1);
        const normalizedBeat = Number.isFinite(beatNo) ? beatNo : index + 1;
        const isBar = !!beat?.is_bar_start || ((normalizedBeat - 1) % 4 === 0);
        const is16 = !!beat?.is_phrase_start || ((normalizedBeat - 1) % 16 === 0);
        const is32 = ((normalizedBeat - 1) % 32 === 0);
        if (unitBeats === 1) {
          let priority = 1;
          let kind = 'Beat';
          if (is32) { priority = 4; kind = '32 beats'; }
          else if (is16) { priority = 3; kind = '16 beats'; }
          else if (isBar) { priority = 2; kind = 'Bar'; }
          out.push({ time_sec: time, priority, kind });
          return;
        }
        if (unitBeats === 4 && isBar) out.push({ time_sec: time, priority: 2, kind: 'Bar' });
        else if (unitBeats === 16 && is16) out.push({ time_sec: time, priority: 3, kind: '16 beats' });
        else if (unitBeats === 32 && is32) out.push({ time_sec: time, priority: 4, kind: '32 beats' });
      });
      return out;
    }

    function snapPreviewForTime(value, pixelThreshold = WAVE_SNAP_PREVIEW_PX) {
      const time = clampTrackTime(value);
      const state = waveWindowState();
      const fallbackBeat = estimateBeatSeconds();
      const thresholdSec = state.windowSec > 0
        ? (Math.max(1, Number(pixelThreshold) || WAVE_SNAP_PREVIEW_PX) / state.width) * state.windowSec
        : Math.max(0.05, fallbackBeat > 0 ? fallbackBeat * 0.18 : 0.12);
      const candidates = snapCandidatesForMode(trackPrepSnap);
      let best = null;
      for (const candidate of candidates) {
        const dist = Math.abs(time - Number(candidate.time_sec));
        if (dist > thresholdSec) continue;
        if (!best || dist < best.distance_sec - 0.000001 || (Math.abs(dist - best.distance_sec) <= 0.000001 && candidate.priority > best.priority)) {
          best = { ...candidate, distance_sec: dist, snapped: true };
        }
      }
      const target = snapTimeToGrid(time, trackPrepSnap);
      if (best) return { time_sec: clampTrackTime(best.time_sec), kind: best.kind, snapped: true, distance_sec: best.distance_sec };
      const dist = Math.abs(time - target);
      return { time_sec: target, kind: snapLabelForMode(trackPrepSnap), snapped: dist <= thresholdSec, distance_sec: dist };
    }

    function snapTargetForPlacement(raw) {
      return snapPreviewForTime(raw).time_sec;
    }

    function manualMarkNearTime(timeSec, thresholdSec) {
      let best = null;
      for (const mark of trackPrep.marks || []) {
        const t = Number(mark?.time_sec);
        if (!Number.isFinite(t)) continue;
        const dist = Math.abs(t - timeSec);
        if (dist > thresholdSec) continue;
        if (!best || dist < best.dist) best = { mark, dist };
      }
      return best?.mark || null;
    }

    function manualMarkFromOverviewEvent(event) {
      const frac = _waveFracFromEvent(event);
      const canvas = $('waveCanvas');
      const duration = playbackDuration();
      if (frac == null || !(duration > 0) || !canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const thresholdSec = (WAVE_SNAP_PREVIEW_PX / Math.max(1, rect.width)) * duration;
      return manualMarkNearTime(frac * duration, thresholdSec);
    }

    function manualMarkFromZoomEvent(event) {
      const time = _waveZoomTimeFromEvent(event);
      const state = waveWindowState();
      if (time == null || !(state.windowSec > 0)) return null;
      const thresholdSec = (WAVE_SNAP_PREVIEW_PX / state.width) * state.windowSec;
      return manualMarkNearTime(time, thresholdSec);
    }

    function normalizePrepMark(mark) {
      const type = String(mark?.type || '').toUpperCase();
      if (!PREP_MARKS.some(item => item.type === type)) return null;
      const time = clampTrackTime(mark?.time_sec);
      const raw = mark?.raw_time_sec == null ? time : clampTrackTime(mark.raw_time_sec);
      return {
        id: type.toLowerCase(),
        type,
        name: mark?.name || prepMarkLabel(type),
        time_sec: Number(time.toFixed(3)),
        raw_time_sec: Number(raw.toFixed(3)),
        snap: mark?.snap || trackPrepSnap,
        source: 'manual',
        confidence: Number(mark?.confidence ?? 1)
      };
    }

    function normalizePrepLoop(loop) {
      const start = clampTrackTime(loop?.start_sec);
      const end = clampTrackTime(loop?.end_sec);
      if (!(end > start)) return null;
      const lengthBeats = Math.max(0, Math.min(512, Number(loop?.length_beats || 0)));
      const type = String(loop?.type || 'OUTRO_LOOP').toUpperCase() === 'EMERGENCY_LOOP' ? 'EMERGENCY_LOOP' : 'OUTRO_LOOP';
      const payload = {
        id: String(loop?.id || `${type.toLowerCase()}_${Math.round(start * 1000)}_${lengthBeats || 'manual'}`),
        type,
        name: loop?.name || `${type === 'EMERGENCY_LOOP' ? 'EMERGENCY' : 'OUTRO'} LOOP ${lengthBeats}`,
        start_sec: Number(start.toFixed(3)),
        end_sec: Number(end.toFixed(3)),
        raw_start_sec: Number((loop?.raw_start_sec == null ? start : clampTrackTime(loop.raw_start_sec)).toFixed(3)),
        length_beats: lengthBeats,
        start_beat_index:
          loop?.start_beat_index ?? null,
        end_beat_index:
          loop?.end_beat_index ?? null,
        grid_source:
          loop?.grid_source || '',
        snap: loop?.snap || trackPrepSnap,
        source: 'manual',
        confidence: Number(loop?.confidence ?? 1)
      };
      const fromMarkType = String(loop?.from_mark_type || '').toUpperCase();
      if (prepMarkTypeValid(fromMarkType)) payload.from_mark_type = fromMarkType;
      return payload;
    }



    function resetTrackPrepState() {
      trackPrep = { marks: [], loops: [], exists: false, source: 'manual', confidence: 1 };
      trackPrepDirty = false;
      selectedPrepMarkType = '';
      clearTrackPrepSuggestionsState();
      waveHover = { active: false, time_sec: null, snap_time_sec: null, snap_kind: '', snapped: false };
      clearTrackPrepExportState();
      renderTrackPrepList();
      syncTrackPrepControls();
    }


    function wireTrackPrepControls() {
      if (window.__trackPrepWired) return;
      window.__trackPrepWired = true;
      document.querySelectorAll('[data-prep-mark]').forEach(btn => {
        btn.addEventListener('click', () => addTrackPrepMark(btn.dataset.prepMark));
      });
      document.querySelectorAll('[data-prep-loop]').forEach(btn => {
        btn.addEventListener('click', () => addTrackPrepLoop(btn.dataset.prepLoop));
      });
      const snap = $('trackPrepSnap');
      if (snap) snap.addEventListener('change', () => {
        trackPrepSnap = snap.value || 'beat';
        syncTrackPrepControls();
      });
      $('trackPrepSave')?.addEventListener('click', saveTrackPrepMarks);
      $('trackPrepReset')?.addEventListener('click', resetTrackPrepMarks);
      $('trackPrepSuggest')?.addEventListener('click', suggestTrackPrepMarks);
      $('trackPrepAccept')?.addEventListener('click', () => acceptTrackPrepSuggestions(false));
      $('trackPrepClearSuggest')?.addEventListener('click', clearTrackPrepSuggestions);
      $('trackPrepReplaceSuggest')?.addEventListener('click', () => acceptTrackPrepSuggestions(true));
      $('trackPrepExport')?.addEventListener('click', () => exportTrackPrepToEngine(false));
      $('batchSuggestRun')?.addEventListener('click', batchSuggestTracks);
      $('batchSuggestAccept')?.addEventListener('click', () => acceptBatchSuggestions(false));
      $('batchSuggestReplace')?.addEventListener('click', () => acceptBatchSuggestions(true));
      $('batchSuggestOpen')?.addEventListener('click', () => {
        const selected = batchTrackSuggestions.find(item => item.selected !== false && item.ok !== false);
        if (selected) openBatchTrack(selected.track_id);
      });
      $('batchSuggestClear')?.addEventListener('click', clearBatchPreview);
      $('batchSuggestTable')?.addEventListener('click', (event) => {
        const check = event.target.closest('[data-batch-result-select]');
        if (check) {
          const id = Number(check.dataset.trackId || 0);
          const item = batchTrackResult(id);
          if (item) item.selected = !!check.checked;
          syncBatchSuggestControls();
          return;
        }
        const open = event.target.closest('[data-batch-open-track]');
        if (open) {
          openBatchTrack(open.dataset.batchOpenTrack || open.dataset.trackId || 0);
        }
      });
      $('trackPrepOverwrite')?.addEventListener('click', () => exportTrackPrepToEngine(true));
      $('trackPrepList')?.addEventListener('click', (event) => {
        const btn = event.target.closest('[data-prep-delete]');
        if (btn) {
          deleteTrackPrepItem(btn.dataset.prepDelete, btn.dataset.id || '');
          return;
        }
        const chip = event.target.closest('[data-prep-select]');
        if (chip?.dataset.prepSelect === 'mark') {
          selectPrepMark(chip.dataset.id || '');
          playPrepMark(chip.dataset.id || '');
        } else if (chip?.dataset.prepSelect === 'loop') {
          playPrepLoop(chip.dataset.id || '');
        }
      });
      syncTrackPrepControls();
    }

