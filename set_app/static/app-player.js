// AutoSet player/playback layer.
// Exports globals: selectedTrackId, playbackDuration, durationForSeek, getPlaybackTime/currentPlaybackTime, seekPlaybackTo,
// preparePlayerForTrack, warmBlobMediaSource, startSelectedPlayback, cueSelectedPlayback, pauseCurrentPlayback, updatePlayerBar, wirePlayerBar.
// Uses globals from app-core/app-prep/app-waveform: $, selectedTrack, trackPrep, drawWaveform, drawZoomWaveform, syncWaveScrollControl,
// centerZoomOnTime, updateFollowWaveWindow, syncTrackPrepControls, refreshWaveDisplayItems-related state.

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
    let activePrepLoop = null;
    let prepLoopRestarting = false;

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
        enforcePrepLoop(cur);
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


    function seekPlaybackTo(timeSec, options = {}) {
      const player = $('player');
      const duration = durationForSeek();
      if (!selectedTrackId() || !Number.isFinite(duration) || duration <= 0) return;
      const t = pinPlaybackCursor(timeSec, options);

      if (webAudioPlaying) {
        scheduleWebAudioSeekTo(t);
      } else if (player) {
        try {
          if (player.readyState >= 1) {
            player.currentTime = t;
          }
        } catch {}
        // Keep the pending seek even if HTML audio accepted currentTime; WebAudio fallback uses it later.
        audioPendingSeekSec = t;
      }
      updatePlayerBar();
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

    function reportPlaybackError(err) {
      const message = err?.message || err?.name || String(err || 'playback failed');
      $('status').className = 'status bad';
      $('status').textContent = `Не удалось запустить трек: ${message}`;
      updatePlayerBar();
    }

    function waitForAudioReady(player, timeoutMs = 6000) {
      if (!player) return Promise.reject(new Error('audio element is missing'));
      if (player.readyState >= 1) return Promise.resolve();
      return new Promise((resolve, reject) => {
        let done = false;
        const cleanup = () => {
          player.removeEventListener('loadedmetadata', onReady);
          player.removeEventListener('canplay', onReady);
          player.removeEventListener('error', onError);
          window.clearTimeout(timer);
        };
        const finish = (fn, value) => {
          if (done) return;
          done = true;
          cleanup();
          fn(value);
        };
        const onReady = () => finish(resolve);
        const onError = () => finish(reject, new Error(audioErrorMessage(player)));
        const timer = window.setTimeout(() => finish(reject, new Error('audio metadata timeout')), timeoutMs);
        player.addEventListener('loadedmetadata', onReady);
        player.addEventListener('canplay', onReady);
        player.addEventListener('error', onError);
      });
    }

    function withTimeout(promise, timeoutMs, label) {
      return Promise.race([
        promise,
        new Promise((_, reject) => window.setTimeout(() => reject(new Error(label || 'timeout')), timeoutMs))
      ]);
    }

    async function waitForPlaySignal(playPromise, timeoutMs = 650) {
      if (!playPromise || typeof playPromise.then !== 'function') return 'started';
      let timeoutId = null;
      const guarded = playPromise.then(() => 'started').catch(() => 'failed');
      const timer = new Promise((resolve) => {
        timeoutId = window.setTimeout(() => resolve('timeout'), timeoutMs);
      });
      const result = await Promise.race([guarded, timer]);
      if (timeoutId) window.clearTimeout(timeoutId);
      if (result === 'timeout') guarded.catch(() => {});
      return result;
    }
    async function checkMediaPath(mediaPath) {
      const res = await fetch(`/api/media-check?path=${encodeURIComponent(mediaPath)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data.ok) throw new Error(data.error || `media-check ${res.status}`);
      return data;
    }

    function waitForPlaybackProgress(player, startTime, timeoutMs = 1800) {
      if (!player) return Promise.resolve(false);
      const start = Number.isFinite(Number(startTime)) ? Number(startTime) : Number(player.currentTime || 0);
      return new Promise((resolve) => {
        let done = false;
        const cleanup = () => {
          player.removeEventListener('timeupdate', check);
          player.removeEventListener('playing', check);
          player.removeEventListener('pause', onStop);
          player.removeEventListener('error', onStop);
          window.clearTimeout(timer);
        };
        const finish = (value) => {
          if (done) return;
          done = true;
          cleanup();
          resolve(value);
        };
        const check = () => {
          const cur = Number(player.currentTime || 0);
          if (player.paused || !Number.isFinite(cur)) return;
          if (start > 1) {
            if (cur < start - 0.75) return;
            if (Math.abs(cur - start) <= 0.75 || cur > start + 0.05) finish(true);
            return;
          }
          if (cur > start + 0.05 || Math.abs(cur - start) > 0.08) finish(true);
        };
        const onStop = () => finish(false);
        const timer = window.setTimeout(() => finish(false), timeoutMs);
        player.addEventListener('timeupdate', check);
        player.addEventListener('playing', check);
        player.addEventListener('pause', onStop);
        player.addEventListener('error', onStop);
        check();
      });
    }

    async function useBlobMediaSource(mediaPath, options = {}) {
      const player = $('player');
      if (!player) throw new Error('audio element is missing');
      const readyTimeoutMs = Math.max(300, Number(options.readyTimeoutMs) || 2200);
      if ((!mediaBlobUrl || mediaBlobPath !== mediaPath) && mediaBlobWarmupPromise && mediaBlobWarmupPath === mediaPath) {
        await mediaBlobWarmupPromise;
      }
      if (!mediaBlobUrl || mediaBlobPath !== mediaPath) {
        $('status').className = 'status';
        $('status').textContent = 'Загружаю аудио напрямую...';
        const res = await fetch(`/media?path=${encodeURIComponent(mediaPath)}`, { cache: 'no-store' });
        if (!res.ok) throw new Error(`/media ${res.status}`);
        const blob = await res.blob();
        if (mediaBlobUrl) {
          try { URL.revokeObjectURL(mediaBlobUrl); } catch {}
        }
        mediaBlobUrl = URL.createObjectURL(blob);
        mediaBlobPath = mediaPath;
      }
      const alreadyAttached = player.src === mediaBlobUrl && player.readyState >= 1;
      if (!alreadyAttached) {
        player.pause();
        player.src = mediaBlobUrl;
        player.preload = 'auto';
        player.muted = false;
        try { player.load(); } catch {}
        await waitForAudioReady(player, readyTimeoutMs);
      } else {
        player.muted = false;
      }
      const trackId = selectedTrackId();
      if (trackId) markAudioReadyForTrack(trackId, true);
      return true;
    }


    function deckCueStartTime() {
      const markTime = (mark) => {
        const t = Number(mark?.time_sec ?? mark?.pos_s ?? mark?.start_sec);
        return Number.isFinite(t) && t >= 0 ? clampTrackTime(t) : null;
      };
      const marks = Array.isArray(trackPrep?.marks) ? trackPrep.marks : [];
      const earlyPrep = marks
        .map(markTime)
        .filter(t => t != null && t <= 5)
        .sort((a, b) => a - b)[0];
      return earlyPrep != null ? earlyPrep : 0;
    }

    async function cueSelectedPlayback() {
      const player = $('player');
      if (!player || !selectedTrack) return;
      const target = deckCueStartTime();
      if (webAudioPlaying) {
        stopWebAudioPlayback(false);
      } else if (!player.paused) {
        try { player.pause(); } catch {}
      }
      followPlayhead = true;
      restoreCursorSnapshot(target, { centerZoom: true });
      try {
        if (player.readyState >= 1) player.currentTime = target;
      } catch {}
      syncWaveScrollControl();
      updatePlayerBar();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
      const ok = await startSelectedPlayback({ forceTimeSec: target, cue: true });
      if (ok) {
        $('status').className = 'status ok';
        $('status').textContent = `Cue: старт с ${fmtTimePrecise(target, true)}`;
      }
    }

    function clearPrepLoop() {
      activePrepLoop = null;
      prepLoopRestarting = false;
    }

    function enforcePrepLoop(timeSec) {
      const loop = activePrepLoop;
      const start = Number(loop?.start_sec);
      const end = Number(loop?.end_sec);
      if (!loop || !Number.isFinite(start) || !Number.isFinite(end) || !(end > start) || prepLoopRestarting) return;
      if (Number(timeSec) < end - 0.04) return;
      prepLoopRestarting = true;
      const player = $('player');
      if (webAudioPlaying) {
        startWebAudioPlayback(mediaPathForTrack(selectedTrack), start)
          .catch(() => clearPrepLoop())
          .finally(() => { prepLoopRestarting = false; });
        return;
      }
      try {
        if (player) player.currentTime = start;
        audioPendingSeekSec = start;
        playbackCursorSec = start;
        playbackCursorPinned = true;
      } catch {
        clearPrepLoop();
      }
      prepLoopRestarting = false;
    }

    function playPrepMark(type) {
      const markType = String(type || '').toUpperCase();
      const mark = (trackPrep?.marks || []).find(item => String(item?.type || '').toUpperCase() === markType);
      if (!mark) return false;
      clearPrepLoop();
      startSelectedPlayback({ forceTimeSec: Number(mark.time_sec) || 0, cue: true });
      return true;
    }

    function playPrepLoop(id) {
      const loop = (trackPrep?.loops || []).find(item => String(item?.id || '') === String(id || ''));
      const start = Number(loop?.start_sec);
      const end = Number(loop?.end_sec);
      if (!loop || !Number.isFinite(start) || !Number.isFinite(end) || !(end > start)) return false;
      activePrepLoop = { id: String(loop.id), start_sec: start, end_sec: end };
      prepLoopRestarting = false;
      startSelectedPlayback({ forceTimeSec: start, prepLoop: activePrepLoop });
      return true;
    }
    async function startSelectedPlayback(options = {}) {
      const player = $('player');
      if (!player || !selectedTrack) return false;
      if (options.prepLoop) {
        activePrepLoop = {
          id: String(options.prepLoop.id || ''),
          start_sec: Number(options.prepLoop.start_sec),
          end_sec: Number(options.prepLoop.end_sec)
        };
        prepLoopRestarting = false;
      }
      const mediaPath = mediaPathForTrack(selectedTrack);
      if (!mediaPath) {
        reportPlaybackError('media path is empty');
        return false;
      }

      const startSeq = ++playbackStartSeq;
      const forced = Number(options.forceTimeSec);
      const hasForcedTime = Number.isFinite(forced) && forced >= 0;
      const durBefore = playbackDuration();
      const desiredBefore = hasForcedTime ? forced : currentCursorSnapshot(Number(player.currentTime || webAudioOffsetSec || 0));
      restoreCursorSnapshot(desiredBefore);

      if (!preparePlayerForTrack(selectedTrack, { preserveCursor: true })) {
        reportPlaybackError('media source is empty');
        return false;
      }
      const src = player.currentSrc || player.src || player.getAttribute('src') || '';
      if (!src) {
        reportPlaybackError('audio src is empty');
        return false;
      }

      const dur = durationForSeek() || playbackDuration() || durBefore;
      const desired = Number.isFinite(Number(desiredBefore)) ? Number(desiredBefore) : 0;
      const target = (Number.isFinite(desired) && desired >= 0 && dur > 0)
        ? Math.max(0, Math.min(dur, desired))
        : Math.max(0, desired || 0);
      restoreCursorSnapshot(target);

      const applyTarget = () => {
        try {
          if (player.readyState >= 1 && Number.isFinite(target) && target >= 0) {
            player.currentTime = target;
            audioPendingSeekSec = target;
          } else if (Number.isFinite(target) && target >= 0) {
            audioPendingSeekSec = target;
          }
          playbackCursorSec = target;
          playbackCursorPinned = true;
        } catch {
          audioPendingSeekSec = target;
          playbackCursorSec = target;
          playbackCursorPinned = true;
        }
      };

      $('status').className = 'status';
      $('status').textContent = options.cue ? 'Запускаю cue...' : 'Запускаю аудио...';
      player.muted = false;
      if (!player.volume && $('playerVol')) player.volume = Math.max(0.01, Number($('playerVol').value) || 0.85);
      showAudioDebug('before play');

      try {
        // First try normal streaming from /media. If Chrome fires play but currentTime does not move,
        // fallback to Blob playback. This bypasses Range/MIME quirks in the tiny local HTTP server.
        if (!(mediaBlobUrl && mediaBlobPath === mediaPath) && mediaBlobWarmupPromise && mediaBlobWarmupPath === mediaPath) {
          await withTimeout(mediaBlobWarmupPromise, 450, 'audio warmup').catch(() => false);
        }
        if (mediaBlobUrl && mediaBlobPath === mediaPath) {
          await useBlobMediaSource(mediaPath, { readyTimeoutMs: 900 });
        }
        applyTarget();
        let playPromise = player.play();
        startAudioDebugMonitor('after play', 9000);
        let playState = playPromise && typeof playPromise.then === 'function'
          ? await waitForPlaySignal(playPromise, mediaBlobUrl && mediaBlobPath === mediaPath ? 350 : 250)
          : 'started';
        let progressed = playState === 'failed'
          ? false
          : await waitForPlaybackProgress(player, target, mediaBlobUrl && mediaBlobPath === mediaPath ? 500 : 350);
        if (playState === 'failed' || !progressed) {
          $('status').className = 'status';
          $('status').textContent = playState === 'failed'
            ? 'Поток отклонен, пробую fallback...'
            : 'Поток не двигается, пробую fallback...';
          await checkMediaPath(mediaPath);
          await useBlobMediaSource(mediaPath, { readyTimeoutMs: 1800 });
          applyTarget();
          playPromise = player.play();
          playState = playPromise && typeof playPromise.then === 'function'
            ? await waitForPlaySignal(playPromise, 650)
            : 'started';
          progressed = playState === 'failed'
            ? false
            : await waitForPlaybackProgress(player, target, 700);
        }
        if (playState === 'failed' || !progressed) {
          $('status').className = 'status';
          $('status').textContent = 'HTML audio не двигается, пробую WebAudio...';
          await startWebAudioPlayback(mediaPath, target);
          updatePlayerBar();
          return true;
        }
        const cur = Number(player.currentTime);
        if (Number.isFinite(cur) && cur >= 0) {
          playbackCursorSec = cur;
          playbackCursorPinned = true;
        }
        $('status').className = 'status ok';
        $('status').textContent = `Воспроизведение: ${fmtTimePrecise(Number(player.currentTime || 0), true)}`;
        startWaveformPlayheadLoop();
        return true;
      } catch (err) {
        const details = player.error ? `${audioErrorMessage(player)} · ${mediaPath}` : `${err?.message || err?.name || err}`;
        reportPlaybackError(details);
        return false;
      }
      updatePlayerBar();
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    }

    function updatePlayerBar() {
      const player = $('player');
      const timeEl = $('playerTime');
      const btn = $('playPause');
      if (!player || !timeEl || !btn) return;
      const trackId = selectedTrackId();
      if (trackId && audioLoadingTrackId === trackId && !audioNavigationReady()) {
        timeEl.textContent = 'Loading track...';
      } else {
        const dur = playbackDuration();
        const cur = currentPlaybackTime();
        const durText = (Number.isFinite(dur) && dur > 0) ? fmtTime(dur) : '0:00';
        const curText = (Number.isFinite(cur) && cur >= 0) ? fmtTime(cur) : '0:00';
        timeEl.textContent = `${curText} / ${durText}`;
      }
      btn.textContent = (player.paused && !webAudioPlaying) ? '▶' : '⏸';
    }

    function wirePlayerBar() {
      const player = $('player');
      if (!player) return;
      const btn = $('playPause');
      const cueBtn = $('cueButton');
      const vol = $('playerVol');
      if (!player.__wiredAudioEvents) {
        player.__wiredAudioEvents = true;
        const markSelectedAudioReady = () => markAudioReadyForTrack(audioPreparingTrackId || selectedTrackId(), false);
        player.addEventListener('timeupdate', () => {
          const cur = Number(player.currentTime);
          enforcePrepLoop(cur);
          const cursor = Number(playbackCursorSec);
          const pending = pendingSeekTime();
          const keepPinned = player.paused && playbackCursorPinned && Number.isFinite(cursor) && Math.abs(cur - cursor) > 0.2 && (pending == null || Math.abs(pending - cursor) < 0.2);
          if (Number.isFinite(cur) && cur >= 0 && !keepPinned) { playbackCursorSec = cur; playbackCursorPinned = true; }
          updatePlayerBar();
          if (lastWavePeaks) drawWaveform(lastWavePeaks);
          drawZoomWaveform();
        });
        player.addEventListener('durationchange', markSelectedAudioReady);
        player.addEventListener('loadedmetadata', markSelectedAudioReady);
        player.addEventListener('canplay', markSelectedAudioReady);
        player.addEventListener('play', () => { updatePlayerBar(); startWaveformPlayheadLoop(); });
        player.addEventListener('playing', () => {
          showAudioDebug('playing');
          startAudioDebugMonitor('playing', 9000);
          updatePlayerBar();
        });
        player.addEventListener('pause', updatePlayerBar);
        player.addEventListener('error', () => {
          const mediaPath = mediaPathForTrack(selectedTrack);
          reportPlaybackError(`${audioErrorMessage(player)}${mediaPath ? ' · ' + mediaPath : ''}`);
        });
        window.addEventListener('keydown', (e) => {
          if (e.code === 'Space' && e.target === document.body) {
            e.preventDefault();
            if (webAudioPlaying || !player.paused) {
              pauseCurrentPlayback();
            } else {
              startSelectedPlayback();
            }
          }
        });
      }
      if (btn && !btn.__wiredPlayCtl) {
        btn.__wiredPlayCtl = true;
        btn.addEventListener('click', () => {
          clearPrepLoop();
          if (webAudioPlaying || !player.paused) {
            pauseCurrentPlayback();
            return;
          }
          startSelectedPlayback();
        });
      }
      if (cueBtn && !cueBtn.__wiredCueCtl) {
        cueBtn.__wiredCueCtl = true;
        cueBtn.addEventListener('click', () => {
          clearPrepLoop();
          cueSelectedPlayback();
        });
      }
      if (vol && !vol.__wiredVolCtl) {
        vol.__wiredVolCtl = true;
        if (player.volume == null) player.volume = 0.85;
        player.volume = Math.max(0, Math.min(1, Number(vol.value) || 0.85));
        vol.addEventListener('input', () => {
          const value = Math.max(0, Math.min(1, Number(vol.value) || 0));
          player.volume = value;
          if (webAudioGain) webAudioGain.gain.value = value;
        });
      }
      updatePlayerBar();
    }


    function getPlaybackTime() {
      return currentPlaybackTime();
    }
