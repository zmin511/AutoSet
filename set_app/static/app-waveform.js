// AutoSet waveform rendering and navigation layer.
// Exports globals: drawWaveform, drawZoomWaveform, loadWaveform, syncWaveScrollControl, wireWaveformScrub,
// wireWaveformDetailControls, wireWaveformPreplaySeekFallback, startWaveformPlayheadLoop, updateFollowWaveWindow.
// Uses globals from app-core/app-player/app-prep: $, selectedTrackId, playbackDuration, currentPlaybackTime,
// seekPlaybackTo, trackPrep, refreshWaveDisplayItems, snapPreviewForTime, PREP_MARK_COLORS.

function updateFollowWaveWindow() {
      if (!followPlayhead) return;
      const cur = currentPlaybackTime();
      if (!Number.isFinite(cur)) return;
      centerZoomOnTime(cur);
    }

    function drawWaveform(peaks) {
      const canvas = $('waveCanvas');
      if (!canvas) return;
      const state = setupWaveCanvas(canvas);
      if (!state) return;
      const { ctx, w, h, dpr } = state;

      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0b0d0f';
      ctx.fillRect(0, 0, w, h);

      if (!Array.isArray(peaks) || !peaks.length) return;
      const cueLabelH = 18 * dpr;
      const loopLabelH = 14 * dpr;
      const waveTop = cueLabelH + (6 * dpr);
      const waveBottom = h - loopLabelH - (6 * dpr);
      const waveBase = Math.max(waveTop + 6 * dpr, waveBottom); // baseline (only upper half waveform)
      const maxAmp = Math.max(4 * dpr, (waveBase - waveTop) * 0.96);
      const bins = Math.max(1, Math.floor(w));
      const rgb = window.__waveRGB;
      const hasRgb = rgb && Array.isArray(rgb.r) && Array.isArray(rgb.g) && Array.isArray(rgb.b) && rgb.r.length === peaks.length;
      if (hasRgb) {
        // Engine-like layered look: blue (low), green (mid), white envelope.
        const drawLayer = (arr, color, gain, alpha) => {
          ctx.strokeStyle = color;
          ctx.globalAlpha = alpha;
          ctx.lineWidth = 1;
          ctx.beginPath();
          for (let x = 0; x < bins; x++) {
            const idx = Math.floor((x / Math.max(1, bins - 1)) * (peaks.length - 1));
            const p = Math.max(0, Math.min(255, Number(arr[idx]) || 0));
            const amp = (p / 255) * maxAmp * gain;
            ctx.moveTo(x + 0.5, waveBase);
            ctx.lineTo(x + 0.5, waveBase - amp);
          }
          ctx.stroke();
          ctx.globalAlpha = 1;
        };
        drawLayer(rgb.b, 'rgba(73,160,236,1)', 1.0, 0.95);
        drawLayer(rgb.g, 'rgba(55,197,143,1)', 0.92, 0.95);
        drawLayer(rgb.r, 'rgba(238,242,245,1)', 0.78, 0.9);
      } else {
        ctx.strokeStyle = '#37c58f';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let x = 0; x < bins; x++) {
          const idx = Math.floor((x / Math.max(1, bins - 1)) * (peaks.length - 1));
          const p = Math.max(0, Math.min(255, Number(peaks[idx]) || 0));
          const amp = (p / 255) * maxAmp;
          ctx.moveTo(x + 0.5, waveBase);
          ctx.lineTo(x + 0.5, waveBase - amp);
        }
        ctx.stroke();
      }

      ctx.strokeStyle = 'rgba(255,255,255,0.10)';
      ctx.beginPath();
      ctx.moveTo(0, waveBase + 0.5);
      ctx.lineTo(w, waveBase + 0.5);
      ctx.stroke();

      if (Array.isArray(window.__waveMarkers) && window.__waveMarkers.length) {
        const beats = window.__waveMarkers.filter(m => String(m?.kind || '') === 'beat');
        const beatStep = beats.length > 80 ? Math.ceil(beats.length / 40) : 1;
        let beatSeen = 0;
        for (const m of window.__waveMarkers) {
          const frac = Number(m?.pos_frac);
          if (!Number.isFinite(frac) || frac < 0 || frac > 1) continue;
          const x = Math.floor(frac * (w - 1)) + 0.5;
          const kind = String(m?.kind || '');
          if (kind === 'beat') {
            beatSeen += 1;
            if (beatSeen % beatStep !== 0) continue;
            ctx.strokeStyle = 'rgba(255,255,255,0.10)';
            ctx.lineWidth = 1;
          } else if (kind === 'cue') {
            ctx.strokeStyle = 'rgba(30,110,200,0.72)';
            ctx.lineWidth = 2;
          } else if (kind === 'prep') {
            const selectedMarker = m?.type === selectedPrepMarkType;
            const suggestedMarker = m?.source === 'suggested';
            ctx.setLineDash(suggestedMarker ? [6 * dpr, 4 * dpr] : []);
            ctx.strokeStyle = selectedMarker ? 'rgba(255,224,108,0.98)' : (suggestedMarker ? 'rgba(255,224,108,0.92)' : 'rgba(55,197,143,0.88)');
            ctx.lineWidth = selectedMarker ? 3 : 2;
          } else if (kind === 'loop') {
            ctx.setLineDash(m?.source === 'suggested' ? [6 * dpr, 4 * dpr] : []);
            ctx.strokeStyle = m?.source === 'suggested' ? 'rgba(255,224,108,0.95)' : 'rgba(236,196,76,0.95)';
            ctx.lineWidth = 2;
          } else {
            ctx.strokeStyle = 'rgba(255,255,255,0.22)';
            ctx.lineWidth = 1;
          }
          ctx.beginPath();
          const y1 = (kind === 'cue' || kind === 'beat') ? 0 : 0;
          const y2 = (kind === 'cue' || kind === 'beat') ? waveBase : h;
          ctx.moveTo(x, y1);
          ctx.lineTo(x, y2);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        ctx.lineWidth = 1;
      }

      // Overview is intentionally text-light: detailed cue/loop labels live on the zoom waveform.
      // The overview keeps marker lines only and uses the native tooltip on hover to avoid label overlap.

      if (Array.isArray(window.__waveLoops) && window.__waveLoops.length) {
        const trackLen = playbackDuration() || null;
        ctx.font = `${Math.max(10, Math.floor(11 * dpr))}px Segoe UI, Inter, Arial, sans-serif`;
        ctx.textBaseline = 'bottom';
        for (const loop of window.__waveLoops) {
          const a = Number(loop?.start_frac);
          const b = Number(loop?.end_frac);
          if (!Number.isFinite(a) || !Number.isFinite(b)) continue;
          const leftFrac = Math.max(0, Math.min(1, Math.min(a, b)));
          const rightFrac = Math.max(0, Math.min(1, Math.max(a, b)));
          const x1 = Math.floor(leftFrac * (w - 1)) + 0.5;
          const x2 = Math.floor(rightFrac * (w - 1)) + 0.5;
          const yTop = waveBase + 1;
          const yBot = h - 1;
          const manualLoop = loop?.source === 'manual';
          const suggestedLoop = loop?.source === 'suggested';
          ctx.setLineDash(suggestedLoop ? [6 * dpr, 4 * dpr] : []);
          ctx.fillStyle = manualLoop ? 'rgba(255,138,61,0.24)' : (suggestedLoop ? 'rgba(255,224,108,0.14)' : 'rgba(255,138,61,0.18)');
          ctx.strokeStyle = loop?.color || (suggestedLoop ? 'rgba(255,224,108,0.92)' : 'rgba(255,138,61,0.70)');
          ctx.lineWidth = 1;
          ctx.fillRect(x1, yTop, Math.max(1, x2 - x1), yBot - yTop);
          ctx.beginPath();
          ctx.moveTo(x1, yTop);
          ctx.lineTo(x1, yBot);
          ctx.moveTo(x2, yTop);
          ctx.lineTo(x2, yBot);
          ctx.stroke();
          ctx.setLineDash([]);
          // No loop text on overview; hover tooltip and zoom waveform carry details.
        }
      }

      {
        const dur = playbackDuration();
        if (Number.isFinite(dur) && dur > 0) {
          const axisY = h - 7 * dpr;
          const labelEvery = dur > 900 ? 120 : 60;
          ctx.font = `${Math.max(10, Math.floor(10 * dpr))}px Segoe UI, Inter, Arial, sans-serif`;
          ctx.textBaseline = 'bottom';
          ctx.strokeStyle = 'rgba(154,167,178,0.38)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(0, axisY + 0.5);
          ctx.lineTo(w, axisY + 0.5);
          ctx.stroke();
          for (let t = 0; t <= dur + 0.001; t += 30) {
            const x = Math.floor((t / dur) * (w - 1)) + 0.5;
            const major = Math.abs(t % labelEvery) < 0.001 || t === 0;
            ctx.strokeStyle = major ? 'rgba(154,167,178,0.55)' : 'rgba(154,167,178,0.28)';
            ctx.beginPath();
            ctx.moveTo(x, axisY - (major ? 8 : 4) * dpr);
            ctx.lineTo(x, axisY + 1 * dpr);
            ctx.stroke();
          }
          const endText = fmtTime(dur);
          const endW = ctx.measureText(endText).width;
          ctx.fillStyle = 'rgba(154,167,178,0.95)';
          for (let t = 0; t < dur - 1; t += labelEvery) {
            const text = fmtTime(t);
            const tw = ctx.measureText(text).width;
            const x = Math.max(2 * dpr, Math.min(w - tw - endW - 18 * dpr, (t / dur) * (w - 1) - tw / 2));
            if (x + tw < w - endW - 14 * dpr) ctx.fillText(text, x, h - 1 * dpr);
          }
          ctx.fillText(endText, w - endW - 2 * dpr, h - 1 * dpr);
        }
      }

      {
        const dur = playbackDuration();
        const cur = currentPlaybackTime();
        if (Number.isFinite(dur) && dur > 0 && Number.isFinite(cur) && cur >= 0) {
          const frac = Math.max(0, Math.min(1, cur / dur));
          const x = Math.floor(frac * (w - 1)) + 0.5;
          ctx.strokeStyle = 'rgba(255,95,95,0.88)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, h);
          ctx.stroke();
          ctx.lineWidth = 1;
          const label = fmtTime(cur);
          ctx.font = `${Math.max(10, Math.floor(10 * dpr))}px Segoe UI, Inter, Arial, sans-serif`;
          const lw = ctx.measureText(label).width + 10 * dpr;
          const lx = Math.max(2 * dpr, Math.min(w - lw - 2 * dpr, x + 5 * dpr));
          const ly = h - 26 * dpr;
          ctx.fillStyle = 'rgba(8,12,16,0.86)';
          ctx.fillRect(lx, ly, lw, 17 * dpr);
          ctx.fillStyle = '#ffb6b6';
          ctx.textBaseline = 'top';
          ctx.fillText(label, lx + 5 * dpr, ly + 3 * dpr);
        }
      }
    }

    function _waveFracFromEvent(event) {
      const canvas = $('waveCanvas');
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      if (!Number.isFinite(x)) return null;
      return Math.max(0, Math.min(1, x / Math.max(1, rect.width)));
    }

    function _waveFracFromOverviewAreaEvent(event) {
      const canvas = $('waveCanvas');
      const area = $('waveBox') || canvas;
      if (!canvas || !area) return null;
      const rect = area.getBoundingClientRect();
      const x = event.clientX - rect.left;
      if (!Number.isFinite(x)) return null;
      return Math.max(0, Math.min(1, x / Math.max(1, rect.width)));
    }

    function _waveZoomTimeFromAreaEvent(event) {
      const canvas = $('waveZoomCanvas');
      const panel = $('waveZoomPanel') || canvas;
      const detail = window.__waveDetail;
      if (!canvas || !panel || !detail) return null;
      const rect = panel.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const duration = Number(detail.duration_sec || 0) || playbackDuration();
      if (!Number.isFinite(x) || duration <= 0) return null;
      const zoom = Math.max(1, Math.min(maxWaveZoom(), Number(waveZoom) || 1));
      const windowSec = duration / zoom;
      return Math.max(0, Math.min(duration, waveOffsetSec + (x / Math.max(1, rect.width)) * windowSec));
    }

    function _waveOverviewSeekEvent(event) {
      const canvas = $('waveCanvas');
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      if (!rect || !Number.isFinite(rect.left) || !Number.isFinite(rect.width)) return null;
      if (event.clientX < rect.left || event.clientX > rect.right) return null;
      if (event.clientY < rect.top || event.clientY > rect.bottom) return null;
      return _waveFracFromEvent(event);
    }

    function _waveZoomTimeFromEvent(event) {
      const canvas = $('waveZoomCanvas');
      const detail = window.__waveDetail;
      if (!canvas || !detail) return null;
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const duration = Number(detail.duration_sec || 0) || playbackDuration();
      if (!Number.isFinite(x) || duration <= 0) return null;
      const zoom = Math.max(1, Math.min(maxWaveZoom(), Number(waveZoom) || 1));
      const windowSec = duration / zoom;
      return Math.max(0, Math.min(duration, waveOffsetSec + (x / Math.max(1, rect.width)) * windowSec));
    }

    function _seekPlayerToTime(timeSec, options = {}) {
      seekPlaybackTo(timeSec, options);
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    }

    function _seekPlayerToFrac(frac, options = {}) {
      const duration = durationForSeek();
      if (!Number.isFinite(duration) || duration <= 0) return;
      _seekPlayerToTime(Math.max(0, Math.min(1, Number(frac) || 0)) * duration, options);
    }

    function fmtTimePrecise(seconds, withMillis = false) {
      const value = Math.max(0, Number(seconds) || 0);
      const whole = Math.floor(value);
      const m = Math.floor(whole / 60);
      const s = whole % 60;
      if (!withMillis) return `${m}:${String(s).padStart(2, '0')}`;
      const ms = Math.floor((value - whole) * 1000);
      return `${m}:${String(s).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
    }

    function fmtTime(seconds) {
      return fmtTimePrecise(seconds, false);
    }

    function setWaveHoverFromEvent(event) {
      const t = _waveZoomTimeFromEvent(event);
      if (t == null) return false;
      const snap = snapPreviewForTime(t);
      waveHover = {
        active: true,
        time_sec: t,
        snap_time_sec: snap.time_sec,
        snap_kind: snap.kind,
        snapped: !!snap.snapped
      };
      drawZoomWaveform();
      return true;
    }

    function clearWaveHover() {
      if (!waveHover.active) return;
      waveHover = { active: false, time_sec: null, snap_time_sec: null, snap_kind: '', snapped: false };
      drawZoomWaveform();
    }

    function wireWaveformScrub() {
      const canvas = $('waveCanvas');
      if (!canvas) return;
      if (canvas.__wired) return;
      canvas.__wired = true;

      canvas.addEventListener('mousemove', (e) => {
        const frac = _waveFracFromEvent(e);
        const duration = playbackDuration();
        if (frac == null || !(duration > 0)) {
          canvas.title = 'Waveform overview';
          return;
        }
        const time = Math.max(0, Math.min(duration, frac * duration));
        overviewHover = { active: true, time_sec: time, label: overviewMarkerHintAtTime(time) };
        canvas.title = overviewHover.label;
      });
      canvas.addEventListener('mouseleave', () => {
        overviewHover = { active: false, time_sec: null, label: '' };
        canvas.title = 'Waveform overview';
      });

      canvas.addEventListener('mousedown', (e) => {
        if (!canNavigateWaveform()) return;
        const mark = manualMarkFromOverviewEvent(e);
        if (mark && selectPrepMark(mark.type)) return;
        const frac = _waveFracFromEvent(e);
        if (frac == null) return;
        waveDragActive = true;
        waveDragMode = 'overview';
        _seekPlayerToFrac(frac, { centerZoom: true });
        e.preventDefault();
      });
      window.addEventListener('mousemove', (e) => {
        if (!waveDragActive) return;
        if (waveDragMode === 'overview' || waveDragMode === 'overview-panel') {
          const frac = waveDragMode === 'overview-panel' ? _waveFracFromOverviewAreaEvent(e) : _waveFracFromEvent(e);
          if (frac == null) return;
          _seekPlayerToFrac(frac, { centerZoom: true });
          return;
        }
        if (waveDragMode === 'zoom-pan' && waveZoomDrag) {
          const zoomCanvas = $('waveZoomCanvas');
          const rect = zoomCanvas?.getBoundingClientRect?.();
          const width = Math.max(1, rect?.width || waveZoomDrag.width || 1);
          const dx = e.clientX - waveZoomDrag.startX;
          if (Math.abs(dx) > 2) waveZoomDrag.moved = true;
          const maxOffset = Math.max(0, waveZoomDrag.duration - waveZoomDrag.windowSec);
          waveOffsetSec = Math.max(0, Math.min(maxOffset, waveZoomDrag.startOffset - (dx / width) * waveZoomDrag.windowSec));
          const focal = Math.max(0, Math.min(waveZoomDrag.duration, waveOffsetSec + waveZoomDrag.windowSec / 2));
          _seekPlayerToTime(focal, { centerZoom: false });
          setWaveHoverFromEvent(e);
        }
      });
      window.addEventListener('mouseup', () => {
        if (waveDragMode === 'zoom-pan' && waveZoomDrag && !waveZoomDrag.moved) {
          _seekPlayerToTime(waveZoomDrag.clickTime, { centerZoom: false });
        }
        waveDragActive = false;
        waveDragMode = '';
        waveZoomDrag = null;
        updatePlayerBar();
        if (lastWavePeaks) drawWaveform(lastWavePeaks);
        drawZoomWaveform();
      });
      const overviewPanel = $('waveBox');
      if (overviewPanel && !overviewPanel.__wiredPanelSeek) {
        overviewPanel.__wiredPanelSeek = true;
        overviewPanel.addEventListener('mousedown', (e) => {
          if (e.target === canvas) return;
          if (!canNavigateWaveform()) return;
          const frac = _waveFracFromOverviewAreaEvent(e);
          if (frac == null) return;
          waveDragActive = true;
          waveDragMode = 'overview-panel';
          _seekPlayerToFrac(frac, { centerZoom: true });
          e.preventDefault();
        });
      }

      const zoomPanel = $('waveZoomPanel');
      if (zoomPanel && !zoomPanel.__wiredPanelSeek) {
        zoomPanel.__wiredPanelSeek = true;
        zoomPanel.addEventListener('mousedown', (e) => {
          if (e.target === zoomCanvas) return;
          if (e.target?.closest?.('button,input,select,label')) return;
          if (!canNavigateWaveform()) return;
          const t = _waveZoomTimeFromAreaEvent(e);
          if (t == null) return;
          followPlayhead = false;
          _seekPlayerToTime(t, { centerZoom: true });
          syncWaveScrollControl();
          e.preventDefault();
        });
      }

      const zoomCanvas = $('waveZoomCanvas');
      if (zoomCanvas && !zoomCanvas.__wired) {
        zoomCanvas.__wired = true;
        zoomCanvas.addEventListener('mousemove', (e) => {
          if (waveDragActive && waveDragMode === 'zoom-pan') return;
          setWaveHoverFromEvent(e);
        });
        zoomCanvas.addEventListener('mouseleave', () => {
          if (!waveDragActive) clearWaveHover();
        });
        zoomCanvas.addEventListener('mousedown', (e) => {
          if (!canNavigateWaveform()) return;
          const mark = manualMarkFromZoomEvent(e);
          if (mark && selectPrepMark(mark.type)) return;
          const t = _waveZoomTimeFromEvent(e);
          if (t == null) return;
          const state = waveWindowState();
          followPlayhead = false;
          waveDragActive = true;
          waveDragMode = 'zoom-pan';
          waveZoomDrag = {
            startX: e.clientX,
            startOffset: waveOffsetSec,
            windowSec: state.windowSec,
            duration: state.duration,
            width: state.width,
            clickTime: t,
            moved: false
          };
          syncWaveScrollControl();
          setWaveHoverFromEvent(e);
          e.preventDefault();
        });
      }
    }

    function wireWaveformPreplaySeekFallback() {
      if (window.__wavePreplaySeekFallbackWired) return;
      window.__wavePreplaySeekFallbackWired = true;
      const player = $('player');
      const handleOverview = (event) => {
        if (webAudioPlaying || (player && !player.paused)) return;
        if (!selectedTrackId() || !(durationForSeek() > 0)) return;
        if (event.target?.closest?.('button,input,select,label')) return;
        const frac = event.currentTarget?.id === 'waveCanvas'
          ? _waveFracFromEvent(event)
          : _waveFracFromOverviewAreaEvent(event);
        if (frac == null) return;
        _seekPlayerToFrac(frac, { centerZoom: true });
        event.preventDefault();
        event.stopPropagation();
      };
      const handleZoom = (event) => {
        if (webAudioPlaying || (player && !player.paused)) return;
        if (!selectedTrackId() || !(durationForSeek() > 0)) return;
        if (event.target?.closest?.('button,input,select,label')) return;
        const t = event.currentTarget?.id === 'waveZoomCanvas'
          ? _waveZoomTimeFromEvent(event)
          : _waveZoomTimeFromAreaEvent(event);
        if (t == null) return;
        followPlayhead = false;
        _seekPlayerToTime(t, { centerZoom: true });
        event.preventDefault();
        event.stopPropagation();
      };
      ['waveCanvas', 'waveBox'].forEach((id) => {
        const el = $(id);
        if (el) el.addEventListener('pointerdown', handleOverview, true);
      });
      ['waveZoomCanvas', 'waveZoomPanel'].forEach((id) => {
        const el = $(id);
        if (el) el.addEventListener('pointerdown', handleZoom, true);
      });
    }

    function startWaveformPlayheadLoop() {
      const player = $('player');
      if (!player) return;
      if (player.__waveLoop) return;
      player.__waveLoop = true;
      const tick = () => {
        if (lastWavePeaks) {
          drawWaveform(lastWavePeaks);
          drawZoomWaveform();
        }
        window.requestAnimationFrame(tick);
      };
      window.requestAnimationFrame(tick);
    }

    function syncWaveScrollControl() {
      const detail = window.__waveDetail;
      const scroll = $('waveScroll');
      const label = $('waveZoomLabel');
      const follow = $('waveFollow');
      if (!detail || !scroll) return;
      const duration = Number(detail.duration_sec || 0) || playbackDuration();
      const zoom = Math.max(1, Math.min(maxWaveZoom(), Number(waveZoom) || 1));
      const windowSec = duration > 0 ? duration / zoom : 0;
      const maxOffset = Math.max(0, duration - windowSec);
      scroll.disabled = !canNavigateWaveform() || maxOffset <= 0;
      scroll.value = maxOffset > 0 ? String(Math.round((waveOffsetSec / maxOffset) * 1000)) : '0';
      if (label) label.textContent = `${zoom.toFixed(1)}x`;
      if (follow) follow.classList.toggle('active', !!followPlayhead);
    }

    function wireWaveformDetailControls() {
      if (window.__waveDetailControlsWired) return;
      window.__waveDetailControlsWired = true;
      const zoomIn = $('waveZoomIn');
      const zoomOut = $('waveZoomOut');
      const scroll = $('waveScroll');
      const follow = $('waveFollow');
      const applyZoom = (nextZoom) => {
        const detail = window.__waveDetail;
        const duration = Number(detail?.duration_sec || 0) || playbackDuration();
        const center = currentPlaybackTime() || waveOffsetSec;
        waveZoom = Math.max(1, Math.min(maxWaveZoom(), Number(nextZoom) || 1));
        const windowSec = duration > 0 ? duration / waveZoom : 0;
        waveOffsetSec = Math.max(0, Math.min(Math.max(0, duration - windowSec), center - windowSec / 2));
        syncWaveScrollControl();
        drawZoomWaveform();
      };
      if (zoomIn) zoomIn.addEventListener('click', () => applyZoom(waveZoom * 1.6));
      if (zoomOut) zoomOut.addEventListener('click', () => applyZoom(waveZoom / 1.6));
      if (scroll) scroll.addEventListener('input', () => {
        followPlayhead = false;
        const detail = window.__waveDetail;
        const duration = Number(detail?.duration_sec || 0) || playbackDuration();
        const windowSec = duration > 0 ? duration / Math.max(1, waveZoom) : 0;
        const maxOffset = Math.max(0, duration - windowSec);
        waveOffsetSec = maxOffset * ((Number(scroll.value) || 0) / 1000);
        syncWaveScrollControl();
        drawZoomWaveform();
      });
      if (follow) follow.addEventListener('click', () => {
        followPlayhead = !followPlayhead;
        if (followPlayhead) updateFollowWaveWindow();
        syncWaveScrollControl();
        drawZoomWaveform();
      });
    }

    async function loadWaveform(trackId) {
      trackId = Number(trackId) || 0;
      lastWaveTrackId = trackId;
      lastWavePeaks = null;
      window.__waveDetail = null;
      window.__waveMarkers = [];
      window.__waveCues = [];
      window.__waveLoops = [];
      resetTrackPrepState();
      waveZoom = DEFAULT_WAVE_ZOOM;
      waveOffsetSec = 0;
      followPlayhead = true;
      $('waveBox').hidden = true;
      $('waveZoomPanel').hidden = true;
      $('trackPrepPanel').hidden = true;
      $('waveMeta').textContent = '';
      const resLabel = $('waveResolutionLabel');
      if (resLabel) resLabel.textContent = '';
      if (!trackId) return;
      try {
        wirePlayerBar();
        wireWaveformDetailControls();
        wireTrackPrepControls();
        const res = await fetch(`/api/track_waveform_detail?track_id=${encodeURIComponent(trackId)}`);
        const data = await res.json();
        if (lastWaveTrackId !== trackId) return;
        if (!data?.ok) return;
        window.__waveDetail = data;
        maybeEnableAudioFallback(trackId);
        const overview = {
          peaks: Array.isArray(data?.waveform) ? data.waveform : [],
          rgb: data?.waveform_rgb || null,
          energy: data?.waveform_energy
        };
        const peaks = overview?.peaks || null;
        window.__waveRGB = overview?.rgb || null;
        await loadTrackPrepMarks(trackId);
        refreshWaveDisplayItems();
        if (!Array.isArray(peaks) || !peaks.length) return;
        lastWavePeaks = peaks;
        $('waveBox').hidden = false;
        $('waveZoomPanel').hidden = false;
        $('trackPrepPanel').hidden = false;
        const energy = (typeof overview?.energy === 'number') ? overview.energy : null;
        const p = data?.source || {};
        const cueCount = Array.isArray(data?.cues) ? data.cues.length : 0;
        const loopCount = Array.isArray(data?.loops) ? data.loops.length : 0;
        const prepCount = (trackPrep.marks || []).length;
        const prepLoopCount = (trackPrep.loops || []).length;
        const markCounts = [];
        if (cueCount) markCounts.push(`cues:${cueCount}`);
        if (loopCount) markCounts.push(`loops:${loopCount}`);
        if (prepCount) markCounts.push(`prep:${prepCount}`);
        if (prepLoopCount) markCounts.push(`prep loops:${prepLoopCount}`);
        if (p.beat_grid) markCounts.push(`beats:${p.beat_grid}`);
        const marksText = markCounts.length ? ` · ${markCounts.join(' ')}` : '';
        $('waveMeta').textContent = energy == null ? `${peaks.length} pts${marksText}` : `${peaks.length} pts · energy ${energy}${marksText}`;
        if (resLabel) {
          resLabel.textContent = data?.waveform_resolution === 'engine_overview_1024'
            ? `Engine overview ${peaks.length} pts`
            : 'Hi-res waveform';
        }
        syncTrackPrepControls();
        syncWaveScrollControl();
        wireWaveformScrub();
      wireWaveformPreplaySeekFallback();
        startWaveformPlayheadLoop();
        drawWaveform(peaks);
        drawZoomWaveform();
      } catch (e) {
        // ignore
      }
    }

