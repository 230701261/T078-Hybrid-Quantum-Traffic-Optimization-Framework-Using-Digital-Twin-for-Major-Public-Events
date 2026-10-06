/**
 * Dashboard & Telemetry Manager
 * Handles KPI card animations, Chart.js graphs, and comparison matrix updates.
 */

class DashboardManager {
    constructor() {
        this.chartSpeedCongestion = null;
        this.chartEntitiesVolume = null;
        this.initCharts();
    }

    initCharts() {
        const speedCtx = document.getElementById('chartSpeedCongestion');
        const entityCtx = document.getElementById('chartEntitiesVolume');

        if (window.Chart && speedCtx && entityCtx) {
            // Chart 1: Speed & Congestion
            this.chartSpeedCongestion = new Chart(speedCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Avg Speed (km/h)',
                            data: [],
                            borderColor: '#38bdf8',
                            backgroundColor: 'rgba(56, 189, 248, 0.1)',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: true,
                            yAxisID: 'y'
                        },
                        {
                            label: 'Congestion (%)',
                            data: [],
                            borderColor: '#ef4444',
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: true,
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: { display: false },
                        y: {
                            type: 'linear',
                            position: 'left',
                            min: 0,
                            max: 60,
                            ticks: { color: '#94a3b8', font: { size: 9 } },
                            grid: { color: 'rgba(51, 65, 85, 0.3)' }
                        },
                        y1: {
                            type: 'linear',
                            position: 'right',
                            min: 0,
                            max: 100,
                            ticks: { color: '#ef4444', font: { size: 9 } },
                            grid: { display: false }
                        }
                    }
                }
            });

            // Chart 2: Entities Volume
            this.chartEntitiesVolume = new Chart(entityCtx, {
                type: 'line',
                data: {
                    labels: [],
                    datasets: [
                        {
                            label: 'Vehicles',
                            data: [],
                            borderColor: '#06b6d4',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: false
                        },
                        {
                            label: 'Pedestrians',
                            data: [],
                            borderColor: '#f59e0b',
                            borderWidth: 2,
                            tension: 0.3,
                            fill: false
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: false,
                    plugins: {
                        legend: {
                            display: true,
                            labels: { color: '#cbd5e1', font: { size: 10 }, boxWidth: 10 }
                        }
                    },
                    scales: {
                        x: { display: false },
                        y: {
                            min: 0,
                            ticks: { color: '#94a3b8', font: { size: 9 } },
                            grid: { color: 'rgba(51, 65, 85, 0.3)' }
                        }
                    }
                }
            });
        }
    }

    update(state) {
        if (!state) return;
        const kpi = state.kpis;
        if (!kpi) return;

        // 1. Update KPI Card values
        this.setText('kpiVehicles', kpi.active_vehicles);
        this.setText('kpiPedestrians', kpi.active_pedestrians);
        this.setText('kpiBuses', kpi.active_buses);
        this.setText('kpiSpeed', `${kpi.avg_speed_kmh} <span class="text-xs text-slate-400">km/h</span>`);
        this.setText('kpiCongestionVal', `${kpi.overall_congestion_pct}%`);
        this.setText('kpiWait', `${kpi.avg_waiting_time_s} <span class="text-xs text-slate-400">sec</span>`);
        this.setText('kpiQueue', `${kpi.total_queue_length_m}m`);
        this.setText('kpiStadiumVisitors', kpi.stadium_visitors_total);
        this.setText('kpiRailArrivals', kpi.railway_arrivals_total);

        // Update Congestion Bar & Color
        const congBar = document.getElementById('kpiCongestionBar');
        const congVal = document.getElementById('kpiCongestionVal');
        if (congBar && congVal) {
            congBar.style.width = `${Math.min(100, kpi.overall_congestion_pct)}%`;
            if (kpi.overall_congestion_pct > 65) {
                congBar.className = 'bg-rose-500 h-full rounded-full transition-all duration-300 shadow-[0_0_8px_#f43f5e]';
                congVal.className = 'text-rose-400 font-bold';
            } else if (kpi.overall_congestion_pct > 30) {
                congBar.className = 'bg-amber-400 h-full rounded-full transition-all duration-300';
                congVal.className = 'text-amber-400 font-bold';
            } else {
                congBar.className = 'bg-emerald-400 h-full rounded-full transition-all duration-300';
                congVal.className = 'text-emerald-400 font-bold';
            }
        }

        // Update Simulation Time Clock
        const simTime = state.time || 0;
        const mins = Math.floor(simTime / 60).toString().padStart(2, '0');
        const secs = (simTime % 60).toFixed(1).padStart(4, '0');
        this.setText('simTimeDisplay', `${mins}:${secs}`);

        // 2. Update Charts
        if (state.chart_data && this.chartSpeedCongestion && this.chartEntitiesVolume) {
            const cd = state.chart_data;
            const labels = cd.timestamps.map(t => `${t}s`);

            this.chartSpeedCongestion.data.labels = labels;
            this.chartSpeedCongestion.data.datasets[0].data = cd.speed;
            this.chartSpeedCongestion.data.datasets[1].data = cd.congestion;
            this.chartSpeedCongestion.update();

            this.chartEntitiesVolume.data.labels = labels;
            this.chartEntitiesVolume.data.datasets[0].data = cd.vehicles;
            this.chartEntitiesVolume.data.datasets[1].data = cd.pedestrians;
            this.chartEntitiesVolume.update();
        }

        // 3. Update Corridors Leaderboard
        this.updateCorridors(state.edges_congestion);

        // 4. Update Signals List
        this.updateSignals(state.traffic_lights);
    }

    updateCorridors(edgesCongestion) {
        const container = document.getElementById('corridorsList');
        if (!container || !edgesCongestion) return;

        const mainRoads = Object.entries(edgesCongestion)
            .filter(([, data]) => data && Number.isFinite(Number(data.occupancy))
                && Number.isFinite(Number(data.queue_len)))
            .sort((a, b) => Number(b[1].queue_len) - Number(a[1].queue_len))
            .slice(0, 5);

        let html = '';
        for (const [edgeId, cData] of mainRoads) {
            const pct = Math.min(100, Math.round(cData.occupancy * 100));
            let badgeClass = 'text-emerald-400 bg-emerald-950/60 border border-emerald-500/30';
            if (cData.level === 'red') badgeClass = 'text-rose-400 bg-rose-950/60 border border-rose-500/30 font-bold';
            else if (cData.level === 'yellow') badgeClass = 'text-amber-400 bg-amber-950/60 border border-amber-500/30';

            html += `
                <div class="flex items-center justify-between p-1.5 rounded-lg bg-slate-900/60 border border-slate-800/40">
                    <span class="text-slate-300 truncate max-w-[170px]">${edgeId}</span>
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] text-slate-500">${cData.queue_len}m Q</span>
                        <span class="px-1.5 py-0.5 rounded text-[10px] ${badgeClass}">${pct}%</span>
                    </div>
                </div>
            `;
        }
        container.innerHTML = html || '<div class="muted">Waiting for measured edge telemetry.</div>';
    }

    updateSignals(trafficLights) {
        const container = document.getElementById('signalsList');
        if (!container || !trafficLights) return;

        const monitoredJunctions = [
            { id: 'J_WAL_QUAID', label: 'Wal / Quaid' },
            { id: 'J_WAL_BELLS', label: 'Wal / Bells' },
            { id: 'J_WAL_KAM', label: 'Wal / Kamarajar' },
            { id: 'J_PYC_BELLS', label: 'Pyc / Bells' },
            { id: 'J_BELLS_STAD', label: 'Bells / Stad' },
            { id: 'J_PYC_KAM', label: 'Pyc / Beach' }
        ];

        let html = '';
        for (const j of monitoredJunctions) {
            const tl = trafficLights[j.id] || { color: 'green', phase: 0 };
            let bulbClass = 'bg-emerald-400 shadow-[0_0_8px_#34d399]';
            if (tl.color === 'red') bulbClass = 'bg-rose-500 shadow-[0_0_8px_#f43f5e]';
            else if (tl.color === 'yellow') bulbClass = 'bg-amber-400 shadow-[0_0_8px_#fbbf24]';

            html += `
                <div class="p-1.5 rounded-lg bg-slate-900/60 border border-slate-800/40 flex items-center justify-between">
                    <span class="text-[11px] text-slate-400 truncate">${j.label}</span>
                    <span class="w-2.5 h-2.5 rounded-full ${bulbClass}"></span>
                </div>
            `;
        }
        container.innerHTML = html;
    }

    setText(id, text) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = text;
    }
}
