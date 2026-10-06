/** Operator controls bound to the real Digital Twin APIs and map renderers. */
class ControlsManager {
  constructor(app) {
    this.app = app;
    this.bindControls();
  }

  bindControls() {
    document.getElementById('btnStart')?.addEventListener('click', () => this.app.startBoth());
    document.getElementById('btnPlayPause')?.addEventListener('click', () => this.app.togglePause());
    document.getElementById('btnReset')?.addEventListener('click', () => this.app.restartBoth());
    document.getElementById('btnScenarioNormal')?.addEventListener('click', () => this.app.selectScenario('normal_day'));
    document.getElementById('btnScenarioEvent')?.addEventListener('click', () => this.app.selectScenario('event_day'));
    document.querySelectorAll('.speed-btn').forEach(button => button.addEventListener('click', () => {
      this.app.setSpeed(Number(button.dataset.speed)).then(success => {
        if (success) document.querySelectorAll('.speed-btn').forEach(item => item.classList.toggle('active', item === button));
      });
    }));
    document.querySelectorAll('.cam-preset-btn').forEach(button => button.addEventListener('click', () => {
      const target = button.dataset.target;
      document.querySelectorAll(`.cam-preset-btn[data-target="${target}"]`).forEach(item => item.classList.toggle('active', item === button));
      for (const renderer of this.app.renderers) renderer.focusCamera(target);
    }));
    document.querySelectorAll('[data-layer]').forEach(input => input.addEventListener('change', () => {
      this.app.setLayer(input.dataset.layer, input.checked);
    }));
    document.querySelectorAll('.dock-tab').forEach(button => button.addEventListener('click', () => {
      document.querySelectorAll('.dock-tab').forEach(item => item.classList.toggle('active', item === button));
      document.querySelectorAll('.dock-pane').forEach(pane => pane.classList.toggle('active', pane.id === `dock-${button.dataset.tab}`));
      requestAnimationFrame(() => this.app.renderers.forEach(renderer => renderer.onResize()));
    }));
    document.getElementById('btnClearSelection')?.addEventListener('click', () => this.app.clearSelection());
    document.getElementById('diversionPercent')?.addEventListener('input', event => {
      document.getElementById('diversionValue').textContent = `${event.target.value}%`;
      this.app.highlightSelectedCorridor();
    });
    ['routeSource', 'routeAlternative'].forEach(id => document.getElementById(id)?.addEventListener('change', () => this.app.highlightSelectedCorridor()));
    ['vipEnabled', 'vipCorridor', 'constructionEnabled', 'constructionCorridor'].forEach(id => document.getElementById(id)?.addEventListener('change', () => this.app.highlightSelectedCorridor()));
    document.getElementById('syncCameras')?.addEventListener('change', event => { this.app.syncCameras = event.target.checked; });
    document.querySelectorAll('.log-filter').forEach(button => button.addEventListener('click', () => {
      document.querySelectorAll('.log-filter').forEach(item => item.classList.toggle('active', item === button));
      this.app.renderEvents(button.dataset.filter);
    }));
  }
}
