(() => {
  const version = '1.5.40';
  const parts = ["app-core.js", "app-prep-config.js", "app-prep.js", "app-prep-batch.js", "app-prep-manual.js", "app-prep-storage.js", "app-waveform.js", "app-actions.js", "app-boot.js"];
  for (const part of parts) {
    document.write(`<script src="/static/${part}?v=${version}"><\/script>`);
  }
})();
