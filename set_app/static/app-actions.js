    function parseCamelot(value) {
      const m = String(value || '').trim().match(/^(\d{1,2})([AB])$/i);
      if (!m) return null;
      const num = Number(m[1]);
      if (!Number.isFinite(num) || num < 1 || num > 12) return null;
      return { num, mode: m[2].toUpperCase() };
    }

    function wrapCamelotNumber(num) {
      const n = Number(num);
      return ((n - 1 + 12) % 12) + 1;
    }

    function formatCamelotRange(center, maxStep) {
      const max = Math.max(0, Math.min(12, Number(maxStep) || 0));
      if (max >= 6) return '1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12';
      const chunks = [];
      chunks.push(String(center));
      for (let d = 1; d <= max; d++) {
        chunks.push(String(wrapCamelotNumber(center + d)));
      }
      for (let d = 1; d <= max; d++) {
        chunks.push(String(wrapCamelotNumber(center - d)));
      }
      return chunks.join(', ');
    }

    function updateKeyStepHint() {
      const input = $('keyStep');
      if (!input) return;
      const step = Math.max(0, Math.min(12, Number(input.value) || 0));
      const camelot = selectedTrack?.camelot || '';
      const parsed = parseCamelot(camelot);
      if (!parsed) {
        input.title = `±${step}: входят только числа Camelot вокруг выбранного трека. ±6 и выше включает все 1–12. A/B не увеличивает расстояние.`;
        return;
      }
      input.title = `От ${parsed.num}${parsed.mode} при ±${step} входят числа Camelot: ${formatCamelotRange(parsed.num, step)}. Для каждого числа подходят A и B. A/B не увеличивает расстояние.`;
    }

    async function build() {
      if (!selectedTrack?.id) return;
      $('build').disabled = true;
      $('enginePlaylist').disabled = true;
      lastBuiltSetFolder = '';
      $('output').textContent = 'Создаю сет...';
      $('status').className = 'status';
      $('status').textContent = 'Копирую треки и пишу плейлисты...';
      try {
        const res = await fetch('/api/build', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            track_id: selectedTrack.id,
            role: $('role').value,
            minutes: Number($('minutes').value),
            max_key_step: Number($('keyStep').value),
            bpm_window: Number($('bpmWindow').value),
            style_filter: selectedStyles()
          })
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok ? 'status ok' : 'status bad';
        $('status').textContent = data.ok ? `Сет создан: ${data.set_folder}` : 'Сборка завершилась с ошибкой';
        if (data.ok && data.set_folder) {
          lastBuiltSetFolder = data.set_folder;
          $('enginePlaylist').disabled = !selectedTrack?.id;
        }
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка запуска';
      } finally {
        $('build').disabled = false;
      }
    }

    async function createEnginePlaylist() {
      if (!selectedTrack?.id) return;
      const folder = ($('engineFolder')?.value || '').trim() || 'Event';

      $('enginePlaylist').disabled = true;
      $('output').textContent = 'Создаю плейлист в Engine DB (ссылками, без копирования файлов)...';
      $('status').className = 'status';
      $('status').textContent = 'Пишу плейлист в Engine DB...';
      try {
        const res = await fetch('/api/engine-playlist', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            track_id: selectedTrack.id,
            role: $('role').value,
            minutes: Number($('minutes').value),
            max_key_step: Number($('keyStep').value),
            bpm_window: Number($('bpmWindow').value),
            style_filter: selectedStyles(),
            folder
          })
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok ? 'status ok' : 'status bad';
        const createdTitle = data.engine_playlist_title || '';
        $('status').textContent = data.ok ? `Плейлист Engine создан: ${folder}/${createdTitle}` : 'Не удалось создать плейлист Engine';
        if (data.ok && data.local_playlist_folder) {
          $('output').textContent += `\n\nLocal playlist folder: ${data.local_playlist_folder}\nM3U: ${data.local_m3u}\nCSV: ${data.local_csv}`;
        }
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка создания плейлиста Engine';
      } finally {
        $('enginePlaylist').disabled = !selectedTrack?.id;
      }
    }

    async function writeEnergyRatings() {
      $('writeEnergyRatings').disabled = true;
      $('output').textContent = 'Записываю энергию waveform в звездочки Engine DJ для текущей папки...';
      try {
        const res = await fetch('/api/write-energy-ratings', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ path: currentPath })
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok && !data.file_tags_warning ? 'status ok' : 'status bad';
        $('status').textContent = data.ok ? tagWriteStatusMessage(data, 'Звездочки энергии обновлены') : 'Не удалось обновить звездочки';
        await browse(currentPath);
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка обновления звездочек';
      } finally {
        $('writeEnergyRatings').disabled = false;
      }
    }

    async function writeAllEnergyRatings() {
      const ok = window.confirm('Записать расчетную энергию в звезды Engine для всей медиатеки Music? Текущие рейтинги Track.rating будут перезаписаны.');
      if (!ok) return;
      $('writeAllEnergyRatings').disabled = true;
      $('output').textContent = 'Записываю энергию waveform в звездочки Engine DJ для всей медиатеки Music...';
      try {
        const res = await fetch('/api/write-all-energy-ratings', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({})
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok && !data.file_tags_warning ? 'status ok' : 'status bad';
        $('status').textContent = data.ok ? tagWriteStatusMessage(data, 'Все звездочки энергии обновлены') : 'Не удалось обновить все звездочки';
        await browse(currentPath);
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка обновления всех звездочек';
      } finally {
        $('writeAllEnergyRatings').disabled = false;
      }
    }

    function rememberStyleSuggestions(data) {
      styleSuggestions.clear();
      selectedStyleFiles.clear();
      (data.suggestions || []).forEach(item => {
        if (!item.file) return;
        styleSuggestions.set(normPath(item.file), item);
      });
      renderRows();
    }

    async function applyStyleDetailsForFiles(files, ask = true) {
      const cleanFiles = [...new Set((files || []).filter(Boolean))];
      if (!cleanFiles.length) {
        $('status').className = 'status bad';
        $('status').textContent = 'Нет выбранных подсказок для применения';
        return;
      }
      if (ask) {
        const ok = window.confirm(`Добавить подстили к выбранным трекам: ${cleanFiles.length}? Старые жанры не удаляются.`);
        if (!ok) return;
      }
      const buttons = ['previewStyleDetails', 'applyCheckedStyleDetails', 'applyStyleDetails'].map(id => $(id));
      buttons.forEach(btn => { btn.disabled = true; });
      $('output').textContent = 'Добавляю выбранные подстили в Engine DB и файлы...';
      try {
        const res = await fetch('/api/detail-styles', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            path: currentPath,
            recursive: $('styleRecursive').checked,
            apply: true,
            min_confidence: 'medium',
            source: 'online',
            files: cleanFiles
          })
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok && !data.file_tags_warning ? 'status ok' : 'status bad';
        $('status').textContent = data.ok ? tagWriteStatusMessage(data, `Подстили добавлены: ${data.updated}`) : 'Не удалось применить подстили';
        if (data.ok) {
          await loadStyles();
          await browse(currentPath);
        }
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка применения подстилей';
      } finally {
        buttons.forEach(btn => { btn.disabled = false; });
      }
    }

    function drawZoomWaveform() {
      const canvas = $('waveZoomCanvas');
      const detail = window.__waveDetail;
      if (!canvas || !detail) return;
      const state = setupWaveCanvas(canvas);
      if (!state) return;
      const { ctx, w, h, dpr } = state;

      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = '#0b0d0f';
      ctx.fillRect(0, 0, w, h);

      const peaks = Array.isArray(detail.waveform) ? detail.waveform : [];
      const duration = Number(detail.duration_sec || 0) || playbackDuration();
      if (!peaks.length || !duration) return;
      waveZoom = Math.max(1, Math.min(maxWaveZoom(), Number(waveZoom) || 1));
      updateFollowWaveWindow();
      const zoom = Math.max(1, Math.min(maxWaveZoom(), Number(waveZoom) || 1));
      const windowSec = duration / zoom;
      const maxOffset = Math.max(0, duration - windowSec);
      waveOffsetSec = Math.max(0, Math.min(maxOffset, Number(waveOffsetSec) || 0));
      syncWaveScrollControl();
      const start = waveOffsetSec;
      const end = Math.min(duration, start + windowSec);
      const span = Math.max(0.001, end - start);
      const mid = h * 0.55;
      const ampMax = h * 0.40;
      const rgb = detail.waveform_rgb;
      const hasRgb = rgb && Array.isArray(rgb.r) && Array.isArray(rgb.g) && Array.isArray(rgb.b) && rgb.r.length === peaks.length;

      const timeToX = (sec) => ((Number(sec) - start) / span) * w;
      const drawLayer = (arr, color, gain, alpha) => {
        const samples = Math.max(160, Math.floor(w));
        ctx.save();
        ctx.globalAlpha = alpha * 0.62;
        ctx.fillStyle = color;
        ctx.beginPath();
        for (let i = 0; i <= samples; i++) {
          const x = (i / samples) * w;
          const sec = start + (x / Math.max(1, w)) * span;
          const p = sampleWave(arr, sec, duration);
          const amp = (p / 255) * ampMax * gain;
          const y = mid - amp;
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        for (let i = samples; i >= 0; i--) {
          const x = (i / samples) * w;
          const sec = start + (x / Math.max(1, w)) * span;
          const p = sampleWave(arr, sec, duration);
          const amp = (p / 255) * ampMax * gain * 0.38;
          ctx.lineTo(x, mid + amp);
        }
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.restore();
      };
      if (hasRgb) {
        drawLayer(rgb.b, 'rgba(73,160,236,1)', 1.0, 0.95);
        drawLayer(rgb.g, 'rgba(55,197,143,1)', 0.88, 0.95);
        drawLayer(rgb.r, 'rgba(238,242,245,1)', 0.74, 0.9);
      } else {
        drawLayer(peaks, 'rgba(73,160,236,1)', 1.0, 0.95);
      }

      const beats = Array.isArray(detail.beat_grid) ? detail.beat_grid : [];
      for (const beat of beats) {
        const t = Number(beat.time_sec);
        if (!Number.isFinite(t) || t < start || t > end) continue;
        const x = Math.floor(timeToX(t)) + 0.5;
        const phrase = !!beat.is_phrase_start;
        const bar = !!beat.is_bar_start;
        ctx.strokeStyle = phrase ? 'rgba(255,255,255,0.55)' : (bar ? 'rgba(255,255,255,0.34)' : 'rgba(255,255,255,0.13)');
        ctx.lineWidth = phrase ? 2.2 : (bar ? 1.6 : 1);
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
      }
      ctx.lineWidth = 1;

      const cues = Array.isArray(window.__waveCues) ? window.__waveCues : [];
      ctx.font = `${Math.max(10, Math.floor(11 * dpr))}px Segoe UI, Inter, Arial, sans-serif`;
      ctx.textBaseline = 'top';
      for (const cue of cues) {
        const t = Number(cue.time_sec ?? cue.pos_s);
        if (!Number.isFinite(t) || t < start || t > end) continue;
        const x = Math.floor(timeToX(t)) + 0.5;
        const manualCue = cue.source === 'manual';
        const suggestedCue = cue.source === 'suggested';
        const selectedCue = manualCue && cue.type === selectedPrepMarkType;
        ctx.setLineDash(suggestedCue ? [6 * dpr, 4 * dpr] : []);
        ctx.strokeStyle = selectedCue ? 'rgba(255,224,108,0.98)' : (cue.color || (suggestedCue ? 'rgba(255,224,108,0.95)' : (manualCue ? 'rgba(55,197,143,0.95)' : 'rgba(73,160,236,0.95)')));
        ctx.lineWidth = selectedCue ? 3 : 2;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
        ctx.setLineDash([]);
        const baseLabel = cue.name || cue.label || 'Cue';
        const label = (manualCue || suggestedCue) ? `${baseLabel} ${fmtTime(t)}` : baseLabel;
        const labelW = Math.min(150 * dpr, ctx.measureText(label).width + 10 * dpr);
        ctx.fillStyle = selectedCue ? 'rgba(255,224,108,0.20)' : (suggestedCue ? 'rgba(255,224,108,0.12)' : 'rgba(8,12,16,0.82)');
        ctx.fillRect(Math.max(0, x + 4), 4 * dpr, labelW, 18 * dpr);
        ctx.fillStyle = selectedCue ? '#fff4c2' : '#e7f0f5';
        ctx.fillText(label, Math.max(2 * dpr, x + 8), 7 * dpr);
      }
      ctx.lineWidth = 1;

      const loops = Array.isArray(window.__waveLoops) ? window.__waveLoops : [];
      for (const loop of loops) {
        const a = Number(loop.start_sec ?? loop.start_s);
        const b = Number(loop.end_sec ?? loop.end_s);
        if (!Number.isFinite(a) || !Number.isFinite(b) || b < start || a > end) continue;
        const x1 = Math.max(0, Math.min(w, timeToX(a)));
        const x2 = Math.max(0, Math.min(w, timeToX(b)));
        const manualLoop = loop.source === 'manual';
        const suggestedLoop = loop.source === 'suggested';
        ctx.setLineDash(suggestedLoop ? [6 * dpr, 4 * dpr] : []);
        ctx.fillStyle = manualLoop ? 'rgba(255,138,61,0.24)' : (suggestedLoop ? 'rgba(255,224,108,0.14)' : 'rgba(255,138,61,0.18)');
        ctx.strokeStyle = loop.color || (suggestedLoop ? 'rgba(255,224,108,0.92)' : 'rgba(255,138,61,0.82)');
        ctx.fillRect(x1, 0, Math.max(1, x2 - x1), h);
        ctx.strokeRect(x1, 0, Math.max(1, x2 - x1), h);
        ctx.setLineDash([]);
        const label = (manualLoop || suggestedLoop)
          ? `${loopRoleLabel(loop, true)} ${fmtTime(a)}–${fmtTime(b)}`
          : ((loop.name || loop.label || '').trim() || 'Loop');
        const textW = ctx.measureText(label).width;
        const tx = Math.max(2 * dpr, Math.min(w - textW - 2 * dpr, (x1 + x2) / 2 - textW / 2));
        ctx.fillStyle = 'rgba(8,12,16,0.78)';
        ctx.fillRect(Math.max(0, tx - 4 * dpr), h - 22 * dpr, Math.min(w, textW + 8 * dpr), 18 * dpr);
        ctx.fillStyle = suggestedLoop ? '#fff4c2' : '#ffe0aa';
        ctx.fillText(label, tx, h - 19 * dpr);
      }

      const cur = currentPlaybackTime();
      if (Number.isFinite(cur) && cur >= start && cur <= end) {
        const x = Math.floor(timeToX(cur)) + 0.5;
        ctx.strokeStyle = 'rgba(255,95,95,0.88)';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
        ctx.lineWidth = 1;
      }

      if (waveHover.active && Number.isFinite(Number(waveHover.time_sec))) {
        const hoverTime = Number(waveHover.time_sec);
        if (hoverTime >= start && hoverTime <= end) {
          const x = Math.floor(timeToX(hoverTime)) + 0.5;
          ctx.strokeStyle = 'rgba(231,240,245,0.58)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(x, 0);
          ctx.lineTo(x, h);
          ctx.stroke();
        }
        const snapTime = Number(waveHover.snap_time_sec);
        if (waveHover.snapped && Number.isFinite(snapTime) && snapTime >= start && snapTime <= end) {
          const sx = Math.floor(timeToX(snapTime)) + 0.5;
          ctx.strokeStyle = 'rgba(255,224,108,0.96)';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.moveTo(sx, 0);
          ctx.lineTo(sx, h);
          ctx.stroke();
          ctx.lineWidth = 1;
        }
        const label = `${fmtTimePrecise(hoverTime, true)}  ${waveHover.snap_kind || 'Snap'} ${fmtTimePrecise(snapTime, true)}`;
        const labelW = Math.min(w - 12 * dpr, ctx.measureText(label).width + 12 * dpr);
        const labelX = Math.max(4 * dpr, Math.min(w - labelW - 4 * dpr, timeToX(hoverTime) + 8 * dpr));
        ctx.fillStyle = 'rgba(8,12,16,0.88)';
        ctx.fillRect(labelX, 26 * dpr, labelW, 20 * dpr);
        ctx.fillStyle = '#fff4c2';
        ctx.textBaseline = 'top';
        ctx.fillText(label, labelX + 6 * dpr, 29 * dpr);
      }

      ctx.fillStyle = 'rgba(154,167,178,0.95)';
      ctx.textBaseline = 'bottom';
      ctx.fillText(`${fmtTime(start)} - ${fmtTime(end)} · ${zoom.toFixed(1)}x`, 8 * dpr, h - 6 * dpr);
    }

    async function detailStyles(apply = false, checkedOnly = false) {
      if (apply && checkedOnly && !styleSuggestions.size) {
        $('status').className = 'status bad';
        $('status').textContent = 'Сначала нажми "Найти стили онлайн" и отметь нужные треки';
        return;
      }
      if (apply && styleSuggestions.size) {
        const files = selectedSuggestionFiles(!checkedOnly);
        await applyStyleDetailsForFiles(files);
        return;
      }
      if (apply) {
        const ok = window.confirm('Добавить все предложенные подстили в жанры текущей папки? Старые жанры не удаляются.');
        if (!ok) return;
      }
      const btn = $(apply ? 'applyStyleDetails' : 'previewStyleDetails');
      btn.disabled = true;
      $('output').textContent = apply ? 'Добавляю подстили в Engine DB и файлы...' : 'Ищу подстили во внешних источниках по всей папке. Это может занять время...';
      try {
        const res = await fetch('/api/detail-styles', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            path: currentPath,
            recursive: $('styleRecursive').checked,
            apply,
            min_confidence: 'medium',
            source: 'online'
          })
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok && !data.file_tags_warning ? 'status ok' : 'status bad';
        $('status').textContent = data.ok
          ? (apply ? tagWriteStatusMessage(data, `Подстили добавлены: ${data.updated}`) : `Предложений по стилям: ${data.suggestion_count || 0}`)
          : 'Не удалось детализировать стили';
        if (data.ok && !apply) {
          rememberStyleSuggestions(data);
        }
        if (data.ok && apply) {
          await loadStyles();
          await browse(currentPath);
        }
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка детализации стилей';
      } finally {
        btn.disabled = false;
      }
    }

    async function bulkGenre(action) {
      const tag = $('tagAdd').value.trim();
      const find = $('tagFind').value.trim();
      const replace = $('tagReplace').value.trim();
      if (action === 'append' && !tag) {
        $('status').className = 'status bad';
        $('status').textContent = 'Укажи тег для добавления';
        return;
      }
      if ((action === 'replace' || action === 'remove') && !find) {
        $('status').className = 'status bad';
        $('status').textContent = 'Укажи тег для поиска';
        return;
      }
      const buttonMap = { append: 'addGenreTag', replace: 'replaceGenreTag', remove: 'removeGenreTag' };
      const btn = $(buttonMap[action]);
      btn.disabled = true;
      $('output').textContent = 'Обновляю жанры в Engine DB и файлах...';
      try {
        const res = await fetch('/api/bulk-genre', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            path: currentPath,
            recursive: $('tagRecursive').checked,
            action,
            tag,
            find,
            replace
          })
        });
        const data = await res.json();
        $('output').textContent = data.output || data.error || 'Нет вывода.';
        $('status').className = data.ok && !data.file_tags_warning ? 'status ok' : 'status bad';
        $('status').textContent = data.ok ? tagWriteStatusMessage(data, 'Жанры обновлены') : 'Не удалось обновить жанры';
        await loadStyles();
        await browse(currentPath);
      } catch (err) {
        $('output').textContent = String(err);
        $('status').className = 'status bad';
        $('status').textContent = 'Ошибка обновления жанров';
      } finally {
        btn.disabled = false;
      }
    }

