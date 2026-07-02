    $('search').addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(search, 220);
    });
    $('limit').addEventListener('change', search);
    $('clearSearch').addEventListener('click', () => browse(currentPath));
    $('reloadFolder').addEventListener('click', () => browse(currentPath));
    $('writeEnergyRatings').addEventListener('click', writeEnergyRatings);
    $('writeAllEnergyRatings').addEventListener('click', writeAllEnergyRatings);
    $('previewStyleDetails').addEventListener('click', () => detailStyles(false));
    $('applyCheckedStyleDetails').addEventListener('click', () => detailStyles(true, true));
    $('applyStyleDetails').addEventListener('click', () => detailStyles(true, false));
    $('addGenreTag').addEventListener('click', () => bulkGenre('append'));
    $('replaceGenreTag').addEventListener('click', () => bulkGenre('replace'));
    $('removeGenreTag').addEventListener('click', () => bulkGenre('remove'));
    $('savePaths').addEventListener('click', savePaths);
    $('pickMusic').addEventListener('click', () => openPicker('folder', 'musicRoot'));
    $('pickDb').addEventListener('click', () => openPicker('db', 'dbPath'));
    $('pickerClose').addEventListener('click', closePicker);
    $('pickerUp').addEventListener('click', () => picker.parent && loadPicker(picker.parent));
    $('pickerSelect').addEventListener('click', selectPickerPath);
    $('pickerModal').addEventListener('click', (event) => {
      if (event.target === $('pickerModal')) closePicker();
    });
    $('build').addEventListener('click', build);
    $('enginePlaylist').addEventListener('click', createEnginePlaylist);
    $('keyStep').addEventListener('input', updateKeyStepHint);
    window.addEventListener('resize', () => lastWavePeaks && drawWaveform(lastWavePeaks));
    $('player').addEventListener('loadedmetadata', () => {
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    });
    $('player').addEventListener('canplay', () => {
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    });
    $('player').addEventListener('timeupdate', () => {
      const player = $('player');
      const cur = Number(player?.currentTime);
      const cursor = Number(playbackCursorSec);
      const pending = pendingSeekTime();
      const keepPinned = player?.paused && playbackCursorPinned && Number.isFinite(cursor) && Math.abs(cur - cursor) > 0.2 && (pending == null || Math.abs(pending - cursor) < 0.2);
      if (Number.isFinite(cur) && cur >= 0 && !keepPinned) { playbackCursorSec = cur; playbackCursorPinned = true; }
      if (lastWavePeaks) drawWaveform(lastWavePeaks);
      drawZoomWaveform();
    });
    wirePlayerBar();
    loadStyles().then(() => loadConfig()).then(() => browse(''));
