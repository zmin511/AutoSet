(() => {
  'use strict';

  const byId = id => document.getElementById(id);

  const TEXT = {
    loading: '\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430...',
    ready: '\u0413\u043e\u0442\u043e\u0432\u043e',
    statusError: '\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0442\u0430\u0442\u0443\u0441\u0430',
    error: '\u041e\u0448\u0438\u0431\u043a\u0430',
    update: '\u041e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435...',
    rebuild: '\u041f\u043e\u043b\u043d\u044b\u0439 \u043f\u0435\u0440\u0435\u0441\u0447\u0451\u0442...',
    startUpdate: '\u0417\u0430\u043f\u0443\u0441\u043a \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f...',
    startRebuild: '\u0417\u0430\u043f\u0443\u0441\u043a \u043f\u043e\u043b\u043d\u043e\u0433\u043e \u043f\u0435\u0440\u0435\u0441\u0447\u0451\u0442\u0430...',
    startFailed: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0430\u043d\u0430\u043b\u0438\u0437',
    profiles: '\u043f\u0440\u043e\u0444\u0438\u043b\u0435\u0439',
    total: '\u0432\u0441\u0435\u0433\u043e',
    analyzed: '\u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u043e',
    skipped: '\u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e',
    pruned: '\u0443\u0434\u0430\u043b\u0435\u043d\u043e',
    errors: '\u043e\u0448\u0438\u0431\u043e\u043a',
    confirm:
      '\u041f\u0435\u0440\u0435\u0441\u0447\u0438\u0442\u0430\u0442\u044c \u0432\u0441\u0435 \u043f\u0440\u043e\u0444\u0438\u043b\u0438 '
      + '\u0438 \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u0438\u0437 analysis.db '
      + '\u0437\u0430\u043f\u0438\u0441\u0438 \u0442\u0440\u0435\u043a\u043e\u0432, '
      + '\u043a\u043e\u0442\u043e\u0440\u044b\u0445 \u0431\u043e\u043b\u044c\u0448\u0435 \u043d\u0435\u0442 \u0432 Engine DJ?',
  };

  let pollTimer = null;

  function formatBytes(value) {
    const bytes = Number(value || 0);

    if (!Number.isFinite(bytes) || bytes <= 0) {
      return '0 MB';
    }

    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }

  function formatResult(result) {
    if (!result) return '';

    return [
      `${TEXT.total} ${Number(result.total || 0)}`,
      `${TEXT.analyzed} ${Number(result.analyzed || 0)}`,
      `${TEXT.skipped} ${Number(result.skipped || 0)}`,
      `${TEXT.pruned} ${Number(result.pruned || 0)}`,
      `${TEXT.errors} ${Number(result.errors || 0)}`,
    ].join(' \u00b7 ');
  }

  function disableButtons(disabled) {
    const updateButton = byId('analysisUpdate');
    const rebuildButton = byId('analysisRebuild');

    if (updateButton) updateButton.disabled = disabled;
    if (rebuildButton) rebuildButton.disabled = disabled;
  }

  function renderStatus(data) {
    const status = byId('analysisStatus');
    const details = byId('analysisDetails');

    if (!status || !details) return;

    const progress = byId('analysisProgress');

    status.classList.remove('running', 'error');

    if (progress) {
      const percent = data?.running
        ? Math.max(0, Math.min(100, Number(data.percent || 0)))
        : 0;

      progress.style.width = `${percent}%`;
    }

    if (!data?.ok) {
      status.textContent = TEXT.statusError;
      status.classList.add('error');
      details.textContent = data?.error || '';
      disableButtons(false);
      return;
    }

    disableButtons(Boolean(data.running));

    const databaseText = [
      `${Number(data.profile_count || 0)} ${TEXT.profiles}`,
      formatBytes(data.database_size),
    ].join(' \u00b7 ');

    if (data.running) {
      const processed = Number(data.processed || 0);
      const total = Number(data.total || 0);
      const percent = Number(data.percent || 0);
      const elapsed = Number(data.elapsed_seconds || 0);

      const minutes = Math.floor(elapsed / 60);
      const seconds = Math.floor(elapsed % 60);

      const elapsedText =
        `${String(minutes).padStart(2, '0')}:`
        + `${String(seconds).padStart(2, '0')}`;

      status.textContent = data.mode === 'rebuild'
        ? TEXT.rebuild
        : TEXT.update;

      status.classList.add('running');

      details.textContent = [
        total
          ? `${processed} / ${total} (${percent.toFixed(1)}%)`
          : databaseText,
        `${TEXT.analyzed} ${Number(data.analyzed || 0)}`,
        `${TEXT.skipped} ${Number(data.skipped || 0)}`,
        `${TEXT.errors} ${Number(data.errors || 0)}`,
        elapsedText,
      ].join(' \u00b7 ');

      return;
    }

    if (data.error) {
      status.textContent = TEXT.error;
      status.classList.add('error');
      details.textContent = data.error;
      return;
    }

    status.textContent = TEXT.ready;

    details.textContent = [
      databaseText,
      formatResult(data.result),
    ].filter(Boolean).join(' \u00b7 ');
  }

  async function loadStatus() {
    try {
      const response = await fetch(
        '/api/analysis-status',
        { cache: 'no-store' }
      );

      const data = await response.json();
      renderStatus(data);

    } catch (error) {
      renderStatus({
        ok: false,
        error: String(error),
      });
    }
  }

  async function startAnalysis(mode) {
    const endpoint = mode === 'rebuild'
      ? '/api/analysis-rebuild'
      : '/api/analysis-update';

    const status = byId('analysisStatus');
    const details = byId('analysisDetails');

    disableButtons(true);

    if (status) {
      status.textContent = mode === 'rebuild'
        ? TEXT.startRebuild
        : TEXT.startUpdate;

      status.classList.add('running');
    }

    if (details) {
      details.textContent = '';
    }

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: '{}',
      });

      const data = await response.json();

      if (!data.ok && !data.started) {
        throw new Error(
          data.error || TEXT.startFailed
        );
      }

      await loadStatus();

    } catch (error) {
      renderStatus({
        ok: false,
        error: String(error),
      });
    }
  }

  function init() {
    const updateButton = byId('analysisUpdate');
    const rebuildButton = byId('analysisRebuild');

    if (!updateButton || !rebuildButton) {
      return;
    }

    updateButton.addEventListener(
      'click',
      () => startAnalysis('update')
    );

    rebuildButton.addEventListener(
      'click',
      () => {
        if (window.confirm(TEXT.confirm)) {
          startAnalysis('rebuild');
        }
      }
    );

    loadStatus();

    pollTimer = window.setInterval(
      loadStatus,
      1500
    );

    window.addEventListener(
      'beforeunload',
      () => {
        if (pollTimer) {
          window.clearInterval(pollTimer);
        }
      }
    );
  }

  init();
})();
