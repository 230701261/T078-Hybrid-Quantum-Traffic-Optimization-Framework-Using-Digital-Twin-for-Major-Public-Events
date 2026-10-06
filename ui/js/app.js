/** Live operations UI. All changing values arrive from the Digital Twin APIs or /ws/simulation. */
class DigitalTwinApp {
  constructor() {
    this.renderers = [new SimulationRenderer3D('classicalMap'), new SimulationRenderer3D('quantumMap')];
    this.themePreference = this.readThemePreference();
    this.setTheme(this.themePreference || this.systemTheme(), false);
    this.renderers[0].onEntitySelected = item => this.inspect(item, 'classical');
    this.renderers[1].onEntitySelected = item => this.inspect(item, 'quantum');
    this.controls = new ControlsManager(this);
    this.snapshots = {};
    this.events = [];
    this.currentPairId = null;
    this.config = null;
    this.scenario = 'normal_day';
    this.paused = false;
    this.lifecycle = 'CHECKING';
    this.comparison = null;
    this.syncCameras = true;
    this.syncingCameras = false;
    this.renderers.forEach((renderer, index) => renderer.controls?.addEventListener('change', () => {
      if (!this.syncCameras || this.syncingCameras) return;
      const other = this.renderers[1 - index];
      if (!other.controls) return;
      this.syncingCameras = true;
      other.camera.position.copy(renderer.camera.position);
      other.camera.quaternion.copy(renderer.camera.quaternion);
      other.controls.target.copy(renderer.controls.target);
      other.controls.update();
      this.syncingCameras = false;
    }));
    this.lastPaint = 0;
    this.lastComparisonPoll = 0;
    document.getElementById('themeToggle')?.addEventListener('click', () => {
      const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      this.setTheme(next, true);
    });
    this.systemThemeListener = event => {
      if (!this.readThemePreference()) this.setTheme(event.matches ? 'light' : 'dark', false);
    };
    window.matchMedia?.('(prefers-color-scheme: light)').addEventListener?.('change', this.systemThemeListener);
    this.connect();
    this.loadConfig();
    this.loadLatestPlan();
    this.refreshSystemStatus();
    document.getElementById('btnApplyBoth')?.addEventListener('click', () => this.applyBoth());
    document.getElementById('btnApplyRoute')?.addEventListener('click', () => this.applyRoute());
    document.getElementById('btnRerouteVehicle')?.addEventListener('click', () => this.rerouteActiveVehicle());
    document.getElementById('btnApplySignal')?.addEventListener('click', () => this.applySignal());
    document.getElementById('signalTls')?.addEventListener('change', () => this.loadSignalPhases());
    document.getElementById('signalPhase')?.addEventListener('change', () => this.showSignalPhase());
    document.getElementById('btnTriggerQuantum')?.addEventListener('click', () => this.optimize());
  }

  readThemePreference() {
    try {
      const value = localStorage.getItem('chepauk-theme');
      return value === 'light' || value === 'dark' ? value : null;
    } catch { return null; }
  }

  systemTheme() {
    return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  setTheme(theme, persist = false) {
    const selected = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = selected;
    document.documentElement.style.colorScheme = selected;
    const button = document.getElementById('themeToggle');
    if (button) {
      button.textContent = selected === 'dark' ? 'Light' : 'Dark';
      button.setAttribute('aria-label', `Switch to ${selected === 'dark' ? 'light' : 'dark'} theme`);
      button.setAttribute('aria-pressed', String(selected === 'light'));
    }
    this.renderers?.forEach(renderer => renderer.setTheme?.(selected));
    if (persist) {
      this.themePreference = selected;
      try { localStorage.setItem('chepauk-theme', selected); } catch { /* Private mode may disable persistence. */ }
    }
  }

  async api(path, options = {}) {
    const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || `HTTP ${response.status}`));
    return data;
  }

  async loadConfig() {
    try {
      const [traffic, routeData, signalData, constraintData] = await Promise.all([
        this.api(`/api/traffic/config?scenario=${this.scenario}`),
        this.api('/api/network/routes'), this.api('/api/network/signals'), this.api('/api/constraints')
      ]);
      this.config = traffic;
      this.networkRoutes = routeData.routes || [];
      this.signalData = signalData;
      const density = this.config.active_density || this.config.density || {};
      for (const [key, id] of Object.entries({cars:'densityCars',buses:'densityBuses',two_wheelers:'densityTwoWheelers',pedestrians:'densityPedestrians',local_trains:'densityTrains'})) {
        const el = document.getElementById(id); if (el) { el.value = density[key] ?? ''; el.disabled = this.config.capabilities?.[key]?.supported === false; el.title = el.disabled ? 'No flow/personFlow of this mode exists in the selected scenario.' : ''; }
      }
      const corridors = routeData.corridors || [];
      ['routeSource','routeAlternative','vipCorridor','constructionCorridor'].forEach(id => this.populateSelect(id, corridors.map(c => [c.id, c.id])));
      this.populateSelect('signalTls', (signalData.classical || []).map(s => [s.tls_id, `${s.tls_id} · ${s.program_id} · ${s.phase_count} phases`]));
      const weather = document.getElementById('weatherSelect');
      if (weather) {
        weather.replaceChildren();
        Object.entries(constraintData.profiles?.weather || {}).forEach(([name, profile]) => {
          const option = document.createElement('option'); option.value = name; option.textContent = `${name} · ${profile.description || 'configured'}`; weather.appendChild(option);
        });
        weather.value = constraintData.constraints?.weather || 'clear';
      }
      if (signalData.classical?.length) {
        const tlsSelect = document.getElementById('signalTls');
        const discoveredIndex = [...tlsSelect.options].findIndex(option => option.value === signalData.classical[0].tls_id);
        if (discoveredIndex >= 0) { tlsSelect.options[0].selected = false; tlsSelect.options[discoveredIndex].selected = true; }
        this.loadSignalPhases();
      }
    } catch (error) { this.toast(`Configuration unavailable: ${error.message}`); }
  }

  populateSelect(id, values) {
    const select = document.getElementById(id); if (!select) return;
    const first = select.options[0]?.cloneNode(true); select.replaceChildren(); if (first) select.appendChild(first);
    values.forEach(([value, label]) => { const option = document.createElement('option'); option.value = value; option.textContent = label; select.appendChild(option); });
  }

  loadSignalPhases() {
    const tlsId = document.getElementById('signalTls')?.value;
    const signal = (this.signalData?.classical || []).find(item => item.tls_id === tlsId);
    const phaseSelect = document.getElementById('signalPhase');
    if (!signal || !phaseSelect) { this.populateSelect('signalPhase', []); return; }
    this.populateSelect('signalPhase', signal.phases.map(p => [String(p.phase), `Phase ${p.phase} · ${p.duration_s}s · ${p.signal_classes.join('/')}`]));
    phaseSelect.value = String(signal.current_phase);
    this.showSignalPhase();
  }

  showSignalPhase() {
    const tlsId = document.getElementById('signalTls')?.value;
    const phaseId = Number(document.getElementById('signalPhase')?.value);
    const signal = (this.signalData?.classical || []).find(item => item.tls_id === tlsId);
    const phase = signal?.phases.find(item => item.phase === phaseId);
    const duration = document.getElementById('signalDuration');
    const text = document.getElementById('signalReadback');
    if (duration) duration.value = phase?.duration_s ?? '';
    const fixed = phase && phase.min_duration_s === phase.max_duration_s;
    const apply = document.getElementById('btnApplySignal'); if (apply) apply.disabled = !phase || fixed;
    if (text) text.textContent = phase ? `Live state ${phase.state}; ${fixed ? `fixed duration ${phase.duration_s}s (SUMO min/max are equal)` : `allowed duration ${phase.min_duration_s || 1}–${phase.max_duration_s || 240}s`}. Signal classes: ${phase.signal_classes.join(', ')}.` : 'Select a live phase.';
  }

  connect() {
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${scheme}//${location.host}/ws/simulation`);
    this.socket = socket;
    socket.onopen = () => { this.setSocketStatus('CONNECTED'); };
    socket.onclose = () => { this.setSocketStatus('RECONNECTING'); setTimeout(() => this.connect(), 1500); };
    socket.onerror = () => this.setSocketStatus('DISCONNECTED');
    socket.onmessage = event => {
      let frame; try { frame = JSON.parse(event.data); } catch { return; }
      if (frame.type === 'geometry') { this.renderers.forEach(renderer => renderer.setGeometry(frame.data)); return; }
      const pair = frame.simulations || {};
      const incomingPairId = frame.pair?.pair_id;
      if (incomingPairId && this.currentPairId && incomingPairId !== this.currentPairId) this.clearOptimizationForNewPair();
      if (incomingPairId) { this.currentPairId = incomingPairId; if (this.config) this.config.current_pair_id = incomingPairId; }
      if (pair.classical) this.snapshots.classical = pair.classical;
      else if (frame.vehicles) this.snapshots.classical = frame;
      if (pair.quantum) this.snapshots.quantum = pair.quantum;
      if (frame.events) this.events = frame.events;
      if (frame.optimization_status) this.updateLifecycleStage(frame.optimization_status);
      this.updateOptimization(frame.quantum_optimization);
      const now = performance.now();
      if (now - this.lastPaint >= 180) { this.lastPaint = now; this.paint(frame); }
    };
  }

  paint(frame = {}) {
    const c = this.snapshots.classical || {}, q = this.snapshots.quantum || {};
    if (c.vehicles) this.renderers[0].update(c);
    if (q.vehicles) this.renderers[1].update(q);
    const k = c.kpis || {}, vehicles = c.vehicles || [], peds = c.pedestrians || [];
    const countType = type => vehicles.filter(v => v.type === type).length;
    const congestion = Object.values(c.edges_congestion || {});
    const congested = congestion.filter(x => ['yellow','orange','red'].includes(x.level)).length;
    this.setText('metricVehicles', vehicles.length); this.setText('metricPedestrians', peds.length);
    this.setText('metricCars', countType('car') + countType('taxi'));
    this.setText('metricBuses', countType('bus')); this.setText('metricTwoWheelers', countType('motorcycle'));
    this.setText('metricTrains', countType('train')); this.setText('metricSignals', Object.keys(c.traffic_lights || {}).length);
    this.setText('metricGenerated', c.generated_vehicles ?? 'N/A');
    this.setText('metricCompleted', k.completed_vehicles ?? 'N/A');
    this.setText('metricSpeed', this.format(k.avg_speed_kmh, ' km/h'));
    this.setText('metricQueue', this.format(k.total_queue_length_m, ' m'));
    this.setText('metricCongested', congested);
    this.updateActiveVehicleChoices(vehicles);
    this.setText('metricVisitors', peds.filter(p => p.dest_flow === 'stadium').length);
    const time = this.formatTime(c.time); this.setText('simTimeDisplay', time); this.setText('dockSimTime', time);
    this.setText('scenarioHeader', (c.scenario || 'waiting').replaceAll('_',' ').toUpperCase());
    this.setText('classicalConnection', c.connection_status || 'WAITING FOR SUMO');
    this.setText('quantumConnection', q.connection_status || 'WAITING FOR SUMO');
    this.setText('classicalSimId', c.simulation_id || '—'); this.setText('quantumSimId', q.simulation_id || '—');
    this.setText('pairIdLabel', frame.pair?.pair_id || 'PAIR —');
    this.setText('traciStatus', c.connection_status || '—');
    this.paintComparison(c, q, frame.pair?.synchronization);
    this.renderEvents(); this.renderExplainability(c, q);
  }

  paintComparison(c, q, synchronization) {
    const ck = c.kpis || {}, qk = q.kpis || {};
    const show = (id, value, suffix='') => this.setText(id, value == null ? 'N/A' : `${value}${suffix}`);
    show('cmpSpeedC', ck.avg_speed_kmh, ''); show('cmpSpeedQ', qk.avg_speed_kmh, '');
    show('cmpQueueC', ck.total_queue_length_m, ''); show('cmpQueueQ', qk.total_queue_length_m, '');
    show('cmpTripTimeC', ck.avg_completed_travel_time_s, ' s');
    show('cmpTripTimeQ', qk.avg_completed_travel_time_s, ' s');
    this.setText('comparisonPair', synchronization?.status || 'UNKNOWN');
    const now = performance.now();
    if (now - this.lastComparisonPoll > 5000) {
      this.lastComparisonPoll = now;
      this.api('/api/comparison').then(data => {
        this.comparison = data;
        const measured = data.measured;
        const changes = measured?.comparisons || {};
        show('cmpSpeedD', changes.avg_speed_kmh?.improvement_percent == null ? null : `${changes.avg_speed_kmh.improvement_percent}%`);
        show('cmpQueueD', changes.queue_length_m?.improvement_percent == null ? null : `${changes.queue_length_m.improvement_percent}%`);
        show('cmpTripTimeD', changes.avg_completed_travel_time_s?.improvement_percent == null ? null : `${changes.avg_completed_travel_time_s.improvement_percent}%`);
        show('cmpCongC', measured?.classical?.congested_edges);
        show('cmpCongQ', measured?.quantum?.congested_edges);
        show('cmpCongD', changes.congested_edges?.improvement_percent == null ? null : `${changes.congested_edges.improvement_percent}%`);
        show('cmpSaved', data.model_estimate?.travel_time_saved_minutes == null ? null : `${data.model_estimate.travel_time_saved_minutes} min`);
        show('cmpReduction', data.model_estimate?.queue_reduction_percent == null ? null : `${data.model_estimate.queue_reduction_percent}%`);
        this.setText('comparisonPair', data.synchronization?.status || 'UNKNOWN');
      }).catch(() => {});
    }
  }

  renderExplainability(c, q) {
    const target = document.getElementById('routeExplainability'); if (!target) return;
    const action = this.latestPlan;
    const corridors = action?.corridors?.filter(x => x.enabled) || [];
    if (!corridors.length) { target.innerHTML = '<span class="muted">No applied route actions yet. Queue and travel-time comparisons require route-level telemetry.</span>'; return; }
    target.innerHTML = corridors.map(x => `<article class="route-explain-card"><b>${this.escape(x.corridor)}</b><span>Quantum action: ${this.escape(String(x.rerouted ?? 'N/A'))} rerouted · remaining queue ${this.escape(String(x.remaining_queue ?? 'N/A'))}</span><span>Classical / Quantum queue and travel time: N/A (not exposed by current telemetry)</span></article>`).join('');
  }

  async refreshSystemStatus() {
    try {
      const s = await this.api('/api/system/status');
      this.status('sumoStatus', 'sumoStatusDot', s.sumo_classical);
      this.status('quantumStatus', 'quantumStatusDot', s.quantum_api?.status || 'OFFLINE');
      this.status('supabaseStatus', 'supabaseStatusDot', s.supabase);
      this.status('digitalTwinStatus', 'digitalTwinStatusDot', s.digital_twin || 'UNKNOWN');
      this.updatePairLifecycle(s.simulation_state || 'UNKNOWN');
    } catch { this.status('digitalTwinStatus', 'digitalTwinStatusDot', 'OFFLINE'); this.updatePairLifecycle('UNKNOWN'); }
    setTimeout(() => this.refreshSystemStatus(), 5000);
  }
  async loadLatestPlan() { try { const result = await this.api('/api/integration/latest_plan'); if(result.status !== 'none') this.updateOptimization(result); } catch { /* The live stream remains authoritative when the plan endpoint is unavailable. */ } }
  clearOptimizationForNewPair() { this.latestPlan = null; this.setText('qOptimizer','Waiting for result'); this.setText('qBitstring','N/A'); this.setText('qObjective','N/A'); this.setText('qRuntime','N/A'); this.setText('qStatus','IDLE'); this.setText('qRouteCount','—'); this.setText('qSignalCount','—'); this.setText('qRestrictionCount','—'); this.setText('qSaved','—'); this.setText('qReduction','—'); this.setText('qApplied','—'); this.setText('qRunId','—'); this.setText('quantumMapBadge','WAITING FOR OPTIMIZATION'); this.renderers[1].setOverlays(); }

  status(id, dotId, value) { this.setText(id, value || 'UNKNOWN'); const dot = dotId && document.getElementById(dotId); if (dot) { const normalized=String(value).toUpperCase(); dot.className=`status-dot ${['CONNECTED','RUNNING','ONLINE','APPLIED'].includes(normalized)?'good':['CHECKING','CONNECTING','STARTING','PAUSED','SYNCING','DEGRADED'].includes(normalized)?'warn':'bad'}`; } }
  setSocketStatus(value) { this.setText('wsStatusPill', value); this.setText('telemetryStatus', value); const pill=document.getElementById('wsStatusPill'); if(pill)pill.className=`live-pill ${['CONNECTED'].includes(value)?'good':['CONNECTING','RECONNECTING'].includes(value)?'checking':'bad'}`; const pip=document.querySelector('.live-pip'); if(pip)pip.className=`live-pip ${value==='CONNECTED'?'good':['CONNECTING','RECONNECTING'].includes(value)?'checking':'bad'}`; }
  updatePairLifecycle(state) { this.lifecycle=state; const stopped=state==='STOPPED'; const paused=state==='PAUSED'; const running=state==='RUNNING'; const start=document.getElementById('btnStart'), pause=document.getElementById('btnPlayPause'), reset=document.getElementById('btnReset'); if(start){start.textContent=paused?'RESUME':stopped?'START':running?'RUNNING':state;start.disabled=running||!['PAUSED','STOPPED','ERROR','DEGRADED'].includes(state);} if(pause){pause.textContent=paused?'RESUME':'PAUSE';pause.disabled=stopped||!['RUNNING','PAUSED'].includes(state);} if(reset)reset.disabled=!['RUNNING','PAUSED','STOPPED'].includes(state); }
  updateLifecycleStage(event) { const stage=String(event.stage||'UNKNOWN').toUpperCase(); this.setText('qStatus',stage); const target={QUEUED:'requested',RUNNING:'running',RESULT_RECEIVED:'running',VALIDATING:'validated',MAPPING:'validated',APPLYING:'applied',APPLIED:'applied',COMPLETED:'completed',FAILED:'requested',REJECTED:'requested',SKIPPED:'completed',FALLBACK:'running'}[stage]; if(!target)return; const stages=['requested','running','validated','applied','completed']; document.querySelectorAll('.pipeline [data-stage]').forEach(el=>{el.classList.toggle('done',stages.indexOf(el.dataset.stage)<stages.indexOf(target));el.classList.toggle('active',el.dataset.stage===target);}); }
  setText(id, value) { const node = document.getElementById(id); if (node) node.textContent = value == null ? 'N/A' : String(value); }
  format(value, suffix='') { return value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}${suffix}` : 'N/A'; }
  formatTime(value) { if (!Number.isFinite(Number(value))) return '--:--.-'; const t=Number(value); return `${String(Math.floor(t/60)).padStart(2,'0')}:${String(Math.floor(t%60)).padStart(2,'0')}.${Math.floor((t%1)*10)}`; }
  delta(a,b) { return Number.isFinite(Number(a)) && Number.isFinite(Number(b)) ? `${(Number(b)-Number(a)>0?'+':'')}${(Number(b)-Number(a)).toFixed(1)}` : 'N/A'; }
  escape(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  toast(text) { const el=document.getElementById('toast'); if (!el) return; el.textContent=text; el.classList.add('visible'); setTimeout(()=>el.classList.remove('visible'),3500); }

  density() { const read=id => { const raw=document.getElementById(id)?.value; const n=Number(raw); if (raw === '' || !Number.isInteger(n)||n<0) throw new Error(`Enter a valid non-negative whole number for ${id.replace('density','')}`); return n; }; return {cars:read('densityCars'),buses:read('densityBuses'),two_wheelers:read('densityTwoWheelers'),pedestrians:read('densityPedestrians'),local_trains:read('densityTrains')}; }
  routeSettings() { const settings={source:document.getElementById('routeSource').value, alternative:document.getElementById('routeAlternative').value || null, diversion_percent:Number(document.getElementById('diversionPercent').value), blocked:document.getElementById('blockEntry').checked}; if(settings.blocked&&!settings.source)throw new Error('Select a corridor before blocking new entry'); return settings; }
  highlightSelectedCorridor() { const selectedNames=[document.getElementById('routeSource')?.value,document.getElementById('routeAlternative')?.value].filter(Boolean); const vipName=document.getElementById('vipEnabled')?.checked?document.getElementById('vipCorridor')?.value:null; const constructionName=document.getElementById('constructionEnabled')?.checked?document.getElementById('constructionCorridor')?.value:null; const edgesFor=names=>[...new Set(names.filter(Boolean).flatMap(n=>this.config?.corridors?.[n]?.edges||[]))]; const selectedEdges=edgesFor(selectedNames),vipEdges=edgesFor([vipName]),constructionEdges=edgesFor([constructionName]); const actionEdges=edgesFor((this.latestPlan?.corridors||[]).filter(x=>x.enabled).map(x=>x.corridor)); this.renderers.forEach(r=>r.setOverlays({selectedEdges,actionEdges,vipEdges,constructionEdges})); }

  async applyBoth() {
    try {
      this.scenario = document.querySelector('.scenario-choice.selected')?.dataset.scenario || this.scenario;
      const routes=this.routeSettings();
      const applied = await this.api('/api/traffic/configure',{method:'POST',body:JSON.stringify({scenario:this.scenario,density:this.density(),constraints:{weather:document.getElementById('weatherSelect').value,vip_enabled:document.getElementById('vipEnabled').checked,vip_corridor:document.getElementById('vipCorridor').value||null,construction_enabled:document.getElementById('constructionEnabled').checked,construction_corridor:document.getElementById('constructionCorridor').value||null},route_modifications:routes.source?routes:{}})});
      this.config.current_pair_id = applied.pair_id;
      if (!applied.success) {
        throw new Error(JSON.stringify(applied.reason || applied.readback || 'SUMO did not confirm every requested input.'));
      }
      await this.loadConfig();
      this.toast('Traffic configuration and constraints read back from both SUMO simulations.'); this.highlightSelectedCorridor();
    } catch (e) { this.toast(`Scenario rejected: ${e.message}`); }
  }
  async applySignal() {
    const tls_id = document.getElementById('signalTls')?.value;
    const phase = Number(document.getElementById('signalPhase')?.value);
    const duration_s = Number(document.getElementById('signalDuration')?.value);
    try {
      const result = await this.api('/api/signals/configure', {method:'POST', body:JSON.stringify({tls_id, phase, duration_s})});
      if (!result.success) throw new Error(result.reason || 'TraCI did not verify the signal timing.');
      this.toast(`Signal ${tls_id} phase ${phase}: ${result.readback.classical.actual_duration_s}s verified in both runs.`);
      this.signalData = await this.api('/api/network/signals'); this.loadSignalPhases();
    } catch (e) { this.toast(`Signal timing rejected: ${typeof e.message === 'string' ? e.message : JSON.stringify(e.message)}`); }
  }
  async applyRoute() { try { const r=this.routeSettings(); if (!r.source) throw new Error('Select a source corridor'); const result=await this.api('/api/simulation/routes',{method:'POST',body:JSON.stringify(r)}); if(!result.success)throw new Error('SUMO readback was incomplete; route control is partial.'); this.highlightSelectedCorridor(); this.toast('Route permissions and control were read back from both SUMO runs.'); } catch(e) { this.toast(`Route control failed: ${e.message}`); } }
  updateActiveVehicleChoices(vehicles = []) { const select=document.getElementById('activeVehicle'),button=document.getElementById('btnRerouteVehicle'); if(!select||!button)return; const ids=[...new Set(vehicles.map(v=>v.id).filter(Boolean))].sort(); const existing=[...select.options].slice(1).map(option=>option.value); if(ids.length!==existing.length||ids.some((id,index)=>id!==existing[index])){const selected=select.value;select.replaceChildren(new Option(ids.length?'Select live vehicle…':'No active vehicles', ''),...ids.map(id=>new Option(id,id)));if(ids.includes(selected))select.value=selected;} button.disabled=!ids.includes(select.value); }
  async rerouteActiveVehicle() { const select=document.getElementById('activeVehicle'),button=document.getElementById('btnRerouteVehicle'),vehicleId=select?.value; if(!vehicleId)return; if(button)button.disabled=true; try { const result=await this.api(`/api/simulation/vehicles/${encodeURIComponent(vehicleId)}/reroute`,{method:'POST',body:JSON.stringify({})}); if(!result.success)throw new Error(result.reason||result.reason_code||'No valid alternative route was found.'); const both=Object.values(result.contexts||{}); if(both.length!==2||both.some(context=>!context.success||!context.vehicle_active||!context.sumo_running||JSON.stringify(context.before_route)===JSON.stringify(context.after_route)))throw new Error('Paired live route readback did not verify the operation.'); this.toast(`Alternative route applied to ${vehicleId}; both SUMO routes verified.`); } catch(error) { this.toast(`Reroute rejected: ${error.message}`); } finally { if(button)button.disabled=!(select&&select.value); } }
  async startBoth() { try { const state=await this.api(`/api/control/start?scenario=${encodeURIComponent(this.scenario)}`,{method:'POST'}); this.updatePairLifecycle(state.lifecycle_state); this.toast(state.action==='resumed'?'Simulation resumed.':state.action==='already_running'?'Simulation is already running.':'Simulation pair started.'); } catch(e) { this.toast(e.message); } }
  async togglePause() { try { const action=this.lifecycle==='PAUSED'?'resume':'pause'; const state=await this.api(`/api/control/${action}`,{method:'POST'}); this.updatePairLifecycle(state.lifecycle_state); } catch(e) { this.toast(e.message); } }
  async restartBoth() { try { await this.api('/api/control/reset',{method:'POST'}); this.toast('Both simulations restarted with the active scenario.'); } catch(e) { this.toast(e.message); } }
  async selectScenario(scenario) { document.querySelectorAll('.scenario-choice').forEach(b=>b.classList.toggle('selected',b.dataset.scenario===scenario)); this.scenario=scenario; try { const config=await this.api(`/api/traffic/config?scenario=${scenario}`); this.config={...this.config,...config}; const density=config.density||{}; for(const [key,id] of Object.entries({cars:'densityCars',buses:'densityBuses',two_wheelers:'densityTwoWheelers',pedestrians:'densityPedestrians',local_trains:'densityTrains'})) { const field=document.getElementById(id); field.value=density[key]??0; field.disabled=config.capabilities?.[key]?.supported===false; } } catch(e) { this.toast(e.message); } }
  async setSpeed(speed) { try { await this.api(`/api/control/speed?multiplier=${speed}`,{method:'POST'}); return true; } catch(e) { this.toast(e.message); return false; } }
  setLayer(layer, enabled) { this.renderers.forEach(renderer => { if (layer === 'buildings') { renderer.setLayer('buildings',enabled); renderer.setLayer('shops',enabled); } else renderer.setLayer(layer,enabled); }); if(layer==='vipRoute'||layer==='construction'||layer==='routes'||layer==='actions')this.highlightSelectedCorridor(); }
  clearSelection() { this.renderers.forEach(r=>{r.selectedEntity=null;r.setOverlaySelection([],[])}); this.setText('inspectorContent','Select a road segment, junction, or vehicle on either map.'); }
  inspect(item, side) { const state=this.snapshots[side]||{}, id=item.edgeId||item.junctionId||item.entityId; let rows={Selection:id,Type:item.type||'Road'}; if(item.edgeId){const x=state.edges_congestion?.[id]; const vehicles=(state.vehicles||[]).filter(v=>v.road_id===id); const corridors=Object.entries(this.config?.corridors||{}).filter(([,value])=>value.edges?.includes(id)).map(([name])=>name); const action=(this.latestPlan?.corridors||[]).find(a=>corridors.includes(a.corridor)&&a.enabled); rows={...rows,'Corridor':corridors.join(', ')||'N/A','Traffic level':x?.level||'N/A','Vehicle count':vehicles.length,'Queue':x?.queue_len==null?'N/A':`${x.queue_len} m`,'Average speed':vehicles.length?`${(vehicles.reduce((sum,v)=>sum+(Number(v.speed_kmh)||0),0)/vehicles.length).toFixed(1)} km/h`:'N/A','Status':x?.level||'N/A','Current action':action?`Quantum reroute · ${action.rerouted} vehicles`:'No applied action'};} else if(item.junctionId||item.type==='TrafficSignal'){const signal=Object.values(state.traffic_lights||{}).find(x=>x.id===id); const action=(this.latestPlan?.signal_changes||[]).find(a=>a.junction===id||this.config?.junctions?.[a.junction]?.sumo_id===id); rows={...rows,'Signal phase':signal?.phase??'N/A','Signal state':signal?.state||'N/A','Phase duration':signal?.phase_duration_s==null?'N/A':`${signal.phase_duration_s} s`,'Next switch':signal?.seconds_to_switch==null?'N/A':`${signal.seconds_to_switch} s`,'Traffic count':'N/A','Queue':'N/A','Optimization status':action?`Green ${action.old_green}s → ${action.new_green}s`:'No action returned'};} else rows={...rows,'Simulation':side,'Speed':item.speed||'N/A','Road':item.edge||'N/A'}; document.getElementById('inspectorContent').innerHTML=Object.entries(rows).map(([k,v])=>`<div class="inspector-row"><span>${this.escape(k)}</span><b>${this.escape(v)}</b></div>`).join(''); }

  async optimize() { const button=document.getElementById('btnTriggerQuantum'); button.disabled=true; const message_id=crypto.randomUUID(); try { const result=await this.api('/api/integration/trigger_optimization',{method:'POST',body:JSON.stringify({message_id,scenario_id:this.scenario})}); this.updateOptimization(result); this.toast(`${result.optimizer_used || 'Optimizer'} result ${result.status}`); } catch(e) { this.toast(`Optimization failed: ${e.message}`); } finally { button.disabled=false; } }
  updateOptimization(plan) { if(!plan)return; this.latestPlan={...(this.latestPlan||{}),...plan}; plan=this.latestPlan; const status=String(plan.status||'completed').toUpperCase(); const applied=Boolean(plan.applied_to_sumo ?? plan.applied); this.setText('qOptimizer',plan.optimizer_used||'N/A'); this.setText('qBitstring',plan.bitstring||'N/A'); this.setText('qObjective',plan.objective_value??'N/A'); this.setText('qRuntime',plan.runtime_seconds==null?'N/A':`${Number(plan.runtime_seconds).toFixed(2)} s`); this.setText('qStatus',applied?`${status} · APPLIED`:status); this.setText('qRouteCount',(plan.corridors||[]).filter(x=>x.enabled).length); this.setText('qSignalCount',(plan.signal_changes||[]).length); this.setText('qRestrictionCount',(plan.restrictions||[]).length); this.setText('qSaved',plan.benefits?.travel_time_saved_minutes==null?'N/A':`${plan.benefits.travel_time_saved_minutes} min`); this.setText('qReduction',plan.benefits?.queue_reduction_percent==null?'N/A':`${plan.benefits.queue_reduction_percent}%`); this.setText('qApplied',applied?'APPLIED':'NOT APPLIED'); this.setText('qRunId',plan.run_id||plan.optimization_run_id||plan.message_id||'—'); const badge=plan.optimizer_used?.includes('Fallback')?'CLASSICAL FALLBACK':plan.optimizer_used==='Quantum'?'QUANTUM RESULT':plan.optimizer_used||'OPTIMIZATION RESULT'; this.setText('quantumMapBadge',plan.status==='failed'?'VALIDATION FAILED':applied?`${badge} · APPLIED`:badge); const active=status.includes('FAIL')? 'requested':applied?'completed':status.includes('RUN')?'running':'validated'; document.querySelectorAll('.pipeline [data-stage]').forEach(el=>{const stages=['requested','running','validated','applied','completed'];el.classList.toggle('done',stages.indexOf(el.dataset.stage)<stages.indexOf(active));el.classList.toggle('active',el.dataset.stage===active);}); this.highlightSelectedCorridor(); }
  renderEvents(filter='all') { const target=document.getElementById('eventLog'); if(!target)return; const events=(this.events||[]).filter(e=>filter==='all'||e.category===filter); target.innerHTML=events.length?events.slice(-80).reverse().map(e=>`<div class="event-row"><time>${this.escape(new Date(e.timestamp).toLocaleTimeString())}</time><b>${this.escape(e.category||'system')}</b><span>${this.escape(e.message||'')}</span></div>`).join(''):'<span class="muted">Waiting for server events.</span>'; const timeline=document.getElementById('timelineView'); if(timeline)timeline.innerHTML=events.slice(-12).map(e=>`<div class="timeline-event"><time>${this.escape(this.formatTime(e.sim_time))}</time><span>${this.escape(e.message)}</span></div>`).join('')||'<span class="muted">Timeline events appear as the simulations run.</span>'; }
}

window.addEventListener('DOMContentLoaded', () => { window.digitalTwinApp = new DigitalTwinApp(); });
