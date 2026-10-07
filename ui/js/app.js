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
    this.explainability = null;
    this.explainabilityRequestedFor = null;
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
    this.loadExplainability();
    this.refreshSystemStatus();
    document.getElementById('btnApplyBoth')?.addEventListener('click', () => this.applyBoth());
    document.getElementById('btnApplyRoute')?.addEventListener('click', () => this.applyRoute());
    document.getElementById('btnClearRoute')?.addEventListener('click', () => this.clearRoute());
    document.getElementById('btnApplyWeather')?.addEventListener('click', () => this.applyWeather());
    document.getElementById('btnResetWeather')?.addEventListener('click', () => this.resetWeather());
    document.getElementById('btnApplySignal')?.addEventListener('click', () => this.applySignal());
    document.getElementById('signalTls')?.addEventListener('change', () => this.loadSignalStates());
    document.getElementById('signalState')?.addEventListener('change', () => this.showSignalState());
    document.getElementById('btnApplyConstruction')?.addEventListener('click', () => this.applyConstruction());
    document.getElementById('btnClearConstruction')?.addEventListener('click', () => this.clearConstruction());
    document.getElementById('routeSource')?.addEventListener('change', () => this.populateRouteAlternatives());
    document.getElementById('routeExplainability')?.addEventListener('click', event => this.useExplainabilityRecommendation(event));
    document.getElementById('diversionPercent')?.addEventListener('input', event => this.setText('diversionValue', `${event.target.value}%`));
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
      const [traffic, routeData, signalData, constraintData, capabilities, operatorState] = await Promise.all([
        this.api(`/api/traffic/config?scenario=${this.scenario}`),
        this.api('/api/network/routes'), this.api('/api/network/signals'), this.api('/api/constraints'),
        this.api('/api/operator/capabilities'), this.api('/api/operator/state')
      ]);
      this.operatorCapabilities=capabilities; this.operatorState=operatorState;
      this.config = traffic;
      const variables=capabilities.decision_variables||[];
      this.setText('decisionVariableCount',variables.length||'N/A');
      const variableGroups={}; variables.forEach(item=>variableGroups[item.category]=(variableGroups[item.category]||0)+1);
      this.setText('decisionVariableBreakdown',Object.entries(variableGroups).map(([name,count])=>`${count} ${name.replaceAll('_',' ')}`).join(' · ')||'Definitions unavailable');
      this.networkRoutes = routeData.routes || [];
      this.corridors = routeData.corridors || [];
      this.renderers.forEach(renderer => renderer.setCorridors(this.corridors));
      this.signalData = signalData;
      const density = this.config.active_density || this.config.density || {};
      for (const [key, id] of Object.entries({cars:'densityCars',buses:'densityBuses',two_wheelers:'densityTwoWheelers',pedestrians:'densityPedestrians',local_trains:'densityTrains'})) {
        const el = document.getElementById(id); if (el) { el.value = density[key] ?? ''; el.disabled = this.config.capabilities?.[key]?.supported === false; el.title = el.disabled ? 'No flow/personFlow of this mode exists in the selected scenario.' : ''; }
      }
      const corridors = routeData.corridors || [];
      this.populateSelect('routeSource', corridors.map(c => [c.id, `${c.display_name || c.id} · ${c.traffic_state || 'UNKNOWN'}`]));
      ['vipCorridor','constructionCorridor'].forEach(id => this.populateSelect(id, corridors.map(c => [c.id, c.display_name || c.id])));
      this.corridors = corridors;
      this.populateRouteAlternatives();
      const routeConfig = capabilities.route_operations || {};
      const slider = document.getElementById('diversionPercent');
      if (slider) { slider.min=routeConfig.diversion_min; slider.max=routeConfig.diversion_max; slider.step=routeConfig.diversion_step; slider.value=routeConfig.default_diversion_share ?? routeConfig.diversion_min; slider.disabled=!corridors.length; }
      this.setText('diversionValue', `${slider?.value ?? 0}%`);
      this.setText('routeShareHint', `Eligible live vehicles only · ${slider?.min ?? 'N/A'}–${slider?.max ?? 'N/A'}% · step ${slider?.step ?? 'N/A'}%`);
      const signals = Object.entries(capabilities.signal_controls||{});
      this.populateSelect('signalTls', signals.map(([tlsId,s]) => [tlsId, s.display_name || tlsId]));
      const weather = document.getElementById('weatherSelect');
      if (weather) {
        weather.replaceChildren();
        Object.entries(constraintData.profiles?.weather || {}).forEach(([name, profile]) => {
          const option = document.createElement('option'); option.value = name; option.textContent = `${name} · ${profile.description || 'configured'}`; weather.appendChild(option);
        });
        const weatherReads=[operatorState.operator_readback?.classical?.weather,operatorState.operator_readback?.quantum?.weather];
        const verifiedWeather=weatherReads.length===2&&weatherReads.every(value=>value?.verified===true)&&weatherReads[0]?.input===weatherReads[1]?.input?weatherReads[0]?.input:'';
        weather.value=verifiedWeather;
        const profile=constraintData.profiles?.weather?.[verifiedWeather];
        this.setText('weatherStatus',verifiedWeather?`Active: ${verifiedWeather} · speed factor ${profile?.speed_factor ?? 'N/A'} · readback verified`:'Weather state unavailable or not verified in both simulations');
      }
      this.populateDurations('routeDuration',capabilities.route_operation_timing?.duration_options,capabilities.route_operation_timing?.default_duration_seconds);
      this.populateDurations('constructionDuration',capabilities.construction_profiles?.duration_options,capabilities.construction_profile?.default_duration_seconds);
      this.populateDurations('vipDuration',capabilities.vip_corridor_preference?.duration_options,capabilities.vip_corridor_preference?.default_duration_seconds);
      this.populateSelect('constructionMode',(capabilities.construction_profiles?.supported_modes||[]).map(mode=>[mode,mode==='profile'?'Speed / cost restriction':mode==='closure'?'Closure':mode]));
      const constructionProfile=capabilities.construction_profiles?.speed_cost_profile||{};
      this.setText('constructionProfileInfo',`Configured profile: speed cap ${constructionProfile.speed_cap_mps??'N/A'} m/s · travel-time factor ${constructionProfile.travel_time_factor??'N/A'} · ${capabilities.construction_closure?.message||''}`);
      const constructionReads=[operatorState.operator_readback?.classical?.construction,operatorState.operator_readback?.quantum?.construction];
      const constructionVerified=constructionReads.length===2&&constructionReads.every(value=>value?.verified===true)&&Boolean(constructionReads[0]?.enabled)===Boolean(constructionReads[1]?.enabled)&&constructionReads[0]?.corridor===constructionReads[1]?.corridor;
      const constructionEnabled=document.getElementById('constructionEnabled');if(constructionEnabled&&constructionVerified)constructionEnabled.checked=Boolean(constructionReads[0]?.enabled);
      const constructionCorridor=document.getElementById('constructionCorridor');if(constructionCorridor&&constructionVerified&&constructionReads[0]?.corridor)constructionCorridor.value=constructionReads[0].corridor;
      if(!constructionVerified)this.setText('constructionTimerStatus','Construction state unavailable or not verified in both simulations.');
      if (signals.length) {
        const tlsSelect = document.getElementById('signalTls');
        const discoveredIndex = [...tlsSelect.options].findIndex(option => option.value === signals[0][0]);
        if (discoveredIndex >= 0) { tlsSelect.options[0].selected = false; tlsSelect.options[discoveredIndex].selected = true; }
        this.loadSignalStates();
      }
      this.updateOperatorTimers(operatorState.timers||constraintData.timers||{});
    } catch (error) { this.toast(`Configuration unavailable: ${error.message}`); }
  }

  populateSelect(id, values) {
    const select = document.getElementById(id); if (!select) return;
    const first = select.options[0]?.cloneNode(true); select.replaceChildren(); if (first) select.appendChild(first);
    values.forEach(([value, label]) => { const option = document.createElement('option'); option.value = value; option.textContent = label; select.appendChild(option); });
  }

  populateDurations(id, values, selected) { const options=(Array.isArray(values)?values:[]).filter(value=>Number.isFinite(Number(value))&&Number(value)>0); this.populateSelect(id,options.map(value=>[String(value),`${value} sec`]));const select=document.getElementById(id);if(select){select.disabled=!options.length;if(options.some(value=>Number(value)===Number(selected)))select.value=String(selected);} }

  populateRouteAlternatives() {
    const source = document.getElementById('routeSource')?.value;
    const selected = document.getElementById('routeAlternative')?.value;
    const corridor = (this.corridors || []).find(item => item.id === source);
    const alternatives = (corridor?.alternatives || []).map(name => {
      const item=(this.corridors||[]).find(candidate=>candidate.id===name);
      return [name,`${item?.display_name||name} · ${item?.traffic_state||'UNKNOWN'}`];
    });
    this.populateSelect('routeAlternative', alternatives);
    const select=document.getElementById('routeAlternative');
    if(select&&alternatives.some(([value])=>value===selected))select.value=selected;
    if(select)select.disabled=!source||!alternatives.length;
  }

  loadSignalStates() {
    const tlsId=document.getElementById('signalTls')?.value, ctl=this.operatorCapabilities?.signal_controls?.[tlsId];
    const select=document.getElementById('signalState'), prior=select?.value;
    const options=(ctl?.states||[]).map(entry=>[entry.state,entry.state]);
    this.populateSelect('signalState',options);
    if(select&&options.some(([value])=>value===prior))select.value=prior;
    else if(select&&options.length)select.value=options[0][0];
    if(select)select.disabled=!options.length;
    this.showSignalState();
  }

  showSignalState() {
    const tlsId=document.getElementById('signalTls')?.value, ctl=this.operatorCapabilities?.signal_controls?.[tlsId];
    const state=document.getElementById('signalState')?.value, option=ctl?.states?.find(item=>item.state===state);
    const duration=document.getElementById('signalDuration');
    if(duration&&option){duration.value=option.duration_s;duration.min=option.min_duration_s;duration.max=option.max_duration_s;duration.disabled=Number(option.min_duration_s)===Number(option.max_duration_s);duration.placeholder=duration.disabled?`Fixed ${option.duration_s} sec`:'';}
    const apply=document.getElementById('btnApplySignal');if(apply)apply.disabled=!option;
    const raw=String(ctl?.signal_state||'');const current=raw&&/[yY]/.test(raw)?'TRANSITION':raw&&/[gG]/.test(raw)?'GREEN':raw?'RED':'UNKNOWN';
    this.setText('signalLiveState',ctl?`Current: ${current} · ${ctl.duration_s}s · next change in ${ctl.remaining_seconds==null?'N/A':`${Number(ctl.remaining_seconds).toFixed(1)}s`}`:'Signal state control unavailable for this junction.');
    this.setText('signalReadback',option?'Status: READY':'Signal state control is unsupported by the active program.');
  }

  refreshSignalReadbackFromTelemetry() { const tlsId=document.getElementById('signalTls')?.value;if(!tlsId||!this.operatorCapabilities?.signal_controls?.[tlsId])return;const lights=Object.values(this.snapshots.classical?.traffic_lights||{});const live=lights.find(item=>item.id===tlsId||item.tls_id===tlsId);if(!live)return;const control=this.operatorCapabilities.signal_controls[tlsId];control.signal_state=live.signal_state||live.state||control.signal_state;control.duration_s=live.phase_duration_s??live.duration_s??control.duration_s;control.remaining_seconds=live.seconds_to_switch??live.remaining_seconds??control.remaining_seconds;this.showSignalState(); }

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
      this.refreshSignalReadbackFromTelemetry();
      if (frame.events) this.events = frame.events;
      if (frame.operator_timers) this.updateOperatorTimers(frame.operator_timers);
      if (frame.route_explainability) { this.explainability=frame.route_explainability; this.renderExplainability(); }
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
    this.setText('metricPendingVehicles', c.demand?.pending_vehicle_count ?? '—');
    this.setText('metricDemandState', c.demand?.vehicle_demand_status?.replaceAll('_', ' ') ?? '—');
    this.setText('metricSpeed', this.format(k.avg_speed_kmh, ' km/h'));
    this.setText('metricQueue', this.format(k.total_queue_length_m, ' m'));
    this.setText('metricCongested', congested);
    this.setText('metricVisitors', peds.filter(p => p.dest_flow === 'stadium').length);
    const time = this.formatTime(c.time); this.setText('simTimeDisplay', time); this.setText('dockSimTime', time);
    this.setText('scenarioHeader', (c.scenario || 'waiting').replaceAll('_',' ').toUpperCase());
    this.setText('classicalConnection', c.connection_status || 'WAITING FOR SUMO');
    this.setText('quantumConnection', q.connection_status || 'WAITING FOR SUMO');
    this.setText('classicalSimId', c.simulation_id || '—'); this.setText('quantumSimId', q.simulation_id || '—');
    this.setText('pairIdLabel', frame.pair?.pair_id || 'PAIR —');
    this.setText('traciStatus', c.connection_status || '—');
    this.paintComparison(c, q, frame.pair?.synchronization);
    this.renderEvents();
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

  async loadExplainability() { try { this.explainability = await this.api('/api/operator/route-explainability'); this.renderExplainability(); } catch (error) { this.renderExplainability({status:'ERROR',message:error.message,corridors:[]}); } }
  renderExplainability(data=this.explainability) {
    const target=document.getElementById('routeExplainability'); if(!target)return;
    if(!data||data.status!=='READY'){target.innerHTML=`<div class="muted">${this.escape(data?.message||'Waiting for an optimizer result.')}</div>`;return;}
    const routeCards=(data.corridors||[]).map(item=>{const c=item.classical||{},q=item.quantum||{},check=item.constraints||{};const applyable=item.status==='APPLICABLE'&&item.decision==='DIVERSION_SELECTED';return `<article class="route-explain-card"><b>${this.escape(item.corridor)} <small>${this.escape(item.status)}</small></b><span>${this.escape(item.recommendation)}</span><span>Classical live: queue ${this.escape(c.available?`${c.queue_length_m} m`:'N/A')}, speed ${this.escape(c.average_speed_kmh==null?'N/A':`${c.average_speed_kmh} km/h`)}, congestion ${this.escape((c.congestion_levels||[]).join(', ')||'N/A')}</span><span>Quantum live: queue ${this.escape(q.available?`${q.queue_length_m} m`:'N/A')}, speed ${this.escape(q.average_speed_kmh==null?'N/A':`${q.average_speed_kmh} km/h`)}, congestion ${this.escape((q.congestion_levels||[]).join(', ')||'N/A')}</span><span>Constraint check: ${check.valid===true?'clear':check.valid===false?'blocked / review required':'unavailable'} · Source: ${this.escape(item.source||data.source||'N/A')}</span>${applyable?`<button class="text-button" data-use-route="${this.escape(item.corridor)}">Review in Route Operations</button>`:''}</article>`;}).join('');
    const signals=(data.signals||[]).map(item=>{const c=item.classical_live||{},q=item.quantum_live||{};const recommended=Number(item.new_green);return `<article class="route-explain-card"><b>${this.escape(item.junction)} signal · ${this.escape(item.status)}</b><span>${this.escape(item.description||item.sumo_tls||'Mapped junction')}</span><span>Live Classical: ${this.escape(c.color||'N/A')} · Quantum: ${this.escape(q.color||'N/A')} · Constraint check: ${item.constraints?.valid===true?'clear':item.constraints?.valid===false?'blocked':'unavailable'}</span><span>Optimizer recommendation: ${this.escape(String(item.old_green))}s → ${this.escape(String(item.new_green))}s. Recommendation only; operator decision required.</span>${item.sumo_tls&&Number.isFinite(recommended)?`<button class="text-button" data-use-signal="${this.escape(item.sumo_tls)}" data-signal-duration="${this.escape(String(recommended))}">Review in Signal Timing</button>`:''}</article>`;}).join('');
    const restrictions=(data.restrictions||[]).map(item=>`<article class="route-explain-card"><b>${this.escape(item.corridor)} · ${this.escape(item.type)} · ${this.escape(item.status)}</b><span>Optimizer returned this restriction proposal. Constraint check: ${item.constraints?.valid===true?'clear':item.constraints?.valid===false?'blocked':'unavailable'}. Review before taking any separate action.</span></article>`).join('');
    const decoded=(data.decoded_variables||[]).map(item=>`${this.escape(item.id)} ${this.escape(item.category)} · ${this.escape(item.target)}=${item.selected?'1':'0'} · ${this.escape(item.description)}`).join(' · ');
    target.innerHTML=`<div class="muted">${this.escape(data.message)} · ${this.escape(data.source)} · ${this.escape(data.run_id||'run id unavailable')}${data.applied_to_sumo?' · optimizer application separately verified':''}</div><details><summary>${this.escape(data.decoder_note||'Decision variable details')}</summary><span>${decoded||'No variables decoded.'}</span></details>${routeCards||'<div class="muted">No corridor decisions returned.</div>'}${signals}${restrictions}`;
  }
  useExplainabilityRecommendation(event) {
    const routeSource=event.target.closest('[data-use-route]')?.dataset.useRoute;
    const signalTls=event.target.closest('[data-use-signal]')?.dataset.useSignal;
    if(routeSource){
      const source=document.getElementById('routeSource'); source.value=routeSource; this.populateRouteAlternatives();
      const alternative=document.getElementById('routeAlternative'); if(alternative.options.length>1)alternative.selectedIndex=1;
      document.getElementById('routeOperationStatus').textContent='Status: READY · recommendation loaded for review';
      document.getElementById('routeSource').scrollIntoView({behavior:'smooth',block:'center'});
    }
    if(signalTls){
      const select=document.getElementById('signalTls'); select.value=signalTls; this.loadSignalStates();
      const stateSelect=document.getElementById('signalState');
      if(stateSelect&&[...stateSelect.options].some(option=>option.value==='GREEN'))stateSelect.value='GREEN';
      this.showSignalState();
      const duration=event.target.closest('[data-signal-duration]')?.dataset.signalDuration;
      if(duration)document.getElementById('signalDuration').value=duration;
      document.getElementById('signalReadback').textContent='Status: READY · optimizer recommendation loaded for review; not applied';
      select.scrollIntoView({behavior:'smooth',block:'center'});
    }
  }
  updateOperatorTimers(timers={},merge=false) { this.operatorTimers=merge?{...(this.operatorTimers||{}),...timers}:timers;timers=this.operatorTimers;const vip=timers.vip, construction=timers.construction_closure||timers.construction_profile,route=timers.route_operation;const vipNode=document.getElementById('vipTimerStatus'),constructionNode=document.getElementById('constructionTimerStatus'),routeNode=document.getElementById('routeTimerStatus');if(vipNode)vipNode.textContent=vip?(vip.status==='RESTORATION_ERROR'?`VIP restoration error: ${vip.error}`:`VIP ${vip.status} · ${vip.remaining_seconds??0}s remaining`):'VIP timer inactive.';if(constructionNode)constructionNode.textContent=construction?construction.status==='RESTORATION_ERROR'?`RESTORE ERROR · ${construction.error}`:`${construction.status} · ${construction.remaining_seconds??0}s`:'Construction inactive.';if(routeNode)routeNode.textContent=route?route.status==='RESTORATION_ERROR'?`RESTORE ERROR · ${route.error}`:`${route.status}${route.status==='ACTIVE'?` · ${route.remaining_seconds}s remaining`:''}`:'Route control inactive.'; }

  async refreshSystemStatus() {
    try {
      const s = await this.api('/api/system/status');
      this.status('sumoStatus', 'sumoStatusDot', s.sumo_classical);
      this.status('quantumStatus', 'quantumStatusDot', s.quantum_api?.status || 'OFFLINE');
      this.status('digitalTwinStatus', 'digitalTwinStatusDot', s.digital_twin || 'UNKNOWN');
      this.updatePairLifecycle(s.simulation_state || 'UNKNOWN');
      if(!this.latestPlan) this.loadExplainability();
    } catch { this.status('digitalTwinStatus', 'digitalTwinStatusDot', 'OFFLINE'); this.updatePairLifecycle('UNKNOWN'); }
    setTimeout(() => this.refreshSystemStatus(), 5000);
  }
  async loadLatestPlan() { try { const result = await this.api('/api/integration/latest_plan'); if(result.status !== 'none') this.updateOptimization(result); } catch { /* The live stream remains authoritative when the plan endpoint is unavailable. */ } }
  clearOptimizationForNewPair() { this.latestPlan = null; this.explainabilityRequestedFor=null; this.explainability=null; this.renderExplainability({status:'WAITING',message:'New simulation pair; waiting for an optimizer result.',corridors:[]}); this.setText('qOptimizer','Waiting for result'); this.setText('qBitstring','N/A'); this.setText('qObjective','N/A'); this.setText('qRuntime','N/A'); this.setText('qStatus','IDLE'); this.setText('qRouteCount','—'); this.setText('qSignalCount','—'); this.setText('qRestrictionCount','—'); this.setText('qSaved','—'); this.setText('qReduction','—'); this.setText('qApplied','—'); this.setText('qRunId','—'); this.setText('quantumMapBadge','WAITING FOR OPTIMIZATION'); this.renderers.forEach(renderer => { renderer.setOverlays(); renderer.setReroutedRoute([]); }); }

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
  routeSettings() { return {source:document.getElementById('routeSource').value,alternative:document.getElementById('routeAlternative').value||null,diversion_percent:Number(document.getElementById('diversionPercent').value),blocked:document.getElementById('blockEntry').checked}; }
  highlightSelectedCorridor() { const selectedNames=[document.getElementById('routeSource')?.value,document.getElementById('routeAlternative')?.value].filter(Boolean); const vipName=document.getElementById('vipEnabled')?.checked?document.getElementById('vipCorridor')?.value:null; const constructionName=document.getElementById('constructionEnabled')?.checked?document.getElementById('constructionCorridor')?.value:null; const edgesFor=names=>[...new Set(names.filter(Boolean).flatMap(n=>this.config?.corridors?.[n]?.edges||[]))]; const selectedEdges=edgesFor(selectedNames),vipEdges=edgesFor([vipName]),constructionEdges=edgesFor([constructionName]); const actionEdges=edgesFor((this.latestPlan?.corridors||[]).filter(x=>x.enabled).map(x=>x.corridor)); this.renderers.forEach(r=>r.setOverlays({selectedEdges,actionEdges,vipEdges,constructionEdges})); }

  async applyBoth() {
    try {
      this.scenario = document.querySelector('.scenario-choice.selected')?.dataset.scenario || this.scenario;
      const applied = await this.api('/api/traffic/configure',{method:'POST',body:JSON.stringify({scenario:this.scenario,density:this.density(),vip_duration_seconds:Number(document.getElementById('vipDuration').value),construction_duration_seconds:Number(document.getElementById('constructionDuration').value),constraints:{weather:document.getElementById('weatherSelect').value,vip_enabled:document.getElementById('vipEnabled').checked,vip_corridor:document.getElementById('vipCorridor').value||null,construction_enabled:document.getElementById('constructionEnabled').checked,construction_corridor:document.getElementById('constructionCorridor').value||null},route_modifications:{}})});
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
    const signal_state = document.getElementById('signalState')?.value;
    const duration = Number(document.getElementById('signalDuration')?.value);
    const button=document.getElementById('btnApplySignal'); if(button?.disabled)return; if(button)button.disabled=true;
    this.setText('signalReadback','Status: APPLYING');
    try {
      const result = await this.api('/api/operator/signal-timing', {method:'POST', body:JSON.stringify({tls_id, signal_state, duration})});
      if (result.status !== 'APPLIED' || !result.readback_verified) throw new Error(result.reason || 'Live signal readback was not verified.');
      this.setText('signalReadback',`Status: APPLIED · ${result.contexts.classical.actual_duration_s}s · readback verified · ${new Date().toLocaleTimeString()}`);
      this.signalData = await this.api('/api/network/signals'); this.operatorCapabilities=await this.api('/api/operator/capabilities'); this.loadSignalStates();
    } catch (e) { const detail=this.errorDetail(e); this.setText('signalReadback',`Status: ${detail.status||'REJECTED'} · ${detail.reason||e.message}`); this.toast(`Signal timing rejected: ${detail.reason||e.message}`); }
    finally { if(button)button.disabled=false; }
  }
  async applyWeather() { const button=document.getElementById('btnApplyWeather'),clear=document.getElementById('btnResetWeather');if(button.disabled)return;button.disabled=true;clear.disabled=true;try { const weather=document.getElementById('weatherSelect').value; const result=await this.api('/api/constraints/weather',{method:'POST',body:JSON.stringify({weather})}); if(!result.success)throw new Error(result.reason||'SUMO did not verify the requested weather profile.'); const profile=this.operatorCapabilities?.weather_profiles?.[weather];this.setText('weatherStatus',`Active: ${weather} · speed factor ${profile?.speed_factor??'N/A'} · readback verified`); this.toast(`Weather profile ${weather} applied.`); } catch(e) { this.setText('weatherStatus',`REJECTED · ${e.message}`);this.toast(`Weather update failed: ${e.message}`); }finally{button.disabled=false;clear.disabled=false;} }
  async resetWeather() { const button=document.getElementById('btnResetWeather'),apply=document.getElementById('btnApplyWeather');if(button.disabled)return;button.disabled=true;apply.disabled=true;try { const result=await this.api('/api/constraints/weather/reset',{method:'POST',body:JSON.stringify({})}); if(!result.success)throw new Error(result.reason||'SUMO did not verify baseline weather.'); const applied=result.applied?.weather||result.applied?.constraints?.weather;await this.loadConfig(); this.setText('weatherStatus',`Cleared to configured baseline${applied?` (${applied})`:''} · readback verified`); this.toast('Weather reset to baseline profile.'); } catch(e) { this.setText('weatherStatus',`RESTORE ERROR · ${e.message}`);this.toast(`Weather reset failed: ${e.message}`); }finally{button.disabled=false;apply.disabled=false;} }
  async applyRoute() {
    const button=document.getElementById('btnApplyRoute'); if(button?.disabled)return;
    const status=document.getElementById('routeOperationStatus'), resultNode=document.getElementById('routeOperationResult');
    const clearButton=document.getElementById('btnClearRoute');if(button)button.disabled=true;if(clearButton)clearButton.disabled=true; if(status)status.textContent='Status: APPLYING'; if(resultNode)resultNode.textContent='';
    try {
      const r=this.routeSettings(); if(!r.source||!r.alternative)throw new Error('Select a source and connected alternative corridor');
      const duration_seconds=Number(document.getElementById('routeDuration').value);
      const result=await this.api('/api/operator/route-operation',{method:'POST',body:JSON.stringify({source_corridor_id:r.source,alternative_corridor_id:r.alternative,diversion_share:r.diversion_percent,block_new_entry:r.blocked,duration_seconds})});
      if(!result.readback_verified||result.status!=='APPLIED')throw new Error(result.reason||'Live route readback was not verified.');
      if(status)status.textContent=`Status: ${result.status} · ${new Date(result.timestamp).toLocaleTimeString()}`;
      this.updateOperatorTimers({route_operation:result.timer},true);
      if(resultNode){const renderSide=side=>{const item=result.contexts?.[side]||{};return `${side[0].toUpperCase()+side.slice(1)} ${item.rerouted_vehicle_count||0}/${item.eligible_vehicle_count||0} vehicles (${Number(item.actual_diversion_share||0).toFixed(1)}%)`;};resultNode.textContent=`Requested ${result.requested_diversion_share}% · ${renderSide('classical')} · ${renderSide('quantum')} · destinations preserved · readback verified`;}
      this.highlightSelectedCorridor(); this.toast('Route operation was applied and verified in both simulations.');
    } catch(e) { const detail=this.errorDetail(e); if(status)status.textContent=`Status: ${detail.status||'REJECTED'}`; if(resultNode)resultNode.textContent=detail.reason||e.message; this.toast(`Route operation ${String(detail.status||'rejected').toLowerCase()}: ${detail.reason||e.message}`); }
    finally { if(button)button.disabled=false;if(clearButton)clearButton.disabled=false; }
  }
  async clearRoute() { const button=document.getElementById('btnClearRoute'),applyButton=document.getElementById('btnApplyRoute');if(button?.disabled)return;if(button)button.disabled=true;if(applyButton)applyButton.disabled=true;this.setText('routeOperationStatus','Status: APPLYING');try{const result=await this.api('/api/operator/route-operation/clear',{method:'POST',body:JSON.stringify({})});if(!result.readback_verified)throw new Error(result.reason||'TraCI restoration was not verified');const state=await this.api('/api/operator/state');this.updateOperatorTimers(state.timers||{});this.setText('routeOperationStatus',`Status: ${result.status}`);this.setText('routeOperationResult','Previous route and corridor state restored; readback verified.');}catch(error){const detail=this.errorDetail(error);this.setText('routeOperationStatus','Status: RESTORE ERROR');this.setText('routeOperationResult',detail.reason||error.message);}finally{if(button)button.disabled=false;if(applyButton)applyButton.disabled=false;} }
  async applyConstruction() { const apply=document.getElementById('btnApplyConstruction'),clear=document.getElementById('btnClearConstruction');if(apply.disabled)return;apply.disabled=true;clear.disabled=true;try{const enabled=document.getElementById('constructionEnabled').checked;if(!enabled)throw new Error('Enable construction and select a corridor first.');const mode=document.getElementById('constructionMode').value,corridor=document.getElementById('constructionCorridor').value,duration_seconds=Number(document.getElementById('constructionDuration').value);if(!corridor)throw new Error('Select a discovered corridor.');let body={mode,enabled:true,corridor,duration_seconds};if(mode==='closure'){const item=this.corridors.find(value=>value.id===corridor);body.edges=item?.edges||[];}const result=await this.api('/api/operator/construction',{method:'POST',body:JSON.stringify(body)});if(result.success===false)throw new Error(result.message||result.reason||'SUMO did not verify construction.');this.setText('constructionTimerStatus',`ACTIVE · ${result.timer?.remaining_seconds??'—'} sec · backend expiry`);this.updateOperatorTimers({[mode==='closure'?'construction_closure':'construction_profile']:result.timer},true);}catch(error){this.setText('constructionTimerStatus',`REJECTED · ${error.message}`);}finally{apply.disabled=false;clear.disabled=false;}}
  async clearConstruction() { const button=document.getElementById('btnClearConstruction'),apply=document.getElementById('btnApplyConstruction');if(button.disabled)return;button.disabled=true;apply.disabled=true;try{const result=await this.api('/api/operator/construction/clear',{method:'POST',body:JSON.stringify({})});if(!result.readback_verified)throw new Error(result.reason||'SUMO did not verify restoration');const state=await this.api('/api/operator/state');this.updateOperatorTimers(state.timers||{});this.setText('constructionTimerStatus',`${result.status} · restoration verified`);}catch(error){this.setText('constructionTimerStatus',`RESTORE ERROR · ${error.message}`);}finally{button.disabled=false;apply.disabled=false;}}
  errorDetail(error) { try { const value=JSON.parse(error.message); return typeof value==='object'&&value?value:{reason:error.message}; } catch { return {reason:error.message}; } }
  async startBoth() { try { const state=await this.api(`/api/control/start?scenario=${encodeURIComponent(this.scenario)}`,{method:'POST'}); this.updatePairLifecycle(state.lifecycle_state); await this.loadConfig(); this.toast(state.action==='resumed'?'Simulation resumed.':state.action==='already_running'?'Simulation is already running.':'Simulation pair started.'); } catch(e) { this.toast(e.message); } }
  async togglePause() { try { const action=this.lifecycle==='PAUSED'?'resume':'pause'; const state=await this.api(`/api/control/${action}`,{method:'POST'}); this.updatePairLifecycle(state.lifecycle_state); } catch(e) { this.toast(e.message); } }
  async restartBoth() { try { await this.api('/api/control/reset',{method:'POST'}); await this.loadConfig(); this.toast('Both simulations restarted with the active scenario.'); } catch(e) { this.toast(e.message); } }
  async selectScenario(scenario) { document.querySelectorAll('.scenario-choice').forEach(b=>b.classList.toggle('selected',b.dataset.scenario===scenario)); this.scenario=scenario; try { const config=await this.api(`/api/traffic/config?scenario=${scenario}`); this.config={...this.config,...config}; const density=config.density||{}; for(const [key,id] of Object.entries({cars:'densityCars',buses:'densityBuses',two_wheelers:'densityTwoWheelers',pedestrians:'densityPedestrians',local_trains:'densityTrains'})) { const field=document.getElementById(id); field.value=density[key]??0; field.disabled=config.capabilities?.[key]?.supported===false; } } catch(e) { this.toast(e.message); } }
  async setSpeed(speed) { try { await this.api(`/api/control/speed?multiplier=${speed}`,{method:'POST'}); return true; } catch(e) { this.toast(e.message); return false; } }
  setLayer(layer, enabled) { this.renderers.forEach(renderer => { if (layer === 'buildings') { renderer.setLayer('buildings',enabled); renderer.setLayer('shops',enabled); } else renderer.setLayer(layer,enabled); }); if(layer==='vipRoute'||layer==='construction'||layer==='routes'||layer==='actions')this.highlightSelectedCorridor(); }
  clearSelection() { this.renderers.forEach(r=>{r.selectedEntity=null;r.setOverlaySelection([],[])}); this.setText('inspectorContent','Select a road segment, junction, or vehicle on either map.'); }
  inspect(item, side) { const state=this.snapshots[side]||{}, id=item.edgeId||item.junctionId||item.entityId; let rows={Selection:id,Type:item.type||'Road'}; if(item.edgeId){const x=state.edges_congestion?.[id]; const vehicles=(state.vehicles||[]).filter(v=>v.road_id===id); const corridors=Object.entries(this.config?.corridors||{}).filter(([,value])=>value.edges?.includes(id)).map(([name])=>name); const action=(this.latestPlan?.corridors||[]).find(a=>corridors.includes(a.corridor)&&a.enabled); rows={...rows,'Corridor':corridors.join(', ')||'N/A','Traffic level':x?.level||'N/A','Vehicle count':vehicles.length,'Queue':x?.queue_len==null?'N/A':`${x.queue_len} m`,'Average speed':vehicles.length?`${(vehicles.reduce((sum,v)=>sum+(Number(v.speed_kmh)||0),0)/vehicles.length).toFixed(1)} km/h`:'N/A','Status':x?.level||'N/A','Optimizer output':action?`Model estimate: ${action.rerouted} diversions; live route changes are not verified by this estimate.`:'No corridor decision returned'};} else if(item.junctionId||item.type==='TrafficSignal'){const signal=Object.values(state.traffic_lights||{}).find(x=>x.id===id); const action=(this.latestPlan?.signal_changes||[]).find(a=>a.junction===id||this.config?.junctions?.[a.junction]?.sumo_id===id); rows={...rows,'Signal state':signal?.state||'N/A','Duration':signal?.phase_duration_s==null?'N/A':`${signal.phase_duration_s} s`,'Next change':signal?.seconds_to_switch==null?'N/A':`${signal.seconds_to_switch} s`,'Traffic count':'N/A','Queue':'N/A','Optimization status':action?`Optimizer output: ${action.old_green}s → ${action.new_green}s`:'No action returned'};} else rows={...rows,'Simulation':side,'Speed':item.speed||'N/A','Road':item.edge||'N/A'}; document.getElementById('inspectorContent').innerHTML=Object.entries(rows).map(([k,v])=>`<div class="inspector-row"><span>${this.escape(k)}</span><b>${this.escape(v)}</b></div>`).join(''); }

  async optimize() { const button=document.getElementById('btnTriggerQuantum'); button.disabled=true; const message_id=crypto.randomUUID(); try { const result=await this.api('/api/integration/trigger_optimization',{method:'POST',body:JSON.stringify({message_id,scenario_id:this.scenario})}); this.updateOptimization(result); this.toast(`${result.optimizer_used || 'Optimizer'} result ${result.status}`); } catch(e) { this.toast(`Optimization failed: ${e.message}`); } finally { button.disabled=false; } }
  updateOptimization(plan) { if(!plan)return; this.latestPlan={...(this.latestPlan||{}),...plan}; plan=this.latestPlan; const key=plan.run_id||plan.message_id||plan.bitstring; if(key&&key!==this.explainabilityRequestedFor){this.explainabilityRequestedFor=key;this.loadExplainability();} const status=String(plan.status||'completed').toUpperCase(); const applied=Boolean(plan.applied_to_sumo ?? plan.applied); this.setText('qOptimizer',plan.optimizer_used||'N/A'); this.setText('qBitstring',plan.bitstring||'N/A'); this.setText('qObjective',plan.objective_value??'N/A'); this.setText('qRuntime',plan.runtime_seconds==null?'N/A':`${Number(plan.runtime_seconds).toFixed(2)} s`); this.setText('qStatus',applied?`${status} · APPLIED`:status); this.setText('qRouteCount',(plan.corridors||[]).filter(x=>x.enabled).length); this.setText('qSignalCount',(plan.signal_changes||[]).length); this.setText('qRestrictionCount',(plan.restrictions||[]).length); this.setText('qSaved',plan.benefits?.travel_time_saved_minutes==null?'N/A':`${plan.benefits.travel_time_saved_minutes} min`); this.setText('qReduction',plan.benefits?.queue_reduction_percent==null?'N/A':`${plan.benefits.queue_reduction_percent}%`); this.setText('qApplied',applied?'APPLIED':'NOT APPLIED'); this.setText('qRunId',plan.run_id||plan.optimization_run_id||plan.message_id||'—'); const badge=plan.optimizer_used?.includes('Fallback')?'CLASSICAL FALLBACK':plan.optimizer_used==='Quantum'?'QUANTUM RESULT':plan.optimizer_used||'OPTIMIZATION RESULT'; this.setText('quantumMapBadge',plan.status==='failed'?'VALIDATION FAILED':applied?`${badge} · APPLIED`:badge); const active=status.includes('FAIL')? 'requested':applied?'completed':status.includes('RUN')?'running':'validated'; document.querySelectorAll('.pipeline [data-stage]').forEach(el=>{const stages=['requested','running','validated','applied','completed'];el.classList.toggle('done',stages.indexOf(el.dataset.stage)<stages.indexOf(active));el.classList.toggle('active',el.dataset.stage===active);}); this.highlightSelectedCorridor(); }
  renderEvents(filter='all') { const target=document.getElementById('eventLog'); if(!target)return; const events=(this.events||[]).filter(e=>filter==='all'||e.category===filter); target.innerHTML=events.length?events.slice(-80).reverse().map(e=>`<div class="event-row"><time>${this.escape(new Date(e.timestamp).toLocaleTimeString())}</time><b>${this.escape(e.category||'system')}</b><span>${this.escape(e.message||'')}</span></div>`).join(''):'<span class="muted">Waiting for server events.</span>'; const timeline=document.getElementById('timelineView'); if(timeline)timeline.innerHTML=events.slice(-12).map(e=>`<div class="timeline-event"><time>${this.escape(this.formatTime(e.sim_time))}</time><span>${this.escape(e.message)}</span></div>`).join('')||'<span class="muted">Timeline events appear as the simulations run.</span>'; }
}

window.addEventListener('DOMContentLoaded', () => { window.digitalTwinApp = new DigitalTwinApp(); });
