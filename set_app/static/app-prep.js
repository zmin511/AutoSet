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
    const DEFAULT_WAVE_ZOOM = 4.0;
    const MAX_WAVE_ZOOM = 12;
    let waveZoom = DEFAULT_WAVE_ZOOM;
    let waveOffsetSec = 0;
    let followPlayhead = true;


    function mediaPathForTrack(track) {
      return String(track?.rel || track?.path || '').trim();
    }

    function audioErrorMessage(player) {
      const code = Number(player?.error?.code || 0);
      const names = {
        1: 'MEDIA_ERR_ABORTED',
        2: 'MEDIA_ERR_NETWORK',
        3: 'MEDIA_ERR_DECODE',
        4: 'MEDIA_ERR_SRC_NOT_SUPPORTED'
      };
      return names[code] || (code ? `MEDIA_ERR_${code}` : 'unknown audio error');
    }


    function audioDebugState(prefix = 'audio') {
      const player = $('player');
      if (!player) return `${prefix}: audio element missing`;
      const err = player.error ? audioErrorMessage(player) : 'none';
      const src = player.currentSrc || player.src || player.getAttribute('src') || '';
      const shortSrc = src.length > 88 ? `${src.slice(0, 58)}...${src.slice(-24)}` : src;
      const t = Number(player.currentTime || 0);
      const d = Number(player.duration || playbackDuration() || 0);
      return `${prefix}: t=${t.toFixed(2)} / ${(Number.isFinite(d) ? d : 0).toFixed(2)} · paused=${player.paused} · ready=${player.readyState} · net=${player.networkState} · vol=${Number(player.volume || 0).toFixed(2)} · muted=${player.muted} · err=${err} · src=${shortSrc}`;
    }

    function showAudioDebug(prefix = 'audio') {
      $('status').className = 'status';
      $('status').textContent = audioDebugState(prefix);
    }

    function ensureWebAudioContext() {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) throw new Error('Web Audio API is not supported by this browser');
      if (!webAudioCtx) webAudioCtx = new AudioCtx();
      if (!webAudioGain) {
        webAudioGain = webAudioCtx.createGain();
        webAudioGain.gain.value = Math.max(0, Math.min(1, Number($('playerVol')?.value) || 0.85));
        webAudioGain.connect(webAudioCtx.destination);
      }
      return webAudioCtx;
    }

    function currentWebAudioTime() {
      if (!webAudioPlaying || !webAudioCtx) return Number(webAudioOffsetSec || 0);
      const elapsed = Math.max(0, webAudioCtx.currentTime - webAudioStartedAt);
      const duration = playbackDuration() || Number(webAudioBuffer?.duration || 0) || 0;
      const cur = Number(webAudioOffsetSec || 0) + elapsed;
      return duration > 0 ? Math.min(duration, cur) : cur;
    }

    function scheduleWebAudioSeekTo(timeSec) {
      if (!webAudioPlaying || !webAudioPath) return;
      const target = Math.max(0, Number(timeSec) || 0);
      playbackCursorSec = target;
      playbackCursorPinned = true;
      audioPendingSeekSec = target;
      if (webAudioSeekTimer) window.clearTimeout(webAudioSeekTimer);
      webAudioSeekTimer = window.setTimeout(async () => {
        webAudioSeekTimer = null;
        if (!webAudioPath) return;
        try {
          await startWebAudioPlayback(webAudioPath, target);
        } catch (err) {
          reportPlaybackError(`WebAudio seek failed: ${err?.message || err?.name || err}`);
        }
      }, 80);
    }

    function stopWebAudioPlayback(updateUi = true) {
      // Capture current WebAudio time before stopping the source. This is the pause position.
      const pausedAt = webAudioPlaying ? currentWebAudioTime() : Number(webAudioOffsetSec || playbackCursorSec || 0);
      if (webAudioSeekTimer) {
        window.clearTimeout(webAudioSeekTimer);
        webAudioSeekTimer = null;
      }
      if (webAudioTimer) {
        window.clearInterval(webAudioTimer);
        webAudioTimer = null;
      }
      if (webAudioSource) {
        try { webAudioSource.onended = null; webAudioSource.stop(0); } catch {}
        try { webAudioSource.disconnect(); } catch {}
        webAudioSource = null;
      }
      if (Number.isFinite(pausedAt) && pausedAt >= 0) {
        webAudioOffsetSec = pausedAt;
        playbackCursorSec = pausedAt;
        playbackCursorPinned = true;
        audioPendingSeekSec = pausedAt;
      }
      webAudioPlaying = false;
      if (updateUi) {
        updatePlayerBar();
        if (lastWavePeaks) drawWaveform(lastWavePeaks);
        drawZoomWaveform();
      }
    }

    function pauseCurrentPlayback() {
      const player = $('player');
      const dur = playbackDuration();
      let pausedAt = currentPlaybackTime();
      if (!Number.isFinite(pausedAt) || pausedAt < 0) pausedAt = 0;
      if (dur > 0) pausedAt = Math.max(0, Math.min(dur, pausedAt));
      if (webAudioPlaying) {
        stopWebAudioPlayback(false);
      } else if (player && !player.paused) {
        try { player.pause(); } catch {}
        pausedAt = Number(player.currentTime || pausedAt || 0);
      }
      if (Number.isFinite(pausedAt) && pausedAt >= 0) {
        webAudioOffsetSec = pausedAt;
        playbackCursorSec = pausedAt;
        playbackCursorPinned = true;
        audioPendingSeekSec = pausedAt;
      }
      $('status').className = 'status';
      $('status').textContent = `Пауза: ${fmtTimePrecise(pausedAt, true)}`;
      updatePlayerBar();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    }

    async function loadWebAudioBuffer(mediaPath) {
      const ctx = ensureWebAudioContext();
      if (webAudioBuffer && webAudioPath === mediaPath) return webAudioBuffer;
      $('status').className = 'status';
      $('status').textContent = 'Декодирую аудио через WebAudio...';
      const res = await fetch(`/media?path=${encodeURIComponent(mediaPath)}&webaudio=1`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`/media ${res.status}`);
      const arrayBuffer = await res.arrayBuffer();
      if (!arrayBuffer || arrayBuffer.byteLength < 1024) throw new Error(`empty audio response (${arrayBuffer?.byteLength || 0} bytes)`);
      const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
      webAudioBuffer = decoded;
      webAudioPath = mediaPath;
      return decoded;
    }

    async function startWebAudioPlayback(mediaPath, targetSec = 0) {
      const ctx = ensureWebAudioContext();
      if (ctx.state === 'suspended') await ctx.resume();
      const buffer = await loadWebAudioBuffer(mediaPath);
      stopWebAudioPlayback(false);
      const duration = Number(buffer.duration || playbackDuration() || 0) || 0;
      const offset = Math.max(0, Math.min(duration ? Math.max(0, duration - 0.05) : 0, Number(targetSec) || 0));
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(webAudioGain || ctx.destination);
      webAudioSource = source;
      webAudioOffsetSec = offset;
      webAudioStartedAt = ctx.currentTime;
      webAudioPlaying = true;
      playbackCursorSec = offset;
      playbackCursorPinned = true;
      audioPendingSeekSec = offset;
      try { $('player')?.pause(); } catch {}
      source.onended = () => {
        if (!webAudioPlaying) return;
        stopWebAudioPlayback(true);
      };
      source.start(0, offset);
      $('status').className = 'status ok';
      $('status').textContent = `WebAudio воспроизведение: ${fmtTimePrecise(offset, true)}`;
      if (webAudioTimer) window.clearInterval(webAudioTimer);
      webAudioTimer = window.setInterval(() => {
        if (!webAudioPlaying) return;
        const cur = currentWebAudioTime();
        playbackCursorSec = cur;
        playbackCursorPinned = true;
        audioPendingSeekSec = cur;
        updatePlayerBar();
        if (lastWavePeaks) drawWaveform(lastWavePeaks);
        drawZoomWaveform();
      }, 80);
      startWaveformPlayheadLoop();
      updatePlayerBar();
      return true;
    }

    function startAudioDebugMonitor(prefix = 'audio', timeoutMs = 9000) {
      const player = $('player');
      if (!player) return;
      const startedAt = performance.now();
      const startedTime = Number(player.currentTime || 0);
      if (player.__audioDebugTimer) window.clearInterval(player.__audioDebugTimer);
      player.__audioDebugTimer = window.setInterval(() => {
        const cur = Number(player.currentTime || 0);
        const advanced = Number.isFinite(cur) && Math.abs(cur - startedTime) > 0.12;
        if (advanced) {
          $('status').className = 'status ok';
          $('status').textContent = `Воспроизведение: ${fmtTimePrecise(cur, true)} · ready=${player.readyState}`;
          window.clearInterval(player.__audioDebugTimer);
          player.__audioDebugTimer = null;
          return;
        }
        showAudioDebug(prefix);
        if (performance.now() - startedAt > timeoutMs) {
          window.clearInterval(player.__audioDebugTimer);
          player.__audioDebugTimer = null;
          $('status').className = 'status bad';
          $('status').textContent = `Аудио не двигается · ${audioDebugState(prefix)}`;
        }
      }, 350);
    }

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
        name: loop?.name || (type === 'EMERGENCY_LOOP' ? `Аварийная петля ${lengthBeats}` : `Loop ${lengthBeats}`),
        start_sec: Number(start.toFixed(3)),
        end_sec: Number(end.toFixed(3)),
        raw_start_sec: Number((loop?.raw_start_sec == null ? start : clampTrackTime(loop.raw_start_sec)).toFixed(3)),
        length_beats: lengthBeats,
        snap: loop?.snap || trackPrepSnap,
        source: 'manual',
        confidence: Number(loop?.confidence ?? 1)
      };
      const fromMarkType = String(loop?.from_mark_type || '').toUpperCase();
      if (prepMarkTypeValid(fromMarkType)) payload.from_mark_type = fromMarkType;
      return payload;
    }


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
          <div class="batch-suggest-cell">ВХОД</div>
          <div class="batch-suggest-cell">ВЫХОД</div>
          <div class="batch-suggest-cell">ПЕТЛЯ АУТРО</div>
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
        if (batchTrackBusy) status.textContent = 'Analyzing tracks...';
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
        prepStatus('No visible tracks to analyze', true);
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
            item.batch_message = 'Метки уже сохранены';
            continue;
          }
          const payload = batchTrackMetaPayload(item);
          const saveRes = await fetch('/api/track_marks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const saveData = await saveRes.json();
          if (!saveData?.ok) throw new Error(saveData?.error || 'Save failed');
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


    function trackPrepSuggestionConflictMessage(kind, type) {
      if (kind === 'loop') {
        return `${String(type || '').toUpperCase() === 'EMERGENCY_LOOP' ? 'Аварийная петля' : 'Петля аутро'} уже есть`;
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
          name: loop.name || (loop.type === 'EMERGENCY_LOOP' ? 'Аварийная петля' : 'Петля аутро'),
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
        const chip = event.target.closest('[data-prep-select="mark"]');
        if (chip) selectPrepMark(chip.dataset.id || '');
      });
      syncTrackPrepControls();
    }

