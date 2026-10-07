/** Three.js view of the SUMO network, exported landmarks, and live TraCI state. */

// Buffer geometry is immutable after construction, so both synchronized map
// scenes can share the same CPU-side road ribbon geometry.
const sharedRibbonGeometry = new Map();
const sharedUnitBoxGeometry = new THREE.BoxGeometry(1, 1, 1);
const sharedUrbanBlockGeometry = new THREE.BoxGeometry(1, 1, 1);
const sharedUrbanLGeometry = (() => {
    const footprint = new THREE.Shape();
    footprint.moveTo(-0.5, -0.5); footprint.lineTo(0.5, -0.5);
    footprint.lineTo(0.5, -0.12); footprint.lineTo(-0.08, -0.12);
    footprint.lineTo(-0.08, 0.5); footprint.lineTo(-0.5, 0.5); footprint.closePath();
    return new THREE.ExtrudeGeometry(footprint, { depth: 1, bevelEnabled: false });
})();

class SimulationRenderer3D {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.geometry = null;
        this.state = null;

        // Three.js Core
        this.scene = null;
        this.camera = null;
        this.renderer = null;
        this.controls = null;
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();

        // Object Pools (mapped 1:1 by TraCI ID)
        this.vehicleMeshes = new Map();
        this.pedestrianMeshes = new Map();
        this.signalMeshes = new Map();
        this.renderedPedestrianConnectors = new Set();
        this.roadMeshes = new Map();
        this.edgeMaterials = new Map();
        this.stadiumAccessEdges = new Set();
        this.baseRoadColor = 0x1e293b;
        this.theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
        this.groundMesh = null;
        this.selectedEdges = new Set();
        this.actionEdges = new Set();
        this.reroutedEdges = new Set();
        this.corridors = [];
        this.vipEdges = new Set();
        this.constructionEdges = new Set();
        this.overlayLayers = { congestion: true, routes: true, actions: true };
        this.onEntitySelected = null;
        this.stadiumMeshGroup = null;
        this.waterMesh = null;
        this.coastLabelPosition = null;
        this.busStopMeshes = [];
        this.nearestStationBusStop = null;
        this.roadsideShopMeshes = [];
        this.staticRoot = null;
        this.networkCenter = new THREE.Vector3();
        this.networkSpan = new THREE.Vector2(800, 800);
        this.defaultCameraPose = null;
        this.staticMaterials = {};
        this.labelSprites = [];

        // Settings & Layer Toggles
        this.layers = {
            vehicles: true,
            pedestrians: true,
            signals: true,
            buildings: true,
            shops: true,
            congestion: true,
            routes: true,
            actions: true,
            vipRoute: true,
            construction: true
        };

        // Follow Camera Target
        this.followTarget = null;
        this.followType = null;
        this.selectedEntity = null;

        // Animation Time
        this.clock = new THREE.Clock();
        this.animTime = 0;

        this.init();
    }

    init() {
        // 1. Scene
        this.scene = new THREE.Scene();
        const sceneColor = this.theme === 'light' ? 0xe8eef2 : 0x060913;
        this.scene.background = new THREE.Color(sceneColor);
        this.scene.fog = new THREE.FogExp2(sceneColor, 0.00075);

        // 2. Camera
        const width = Math.max(1, this.container.clientWidth || window.innerWidth);
        const height = Math.max(1, this.container.clientHeight || window.innerHeight);
        this.camera = new THREE.PerspectiveCamera(45, width / height, 1, 4500);
        this.camera.position.set(450, 560, 520);

        // 3. WebGL Renderer
        this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
        this.renderer.setSize(width, height);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
        this.renderer.shadowMap.enabled = true;
        this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.18;
        this.container.appendChild(this.renderer.domElement);

        // 4. OrbitControls
        if (THREE.OrbitControls) {
            this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
            this.controls.enableDamping = true;
            this.controls.dampingFactor = 0.08;
            this.controls.maxPolarAngle = Math.PI / 2 - 0.02;
            this.controls.minDistance = 20;
            this.controls.maxDistance = 1800;
            this.controls.target.set(450, 0, -400);
            this.controls.update();
        }

        // 5. Lighting
        this.setupLighting();

        // 6. Event Listeners
        window.addEventListener('resize', () => this.onResize());
        this.renderer.domElement.addEventListener('mousemove', (e) => this.onMouseMove(e));
        this.renderer.domElement.addEventListener('click', (e) => this.onClick(e));

        // Start render loop
        this.animate();
    }

    setupLighting() {
        const ambient = new THREE.AmbientLight(0xdbeafe, 0.55);
        this.scene.add(ambient);

        const sun = new THREE.DirectionalLight(0xfffaed, 0.95);
        sun.position.set(350, 650, 250);
        sun.castShadow = true;
        sun.shadow.mapSize.width = 2048;
        sun.shadow.mapSize.height = 2048;
        sun.shadow.camera.near = 10;
        sun.shadow.camera.far = 1600;
        sun.shadow.camera.left = -700;
        sun.shadow.camera.right = 700;
        sun.shadow.camera.top = 700;
        sun.shadow.camera.bottom = -700;
        sun.shadow.bias = -0.0005;
        this.scene.add(sun);

        const hemi = new THREE.HemisphereLight(0x38bdf8, 0x0f172a, 0.45);
        this.scene.add(hemi);
    }

    onResize() {
        if (!this.container || !this.renderer) return;
        const width = Math.max(1, this.container.clientWidth);
        const height = Math.max(1, this.container.clientHeight);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height);
    }

    onMouseMove(event) {
        const rect = this.renderer.domElement.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    }

    onClick(event) {
        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.scene.children, true);
        
        let found = null;
        for (const hit of intersects) {
            let obj = hit.object;
            while (obj && obj !== this.scene) {
                if (obj.userData && (obj.userData.entityId || obj.userData.edgeId || obj.userData.junctionId)) {
                    found = obj.userData;
                    break;
                }
                obj = obj.parent;
            }
            if (found) {
                break;
            }
        }

        const tooltip = document.getElementById('inspectorTooltip');
        const tooltipContent = document.getElementById('tooltipContent');

        if (found) {
            this.selectedEntity = found;
            if (this.onEntitySelected) this.onEntitySelected(found);
            if (found.type === 'Vehicle') {
                this.followTarget = this.vehicleMeshes.get(found.entityId);
                this.followType = 'vehicle';
            } else if (found.type === 'Pedestrian') {
                this.followTarget = this.pedestrianMeshes.get(found.entityId);
                this.followType = 'pedestrian';
            }

            if (tooltip && tooltipContent) {
                let html = `
                    <div class="font-bold text-cyan-300 border-b border-slate-700/80 pb-1.5 mb-2 flex justify-between items-center">
                        <span class="flex items-center gap-1.5">
                            <span>${found.type === 'Vehicle' ? '🚗' : '🚶'}</span>
                            <span>${found.type}</span>
                        </span>
                        <span class="font-mono text-[10px] px-1.5 py-0.5 rounded bg-cyan-950/80 text-cyan-400">#${found.entityId}</span>
                    </div>
                `;
                for (const [k, val] of Object.entries(found)) {
                    if (k !== 'type' && k !== 'entityId') {
                        html += `<div class="flex justify-between py-0.5"><span class="text-slate-400 capitalize">${k}:</span><span class="font-mono font-semibold text-slate-200">${val}</span></div>`;
                    }
                }
                html += `<div class="mt-2 text-[10px] text-cyan-400/80 italic font-mono text-center">🎯 Locked to Follow Cam</div>`;
                tooltipContent.innerHTML = html;
                tooltip.style.left = `${Math.min(window.innerWidth - 280, event.clientX + 15)}px`;
                tooltip.style.top = `${Math.min(window.innerHeight - 200, event.clientY + 15)}px`;
                tooltip.classList.remove('hidden');
            }
        } else {
            this.selectedEntity = null;
            this.followTarget = null;
            if (tooltip) tooltip.classList.add('hidden');
        }
    }

    worldToSceneCoordinates(sumoX, sumoY, elevation = 0) {
        // netconvert's local frame uses +X east and +Y north in this network.
        // Three.js uses +X east and -Z north; all exported layers share this map.
        return new THREE.Vector3(sumoX, elevation, -sumoY);
    }

    sumoTo3D(sumoX, sumoY, elevation = 0) {
        return this.worldToSceneCoordinates(sumoX, sumoY, elevation);
    }

    shapeCoordinates(sumoX, sumoY) {
        // Extruded ShapeGeometry is rotated -90° around X. Its local Y maps to
        // world Z with a sign flip, so use northing as local Shape Y.
        return [sumoX, sumoY];
    }

    setGeometry(geoData) {
        this.geometry = geoData;
        this.buildNetworkScene();
    }

    /* Build the static city from the geometry exported from the loaded SUMO net.
       No road shapes, coastline, station or stadium position is authored here. */
    buildNetworkScene() {
        if (!this.geometry?.edges?.length) return;
        if (this.staticRoot) this.scene.remove(this.staticRoot);
        if (this.closureMarkers) for (const marker of this.closureMarkers.values()) this.scene.remove(marker);
        this.closureMarkers = new Map();
        this.labelSprites = [];
        this.busStopMeshes = [];
        this.nearestStationBusStop = null;
        this.roadsideShopMeshes = [];
        this.waterMesh = null;
        this.coastLabelPosition = null;
        this.cityBuildingMesh = null;
        this.roadMeshes.clear();
        this.edgeMaterials.clear();
        this.stadiumAccessEdges.clear();
        this.signalMeshes.clear();
        this.renderedPedestrianConnectors.clear();
        this.staticRoot = new THREE.Group();
        this.scene.add(this.staticRoot);

        const b = this.geometry.bbox || {};
        const minX = Number(b.min_x ?? 0), maxX = Number(b.max_x ?? 1);
        const minY = Number(b.min_y ?? 0), maxY = Number(b.max_y ?? 1);
        const polygons = this.geometry.polygons || [];
        const allPolygonPoints = polygons.flatMap(p => p.shape || []);
        const sceneMinX = Math.min(minX, ...allPolygonPoints.map(p => p[0]));
        const sceneMaxX = Math.max(maxX, ...allPolygonPoints.map(p => p[0]));
        const sceneMinY = Math.min(minY, ...allPolygonPoints.map(p => p[1]));
        const sceneMaxY = Math.max(maxY, ...allPolygonPoints.map(p => p[1]));
        const width = Math.max(1, sceneMaxX - sceneMinX), depth = Math.max(1, sceneMaxY - sceneMinY);
        this.networkCenter.copy(this.worldToSceneCoordinates((minX + maxX) / 2, (minY + maxY) / 2));
        this.networkSpan.set(width, depth);
        this.studyAreaCenter = this.worldToSceneCoordinates((sceneMinX + sceneMaxX) / 2, (sceneMinY + sceneMaxY) / 2);
        const extent = Math.max(width, depth);

        const dark = this.theme !== 'light';
        this.baseRoadColor = dark ? 0x3a444c : 0x59646d;
        const groundMat = new THREE.MeshStandardMaterial({ color: dark ? 0x111923 : 0xd9dedf, roughness: 1 });
        const ground = new THREE.Mesh(new THREE.PlaneGeometry(width * 1.04, depth * 1.04), groundMat);
        ground.rotation.x = -Math.PI / 2;
        ground.position.copy(this.worldToSceneCoordinates((sceneMinX + sceneMaxX) / 2, (sceneMinY + sceneMaxY) / 2, -0.2));
        ground.receiveShadow = true;
        this.staticRoot.add(ground);
        this.groundMesh = ground;
        this.staticMaterials = {
            road: new THREE.MeshStandardMaterial({ color: this.baseRoadColor, roughness: 0.9 }),
            junction: new THREE.MeshStandardMaterial({ color: dark ? 0x323b43 : 0x69737a, roughness: 0.95 }),
            roadEdge: new THREE.MeshStandardMaterial({ color: dark ? 0x707c84 : 0x747e84, roughness: 0.9 }),
            laneMark: new THREE.MeshBasicMaterial({ color: dark ? 0xd3dbe0 : 0xf3f5f4 }),
            crosswalk: new THREE.MeshBasicMaterial({
                color: 0xf8faf8,
                depthTest: true,
                polygonOffset: true,
                polygonOffsetFactor: -1,
                polygonOffsetUnits: -2
            }),
            curb: new THREE.MeshStandardMaterial({ color: dark ? 0x69747e : 0x91999f, roughness: 0.9 }),
            railBed: new THREE.MeshStandardMaterial({ color: dark ? 0x39434d : 0x686e72, roughness: 0.95 }),
            rail: new THREE.MeshStandardMaterial({ color: 0x9aa3a8, metalness: 0.7, roughness: 0.35 }),
            building: new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.92 }),
            stadium: new THREE.MeshStandardMaterial({ color: dark ? 0x737d87 : 0x9ba4a8, roughness: 0.78 }),
            roof: new THREE.MeshStandardMaterial({ color: dark ? 0xa8b3bb : 0xe1e5e5, roughness: 0.55, metalness: 0.1 }),
            field: new THREE.MeshStandardMaterial({ color: 0x32794f, roughness: 0.95 }),
            land: new THREE.MeshStandardMaterial({ color: dark ? 0x202b2b : 0xc8d1c6, roughness: 1 }),
            beach: new THREE.MeshStandardMaterial({ color: dark ? 0xa48a62 : 0xd3bf96, roughness: 1 }),
            water: new THREE.MeshStandardMaterial({ color: dark ? 0x174f67 : 0x5b9daf, roughness: 0.34, metalness: 0.04 }),
            pedestrianPath: new THREE.MeshStandardMaterial({ color: dark ? 0xb8aa8f : 0x8f8068, roughness: 0.95 }),
            accessMarker: new THREE.MeshStandardMaterial({ color: dark ? 0xc3a66f : 0x80653b, roughness: 0.7 }),
            stationPlatform: new THREE.MeshStandardMaterial({ color: dark ? 0x82919a : 0x858d8e, roughness: 0.82 }),
            stationRoof: new THREE.MeshStandardMaterial({ color: dark ? 0x647780 : 0x667176, roughness: 0.72, metalness: 0.1 })
        };

        const landmark = id => polygons.find(p => p.id === id && p.shape?.length >= 3);
        const stadium = landmark('poly_stadium');
        const station = landmark('poly_station_elevated');
        const beach = landmark('poly_beach');
        for (const polygon of polygons) {
            if (polygon === stadium) this.buildStadiumFromPolygon(polygon);
            else if (polygon === station) this.buildStationFromPolygon(polygon);
            else if (polygon === beach) this.buildCoastFromPolygon(polygon, minX, maxX, minY, maxY);
            else this.buildLandmarkPolygon(polygon, 0.12, this.staticMaterials.land);
        }

        this.buildJunctionSurfaces();
        const railSamples = [];
        for (const edge of this.geometry.edges) {
            const lanes = edge.lanes || [];
            const drivable = lanes.filter(l => l.shape?.length >= 2 && !l.allow?.includes('pedestrian'));
            const stadiumAccess = /stadium_access/i.test(edge.type || '') || /^E_STAD_(ACC|RING)/.test(edge.id);
            if (stadiumAccess && drivable.length) this.stadiumAccessEdges.add(edge.id);
            const rail = lanes.some(l => l.allow?.some(vehicleClass => /^rail/.test(vehicleClass))) || /rail/i.test(edge.id) || /rail/i.test(edge.type || '');
            const sidewalk = lanes.length && lanes.every(l => l.allow?.includes('pedestrian'));
            for (const lane of lanes) {
                if (!lane.shape || lane.shape.length < 2) continue;
                const pedestrianOnly = lane.allow?.includes('pedestrian') && !lane.allow?.includes('passenger');
                if (pedestrianOnly) {
                    this.buildPedestrianPath(lane);
                    continue;
                }
                const widthM = Math.max(0.8, Number(lane.width) || 3.2);
                const elevation = Math.max(0, Number(lane.elevation) || 0) + (rail ? 0.08 : 0.24);
                let material = this.staticMaterials.railBed;
                if (!rail) {
                    if (!this.edgeMaterials.has(edge.id)) this.edgeMaterials.set(edge.id,
                        new THREE.MeshStandardMaterial({ color: this.baseRoadColor, roughness: 0.88, metalness: 0.01 }));
                    material = this.edgeMaterials.get(edge.id);
                    if (!sidewalk) {
                        const edgeWidth = stadiumAccess ? 1.05 : drivable.length >= 2 || Number(lane.speed) >= 13.89 ? 0.76 : 0.58;
                        const edgeMesh = this.createRibbonMesh(lane.shape, widthM + edgeWidth, elevation - 0.12,
                            this.staticMaterials.roadEdge, 0.30);
                        if (edgeMesh) { edgeMesh.userData.roadEdge = true; this.staticRoot.add(edgeMesh); }
                    }
                }
                const surfaceWidth = widthM + (rail ? 0.25 : stadiumAccess && !pedestrianOnly ? 0.62 : 0.22);
                const mesh = this.createRibbonMesh(lane.shape, surfaceWidth, elevation, material, rail ? 0.18 : 0.30);
                if (!mesh) continue;
                mesh.userData.edgeId = edge.id;
                mesh.receiveShadow = true;
                this.staticRoot.add(mesh);
                if (!rail && !sidewalk) {
                    if (!this.roadMeshes.has(edge.id)) {
                        this.roadMeshes.set(edge.id, []);
                    }
                    this.roadMeshes.get(edge.id).push(mesh);
                }
                if (rail) {
                    railSamples.push(this.samplePolyline(lane.shape, 0.5));
                    this.addRailTrack(lane.shape, elevation + 0.13, widthM);
                }
            }
            if (drivable.length) this.addLaneSeparators(drivable);
        }

        this.createUrbanBuildings(extent);
        this.buildNetworkBusStops();
        this.buildSignalPoles();
        this.buildPedestrianCrossings();
        this.buildStationAccessLabel();
        const chepauk = stadium ? this.polygonCentroid(stadium.shape) : { x: this.networkCenter.x, y: -this.networkCenter.z };
        this.addMapLabelAtWorld('CHEPAUK', chepauk.x - width * 0.08, chepauk.y - depth * 0.08, 1, 0x99d9ee);
        if (stadium) {
            const c = this.polygonCentroid(stadium.shape);
            this.addMapLabelAtWorld('MA CHIDAMBARAM STADIUM', c.x, c.y, 22, 0xf2f5f6);
        }
        if (station) {
            const c = this.polygonCentroid(station.shape);
            this.addMapLabelAtWorld('CHEPAUK RAILWAY STATION', c.x, c.y, this.getRailElevation() + 5, 0xe5edf0);
        }
        this.addStadiumAccessMarkers();
        if (beach) {
            const c = this.coastLabelPosition || this.polygonCentroid(beach.shape);
            this.addMapLabelAtWorld('MARINA  /  BAY OF BENGAL', c.x, c.y, 1.2, 0xc2e6ef);
        }
        if (railSamples.length) {
            const c = railSamples.reduce((sum, p) => ({ x: sum.x + p[0], y: sum.y + p[1] }), { x: 0, y: 0 });
            this.addMapLabelAtWorld('RAILWAY  /  MRTS', c.x / railSamples.length, c.y / railSamples.length, 10, 0xe5edf0);
        }
        this.buildCorridorLabels();
        this.defaultCameraPose = this.configureDigitalTwinCamera(extent);
        this.camera.position.copy(this.defaultCameraPose.position);
        if (this.controls) {
            this.controls.target.copy(this.defaultCameraPose.target);
            this.controls.maxDistance = extent * 2.5;
            this.controls.minDistance = Math.max(8, extent * 0.012);
            this.controls.update();
        }
        this.updateRoadVisualization(this.state || {});
    }

    polygonCentroid(points) {
        const sum = points.reduce((a, p) => ({ x: a.x + p[0], y: a.y + p[1] }), { x: 0, y: 0 });
        return { x: sum.x / points.length, y: sum.y / points.length };
    }

    configureDigitalTwinCamera(extent) {
        // A moderate elevated view keeps the actual SUMO network legible while
        // placing the +X (east/coast in this local Chepauk network frame) side
        // toward the right of the composition.
        const target = (this.studyAreaCenter || this.networkCenter).clone();
        const position = target.clone().add(new THREE.Vector3(extent * 0.55, extent * 0.95, extent * 0.95));
        return { target, position };
    }

    getStadiumAreaViewSpan() {
        const stadium = this.geometry?.polygons?.find(p => p.id === 'poly_stadium');
        const station = (this.geometry?.nodes || []).find(node => node.id === 'N_STATION_GROUND');
        if (!stadium || !station) return Math.max(180, Math.min(Math.max(this.networkSpan.x, this.networkSpan.y), 500));
        const center = this.polygonCentroid(stadium.shape);
        const stationDistance = Math.hypot(station.x - center.x, station.y - center.y);
        const stadiumWidth = Math.max(...stadium.shape.map(p => p[0])) - Math.min(...stadium.shape.map(p => p[0]));
        const pickupDistance = this.nearestStationBusStop
            ? Math.hypot(this.nearestStationBusStop.x - center.x, this.nearestStationBusStop.y - center.y) : 0;
        return Math.max(180, stadiumWidth * 2.6, stationDistance * 2.2, pickupDistance * 1.35);
    }

    polygonMesh(points, material, height = 0.1, baseElevation = 0) {
        if (!points || points.length < 3) return null;
        const shape = new THREE.Shape();
        const first = this.shapeCoordinates(points[0][0], points[0][1]);
        shape.moveTo(first[0], first[1]);
        for (let i = 1; i < points.length; i++) {
            const coordinate = this.shapeCoordinates(points[i][0], points[i][1]);
            shape.lineTo(coordinate[0], coordinate[1]);
        }
        shape.closePath();
        const mesh = new THREE.Mesh(new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false }), material);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.y = baseElevation;
        mesh.receiveShadow = true;
        mesh.castShadow = height > 1;
        return mesh;
    }

    getRailElevation() {
        const elevations = (this.geometry?.edges || []).filter(edge => /rail/i.test(edge.id) || /rail/i.test(edge.type || ''))
            .flatMap(edge => edge.lanes || []).map(lane => Number(lane.elevation) || 0);
        return elevations.length ? Math.max(...elevations) : 0;
    }

    buildLandmarkPolygon(polygon, height, material, baseElevation = 0) {
        const mesh = this.polygonMesh(polygon.shape, material, height, baseElevation);
        if (mesh) { mesh.userData.landmark = true; this.staticRoot.add(mesh); }
    }

    buildStationFromPolygon(polygon) {
        const shape = polygon.shape || [];
        if (shape.length < 3) return;
        const railElevation = this.getRailElevation();
        const minX = Math.min(...shape.map(p => p[0])), maxX = Math.max(...shape.map(p => p[0]));
        const minY = Math.min(...shape.map(p => p[1])), maxY = Math.max(...shape.map(p => p[1]));
        const center = { x: (minX + maxX) / 2, y: (minY + maxY) / 2 };
        const railLanes = (this.geometry.edges || []).filter(edge => /rail/i.test(edge.id) || /rail/i.test(edge.type || ''))
            .flatMap(edge => edge.lanes || []);
        const closestOnSegment = (point, a, b) => {
            const dx = b[0] - a[0], dy = b[1] - a[1];
            const t = Math.max(0, Math.min(1, ((point.x - a[0]) * dx + (point.y - a[1]) * dy) / (dx * dx + dy * dy || 1)));
            const nearest = [a[0] + t * dx, a[1] + t * dy];
            return { nearest, distance: Math.hypot(nearest[0] - point.x, nearest[1] - point.y) };
        };
        const nearbySegments = railLanes.flatMap(lane => (lane.shape || []).slice(1).map((point, index) => {
            const previous = lane.shape[index];
            const midpoint = [(previous[0] + point[0]) / 2, (previous[1] + point[1]) / 2];
            const closest = closestOnSegment(center, previous, point);
            return { previous, point, midpoint, nearest: closest.nearest, distance: closest.distance };
        })).sort((a, b) => a.distance - b.distance);
        const trackSegment = nearbySegments[0];
        if (!trackSegment) { this.buildLandmarkPolygon(polygon, 0.3, this.staticMaterials.stationPlatform, railElevation - 0.3); return; }
        let tx = trackSegment.point[0] - trackSegment.previous[0], ty = trackSegment.point[1] - trackSegment.previous[1];
        const trackLength = Math.hypot(tx, ty) || 1;
        tx /= trackLength; ty /= trackLength;
        let nx = -ty, ny = tx;
        const project = (point, x, y) => point[0] * x + point[1] * y;
        const polygonT = shape.map(point => project(point, tx, ty));
        const polygonN = shape.map(point => project(point, nx, ny));
        const minT = Math.min(...polygonT), maxT = Math.max(...polygonT);
        const minN = Math.min(...polygonN), maxN = Math.max(...polygonN);
        // SUMO lane polylines often span across a station polygon without
        // having a vertex inside its bounds. Use the closest point on the live
        // rail geometry rather than requiring a lane vertex inside the box.
        const railCenterN = project(trackSegment.nearest, nx, ny);
        const alongCenter = (minT + maxT) / 2;
        const platformLength = (maxT - minT) * 0.78;
        const railClearance = 2.8;
        const platformSpecs = [
            { across: (minN + railCenterN - railClearance) / 2, width: railCenterN - railClearance - minN },
            { across: (railCenterN + railClearance + maxN) / 2, width: maxN - railCenterN - railClearance }
        ];
        const yaw = Math.atan2(tx, -ty);
        for (const platform of platformSpecs) {
            if (platform.width < 2.5 || platformLength < 4) continue;
            const x = tx * alongCenter + nx * platform.across;
            const y = ty * alongCenter + ny * platform.across;
            const group = new THREE.Group();
            group.position.copy(this.worldToSceneCoordinates(x, y, railElevation - 0.34));
            group.rotation.y = yaw;
            const deck = new THREE.Mesh(new THREE.BoxGeometry(platform.width, 0.28, platformLength), this.staticMaterials.stationPlatform);
            deck.userData.landmark = true; group.add(deck);
            const canopy = new THREE.Mesh(new THREE.BoxGeometry(Math.min(platform.width, 5), 0.24, platformLength * 0.58), this.staticMaterials.stationRoof);
            canopy.position.y = 3.15; canopy.userData.landmark = true;
            group.add(canopy);
            this.staticRoot.add(group);
        }
        // A compact elevated concourse makes the station recognizable inside
        // its supplied landmark footprint without inventing another location.
        const elevatedStationNode = (this.geometry.nodes || []).find(node => node.id === 'N_STATION_ELEVATED');
        const stationAnchor = elevatedStationNode || { x: center.x, y: center.y };
        const concourse = new THREE.Mesh(new THREE.BoxGeometry(Math.min(8, maxN - minN), 0.5, platformLength * 0.38),
            this.staticMaterials.stationRoof);
        concourse.position.copy(this.worldToSceneCoordinates(stationAnchor.x, stationAnchor.y, railElevation + 4.2));
        concourse.rotation.y = yaw;
        concourse.userData.landmark = true;
        this.staticRoot.add(concourse);
    }

    buildStadiumFromPolygon(polygon) {
        const shapeMesh = this.polygonMesh(polygon.shape, this.staticMaterials.stadium, 0.5);
        if (shapeMesh) this.staticRoot.add(shapeMesh);
        const center = this.polygonCentroid(polygon.shape);
        const xs = polygon.shape.map(p => p[0]), ys = polygon.shape.map(p => p[1]);
        const rx = (Math.max(...xs) - Math.min(...xs)) * 0.39;
        const rz = (Math.max(...ys) - Math.min(...ys)) * 0.39;
        const group = new THREE.Group();
        const worldCenter = this.worldToSceneCoordinates(center.x, center.y);
        const makeBowl = (outerX, outerZ, innerX, innerZ, bottom, top, material) => {
            const s = new THREE.Shape(); s.absellipse(0, 0, outerX, outerZ, 0, Math.PI * 2, false, 0);
            const hole = new THREE.Path(); hole.absellipse(0, 0, innerX, innerZ, 0, Math.PI * 2, true, 0); s.holes.push(hole);
            const m = new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: top - bottom, bevelEnabled: false, curveSegments: 48 }), material);
            m.rotation.x = -Math.PI / 2; m.position.set(worldCenter.x, bottom, worldCenter.z); m.castShadow = true; m.receiveShadow = true; group.add(m);
        };
        makeBowl(rx, rz, rx * 0.73, rz * 0.73, 1, 7, this.staticMaterials.roof);
        makeBowl(rx * 0.73, rz * 0.73, rx * 0.48, rz * 0.48, 0.6, 4.5,
            new THREE.MeshStandardMaterial({ color: this.theme === 'light' ? 0x8b633b : 0xb08b61, roughness: 0.9 }));
        const field = new THREE.Mesh(new THREE.CircleGeometry(Math.min(rx, rz) * 0.44, 48), this.staticMaterials.field);
        field.rotation.x = -Math.PI / 2; field.scale.set(rx / Math.min(rx, rz), rz / Math.min(rx, rz), 1);
        field.position.set(worldCenter.x, 0.62, worldCenter.z); field.receiveShadow = true; group.add(field);
        const rim = new THREE.Mesh(new THREE.TorusGeometry(Math.max(rx, rz) * 0.91, Math.max(0.8, Math.min(rx, rz) * 0.045), 8, 64), this.staticMaterials.roof);
        rim.rotation.x = Math.PI / 2; rim.scale.set(rx / Math.max(rx, rz), rz / Math.max(rx, rz), 1);
        rim.position.set(worldCenter.x, 9.4, worldCenter.z); group.add(rim);
        this.staticRoot.add(group);
        this.stadiumMeshGroup = group;
    }

    buildCoastFromPolygon(polygon, minX, maxX, minY, maxY) {
        const points = polygon.shape || [];
        if (points.length < 3) return;
        // poly_beach is authored in SUMO world coordinates and uses the same
        // +X=east transform as the roads. Split its actual slanted footprint
        // into adjacent sand and sea bands; avoid axis-aligned clipping so the
        // coastline follows the source geography instead of forming a block.
        const sides = points.map((point, index) => ({ a: point, b: points[(index + 1) % points.length] }))
            .sort((left, right) => Math.hypot(right.b[0] - right.a[0], right.b[1] - right.a[1]) -
                Math.hypot(left.b[0] - left.a[0], left.b[1] - left.a[1]));
        const longSides = sides.slice(0, 2);
        if (longSides.length < 2) return;
        const meanX = side => (side.a[0] + side.b[0]) / 2;
        const westSide = longSides.reduce((west, side) => meanX(side) < meanX(west) ? side : west);
        const eastSide = longSides.find(side => side !== westSide);
        const northSouth = side => [side.a, side.b].sort((a, b) => b[1] - a[1]);
        const [westNorth, westSouth] = northSouth(westSide);
        const [eastNorth, eastSouth] = northSouth(eastSide);
        const interpolate = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
        const across = (t, fraction) => interpolate(interpolate(westNorth, westSouth, t),
            interpolate(eastNorth, eastSouth, t), fraction);
        const band = (start, end) => [across(0, start), across(0, end), across(1, end), across(1, start)];
        const coastWidth = Math.min(
            Math.hypot(eastNorth[0] - westNorth[0], eastNorth[1] - westNorth[1]),
            Math.hypot(eastSouth[0] - westSouth[0], eastSouth[1] - westSouth[1])
        );
        if (!Number.isFinite(coastWidth) || coastWidth < 24) return;

        // Keep a modest setback from the western edge beside the coastal road.
        // Give sand and water substantial, visible adjacent widths, while the
        // two remain bounded by the real coast polygon.
        const sandStart = Math.min(0.12, 16 / coastWidth);
        const sandEnd = 0.56;
        const sand = this.polygonMesh(band(sandStart, sandEnd), this.staticMaterials.beach, 0.05, -0.08);
        if (sand) { sand.userData.coastLayer = 'sand'; this.staticRoot.add(sand); }
        const water = this.polygonMesh(band(sandEnd, 1), this.staticMaterials.water, 0.025, -0.12);
        if (water) {
            water.userData.coastLayer = 'sea';
            this.staticRoot.add(water);
            this.waterMesh = water;
        }
        const labelPoint = across(0.5, (sandEnd + 1) / 2);
        this.coastLabelPosition = { x: labelPoint[0], y: labelPoint[1] };
    }

    buildPedestrianPath(lane) {
        const shape = lane.shape || [];
        if (shape.length < 2) return;
        const geometry3d = lane.shape_3d || [];
        const isVerticalConnector = geometry3d.length > 1 &&
            Math.hypot(geometry3d.at(-1)[0] - geometry3d[0][0], geometry3d.at(-1)[1] - geometry3d[0][1]) < 0.5 &&
            Math.abs(geometry3d.at(-1)[2] - geometry3d[0][2]) > 1;
        if (isVerticalConnector) {
            const endpoints = [geometry3d[0], geometry3d[geometry3d.length - 1]]
                .map(point => point.map(value => Number(value).toFixed(1)).join(','))
                .sort();
            const connectorKey = endpoints.join('|');
            if (this.renderedPedestrianConnectors.has(connectorKey)) return;
            this.renderedPedestrianConnectors.add(connectorKey);
        }
        let mesh;
        if (isVerticalConnector) {
            const points = geometry3d.map(p => this.worldToSceneCoordinates(p[0], p[1], p[2]));
            const curve = new THREE.CatmullRomCurve3(points);
            mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(8, points.length * 4), 0.72, 6, false),
                new THREE.MeshStandardMaterial({ color: this.theme === 'light' ? 0xa69c88 : 0xc6b99f, roughness: 0.9 }));
        } else {
            const material = this.staticMaterials.pedestrianPath;
            mesh = this.createRibbonMesh(shape, Math.max(1.5, Math.min(Number(lane.width) || 2.4, 4.2)),
                (Number(lane.elevation) || 0) + 0.08, material, 0.08);
        }
        if (!mesh) return;
        mesh.userData.layer = 'pedestrianPaths';
        mesh.userData.networkEdgeId = lane.id;
        this.staticRoot.add(mesh);
    }

    addStadiumAccessMarkers() {
        const nodes = (this.geometry.nodes || []).filter(node => /^N_STAD_(WEST|EAST|SOUTH)_GATE$/.test(node.id));
        const edgeList = this.geometry.edges || [];
        for (const node of nodes) {
            const side = node.id.match(/_(WEST|EAST|SOUTH)_/)[1];
            const connected = edgeList.filter(edge => edge.from === node.id || edge.to === node.id);
            const lane = connected.flatMap(edge => edge.lanes || []).find(item => item.shape?.length > 1);
            const shape = lane?.shape || [];
            const tangent = shape.length > 1
                ? [shape.at(-1)[0] - shape[0][0], shape.at(-1)[1] - shape[0][1]] : [1, 0];
            const heading = Math.atan2(tangent[0], -tangent[1]);
            const access = new THREE.Group();
            access.position.copy(this.worldToSceneCoordinates(node.x, node.y, 0.12));
            access.rotation.y = heading;
            access.userData.junctionId = node.id;
            const postGeometry = new THREE.BoxGeometry(0.65, 3.8, 0.65);
            for (const x of [-3.4, 3.4]) {
                const post = new THREE.Mesh(postGeometry, this.staticMaterials.accessMarker);
                post.position.set(x, 1.9, 0);
                access.add(post);
            }
            const lintel = new THREE.Mesh(new THREE.BoxGeometry(7.4, 0.55, 0.72), this.staticMaterials.accessMarker);
            lintel.position.y = 3.95;
            access.add(lintel);
            const ring = new THREE.Mesh(new THREE.TorusGeometry(2.1, 0.24, 6, 18), this.staticMaterials.accessMarker);
            ring.rotation.x = Math.PI / 2;
            ring.position.y = 0.22;
            access.add(ring);
            this.staticRoot.add(access);
            const vehicleAccess = connected.some(edge => (edge.lanes || []).some(item => item.allow?.includes('passenger')));
            const caption = vehicleAccess && (side === 'SOUTH' || side === 'WEST') ? `${side} VEHICLE ENTRY / EXIT`
                : side === 'WEST' ? 'STADIUM WEST ENTRY' : side === 'EAST' ? 'STADIUM EAST ACCESS' : 'STADIUM ACCESS';
            this.addMapLabelAtWorld(caption, node.x, node.y, 5.2, 0xe9d39c);
        }
    }

    buildStationAccessLabel() {
        const edge = (this.geometry.edges || []).find(item => item.id === 'E_PED_STATION_STAD');
        const lane = edge?.lanes?.find(item => item.allow?.includes('pedestrian') && item.shape?.length > 1);
        if (!lane) return;
        const point = this.samplePolyline(lane.shape, 0.5);
        this.addMapLabelAtWorld('PEDESTRIAN STATION ACCESS', point[0], point[1], 2.2, 0xdcc9a3);
    }

    addPolyline(points, width, elevation, material) {
        if (points.length < 2) return;
        for (let i = 1; i < points.length; i++) {
            const a = points[i - 1], b = points[i];
            const dx = b[0] - a[0], dy = b[1] - a[1], len = Math.hypot(dx, dy);
            if (!len) continue;
            const mesh = new THREE.Mesh(sharedUnitBoxGeometry, material);
            mesh.position.copy(this.worldToSceneCoordinates((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, elevation));
            mesh.scale.set(width, 0.08, len);
            mesh.rotation.y = Math.atan2(dx, dy);
            this.staticRoot.add(mesh);
        }
    }

    addLaneSeparators(lanes) {
        const sorted = [...lanes].sort((a, b) => String(a.id).localeCompare(String(b.id)));
        const roadTop = Math.max(...sorted.map(lane => Math.max(0, Number(lane.elevation) || 0) + 0.24));
        const boundary = (lane, side) => {
            const shape = lane.shape || [];
            return shape.map((point, index) => {
                const before = shape[Math.max(0, index - 1)], after = shape[Math.min(shape.length - 1, index + 1)];
                const dx = after[0] - before[0], dy = after[1] - before[1], length = Math.hypot(dx, dy) || 1;
                const offset = ((Number(lane.width) || 3.2) + 0.1) / 2 * side;
                return [point[0] - dy / length * offset, point[1] + dx / length * offset];
            });
        };
        if (sorted.length) {
            const firstSides = sorted.length === 1 ? [-1, 1] : [-1];
            firstSides.forEach(side => this.addDashedLine(boundary(sorted[0], side), 0.17, roadTop + 0.035,
                this.staticMaterials.laneMark, 3.4, 3.1));
            if (sorted.length > 1) this.addDashedLine(boundary(sorted[sorted.length - 1], 1), 0.17, roadTop + 0.035,
                this.staticMaterials.laneMark, 3.4, 3.1);
        }
        for (let laneIndex = 0; laneIndex < sorted.length - 1; laneIndex++) {
            const a = sorted[laneIndex].shape, b = sorted[laneIndex + 1].shape;
            const samples = Math.max(a.length, b.length) * 4;
            const points = [];
            for (let i = 0; i < samples; i++) {
                const t = i / Math.max(1, samples - 1);
                const pa = this.samplePolyline(a, t), pb = this.samplePolyline(b, t);
                points.push([(pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2]);
            }
            this.addDashedLine(points, 0.18, roadTop + 0.04, this.staticMaterials.laneMark, 2.7, 2.4);
        }
    }

    samplePolyline(points, t) {
        const lengths = []; let total = 0;
        for (let i = 1; i < points.length; i++) { const d = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]); lengths.push(d); total += d; }
        let distance = t * total;
        for (let i = 0; i < lengths.length; i++) {
            if (distance <= lengths[i]) { const f = lengths[i] ? distance / lengths[i] : 0; return [points[i][0] + (points[i + 1][0] - points[i][0]) * f, points[i][1] + (points[i + 1][1] - points[i][1]) * f]; }
            distance -= lengths[i];
        }
        return points[points.length - 1];
    }

    pointAlongPolyline(points, distance) {
        if (!points?.length) return null;
        if (points.length === 1) return { point: points[0].slice(0, 2), tangent: [0, 1], totalLength: 0 };
        const lengths = [];
        let totalLength = 0;
        for (let i = 1; i < points.length; i++) {
            const length = Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
            lengths.push(length); totalLength += length;
        }
        let remaining = Math.max(0, Math.min(totalLength, Number(distance) || 0));
        for (let i = 0; i < lengths.length; i++) {
            if (remaining <= lengths[i] || i === lengths.length - 1) {
                const length = lengths[i] || 1;
                const t = Math.max(0, Math.min(1, remaining / length));
                const a = points[i], b = points[i + 1];
                return {
                    point: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t],
                    tangent: [(b[0] - a[0]) / length, (b[1] - a[1]) / length],
                    totalLength
                };
            }
            remaining -= lengths[i];
        }
        return { point: points[points.length - 1].slice(0, 2), tangent: [0, 1], totalLength };
    }

    addDashedLine(points, width, elevation, material, dashLength, gapLength) {
        let distanceToDash = 0, drawing = true;
        const dashes = [];
        for (let i = 1; i < points.length; i++) {
            const a = points[i - 1], b = points[i];
            const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
            if (!length) continue;
            let cursor = 0;
            while (cursor < length) {
                const segmentLength = drawing ? dashLength : gapLength;
                const step = Math.min(segmentLength - distanceToDash, length - cursor);
                if (drawing && step > 0.15) {
                    const t0 = cursor / length, t1 = (cursor + step) / length;
                    const start = [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0];
                    const end = [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1];
                    dashes.push({ x: (start[0] + end[0]) / 2, y: (start[1] + end[1]) / 2,
                        length: step, angle: Math.atan2(end[0] - start[0], end[1] - start[1]) });
                }
                cursor += step; distanceToDash += step;
                if (distanceToDash >= segmentLength - 1e-6) { distanceToDash = 0; drawing = !drawing; }
            }
        }
        if (!dashes.length) return;
        const batch = new THREE.InstancedMesh(sharedUnitBoxGeometry, material, dashes.length);
        const transform = new THREE.Object3D();
        dashes.forEach((dash, index) => {
            transform.position.copy(this.worldToSceneCoordinates(dash.x, dash.y, elevation));
            transform.rotation.set(0, dash.angle, 0);
            transform.scale.set(width, 0.08, dash.length); transform.updateMatrix();
            batch.setMatrixAt(index, transform.matrix);
        });
        batch.instanceMatrix.needsUpdate = true; this.staticRoot.add(batch);
    }

    addRailTrack(shape, elevation, width) {
        if (shape.length < 2) return;
        const railMaterial = this.staticMaterials.rail;
        const halfGap = Math.max(0.5, Math.min(width * 0.23, 0.9));
        for (const side of [-1, 1]) {
            const railPoints = [];
            for (let i = 0; i < shape.length; i++) {
                const p = shape[i], before = shape[Math.max(0, i - 1)], after = shape[Math.min(shape.length - 1, i + 1)];
                const dx = after[0] - before[0], dy = after[1] - before[1], len = Math.hypot(dx, dy) || 1;
                railPoints.push([p[0] - dy / len * halfGap * side, p[1] + dx / len * halfGap * side]);
            }
            this.addPolyline(railPoints, 0.24, elevation, railMaterial);
        }
        const length = shape.reduce((sum, p, i) => i ? sum + Math.hypot(p[0] - shape[i - 1][0], p[1] - shape[i - 1][1]) : 0, 0);
        const sleepers = Math.floor(length / 5.5);
        const sleeperBatch = sleepers ? new THREE.InstancedMesh(sharedUnitBoxGeometry, this.staticMaterials.railBed, sleepers) : null;
        const transform = new THREE.Object3D();
        for (let i = 0; i < sleepers; i++) {
            const p = this.samplePolyline(shape, (i + 0.5) / sleepers);
            const a = this.samplePolyline(shape, Math.max(0, (i + 0.5) / sleepers - 0.002));
            const b = this.samplePolyline(shape, Math.min(1, (i + 0.5) / sleepers + 0.002));
            const angle = Math.atan2(b[0] - a[0], b[1] - a[1]);
            transform.position.copy(this.worldToSceneCoordinates(p[0], p[1], elevation - 0.1)); transform.rotation.set(0, angle, 0);
            transform.scale.set(width * 0.86, 0.16, 0.28); transform.updateMatrix();
            sleeperBatch?.setMatrixAt(i, transform.matrix);
        }
        if (sleeperBatch) { sleeperBatch.instanceMatrix.needsUpdate = true; this.staticRoot.add(sleeperBatch); }
    }

    buildJunctionSurfaces() {
        for (const node of this.geometry.nodes || []) {
            if (!node.shape || node.shape.length < 3) continue;
            // Signalized nodes need a paved surface too. Omitting them left a
            // visible ground hole where several SUMO lane ribbons terminate.
            // Match the surface top to the connected road decks so the real
            // SUMO junction polygon closes those seams without covering roads.
            const connectedRoadLevels = (this.geometry.edges || [])
                .filter(edge => edge.from === node.id || edge.to === node.id)
                .flatMap(edge => (edge.lanes || []).filter(lane =>
                    lane.shape?.length >= 2 && !lane.allow?.includes('pedestrian') &&
                    !lane.allow?.some(vehicleClass => /^rail/.test(vehicleClass)))
                    .map(lane => Number(lane.elevation) || 0));
            const roadLevel = connectedRoadLevels.length
                ? connectedRoadLevels.reduce((sum, value) => sum + value, 0) / connectedRoadLevels.length : 0;
            const mesh = this.polygonMesh(node.shape, this.staticMaterials.junction, 0.34, roadLevel + 0.20);
            if (!mesh) continue;
            mesh.userData.junctionId = node.id;
            this.staticRoot.add(mesh);
        }
    }

    createUrbanBuildings(extent) {
        // No surveyed building footprints are exported by this SUMO network.
        // Add a small, stable sample of contextual masses in road-defined open
        // blocks; they are deliberately sparse and are not presented as GIS data.
        const bounds = this.geometry.bbox || {};
        const minX = Number(bounds.min_x ?? 0), maxX = Number(bounds.max_x ?? 0);
        const minY = Number(bounds.min_y ?? 0), maxY = Number(bounds.max_y ?? 0);
        const marginX = (maxX - minX) * 0.035, marginY = (maxY - minY) * 0.035;
        const polygons = this.geometry.polygons || [];
        const nodes = this.geometry.nodes || [];
        const sensitiveAreas = [
            ...polygons.filter(p => p.id === 'poly_stadium' || p.id === 'poly_station_elevated')
                .map(p => ({ center: this.polygonCentroid(p.shape), radius: p.id === 'poly_stadium' ? 62 : 34 })),
            ...nodes.filter(n => /^N_STAD_(WEST|EAST|SOUTH)_GATE$/.test(n.id))
                .map(n => ({ center: { x: n.x, y: n.y }, radius: 20 }))
        ];
        const segments = [];
        for (const edge of this.geometry.edges || []) {
            const rail = (edge.lanes || []).some(lane => lane.allow?.some(c => /^rail/.test(c))) || /rail/i.test(edge.id) || /rail/i.test(edge.type || '');
            for (const lane of edge.lanes || []) {
                const shape = lane.shape || [];
                for (let i = 1; i < shape.length; i++) {
                    const a = shape[i - 1], b = shape[i];
                    segments.push({ a, b, width: Number(lane.width) || 3.2, rail,
                        angle: Math.atan2(b[1] - a[1], b[0] - a[0]) });
                }
            }
        }
        const pointSegmentDistance = (x, y, a, b) => {
            const dx = b[0] - a[0], dy = b[1] - a[1];
            const t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / (dx * dx + dy * dy || 1)));
            return Math.hypot(x - (a[0] + t * dx), y - (a[1] + t * dy));
        };
        const inside = (x, y, shape) => {
            if (!shape?.length) return false;
            let result = false;
            for (let i = 0, j = shape.length - 1; i < shape.length; j = i++) {
                const [xi, yi] = shape[i], [xj, yj] = shape[j];
                if (((yi > y) !== (yj > y)) && x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-9) + xi) result = !result;
            }
            return result;
        };
        const radicalInverse = (value, base) => {
            let fraction = 1 / base, result = 0;
            while (value > 0) { result += (value % base) * fraction; value = Math.floor(value / base); fraction /= base; }
            return result;
        };
        const hash = value => { const n = Math.sin(value * 91.731 + 12.337) * 43758.5453; return n - Math.floor(n); };
        const targetCount = Math.max(10, Math.min(22, Math.round(extent / 42)));
        const candidates = [];
        for (let sample = 1; sample <= 900 && candidates.length < targetCount; sample++) {
            const x = minX + marginX + radicalInverse(sample, 2) * Math.max(1, maxX - minX - 2 * marginX);
            const y = minY + marginY + radicalInverse(sample, 3) * Math.max(1, maxY - minY - 2 * marginY);
            const seed = sample * 7.91 + x * 0.017 + y * 0.031;
            const w = 19 + hash(seed) * 18, d = 16 + hash(seed + 1) * 15;
            const clearanceNeeded = Math.max(w, d) * 0.55 + 8;
            if (polygons.some(p => inside(x, y, p.shape)) || nodes.some(n => n.type !== 'traffic_light' && inside(x, y, n.shape))) continue;
            if (sensitiveAreas.some(area => Math.hypot(x - area.center.x, y - area.center.y) < area.radius + clearanceNeeded)) continue;

            let minimumClearance = Infinity;
            const nearbyAngles = [];
            let railClearance = Infinity;
            for (const segment of segments) {
                const distance = pointSegmentDistance(x, y, segment.a, segment.b) - segment.width / 2;
                if (segment.rail) railClearance = Math.min(railClearance, distance);
                else {
                    minimumClearance = Math.min(minimumClearance, distance);
                    if (distance < 72) nearbyAngles.push(segment.angle);
                }
            }
            if (minimumClearance < clearanceNeeded || railClearance < clearanceNeeded + 4) continue;
            // A candidate must sit near two differently oriented actual road
            // segments, so isolated edge-of-map areas do not become fake blocks.
            let boundedBlock = false;
            for (let i = 0; i < nearbyAngles.length && !boundedBlock; i++) {
                for (let j = i + 1; j < nearbyAngles.length; j++) {
                    let delta = Math.abs(nearbyAngles[i] - nearbyAngles[j]) % Math.PI;
                    delta = Math.min(delta, Math.PI - delta);
                    if (delta > 0.38) { boundedBlock = true; break; }
                }
            }
            if (!boundedBlock) continue;
            if (candidates.some(other => Math.hypot(x - other.x, y - other.y) < Math.max(36, (w + d) * 0.55))) continue;

            const heightRoll = hash(seed + 2);
            const h = heightRoll < 0.70 ? 4.5 + hash(seed + 3) * 4.2
                : heightRoll < 0.95 ? 8.8 + hash(seed + 3) * 5.5
                    : 14.5 + hash(seed + 3) * 4.5;
            candidates.push({ x, y, w, d, h, shape: hash(seed + 4) < 0.18 ? 'L' : 'block', shade: hash(seed + 5) });
        }
        if (!candidates.length) return;

        const darkColors = [0x293740, 0x34424a, 0x3b474e, 0x303b43];
        const lightColors = [0xa9b2b0, 0xbab7aa, 0x9fa9aa, 0xb1b5b0];
        const archetypes = [
            { name: 'block', geometry: sharedUrbanBlockGeometry, rotation: 0 },
            { name: 'L', geometry: sharedUrbanLGeometry, rotation: Math.PI / 2 }
        ];
        const dummy = new THREE.Object3D(), tint = new THREE.Color();
        for (const archetype of archetypes) {
            const members = candidates.filter(item => item.shape === archetype.name);
            if (!members.length) continue;
            const batch = new THREE.InstancedMesh(archetype.geometry, this.staticMaterials.building, members.length);
            batch.castShadow = true; batch.receiveShadow = true; batch.userData.layer = 'buildings';
            batch.userData.shades = members.map(building => building.shade);
            members.forEach((building, index) => {
                dummy.position.copy(this.worldToSceneCoordinates(building.x, building.y, archetype.name === 'L' ? building.h : building.h / 2));
                dummy.rotation.set(archetype.rotation, 0, 0);
                dummy.scale.set(building.w, archetype.name === 'L' ? building.d : building.h, archetype.name === 'L' ? building.h : building.d);
                dummy.updateMatrix(); batch.setMatrixAt(index, dummy.matrix);
                const palette = this.theme === 'light' ? lightColors : darkColors;
                tint.setHex(palette[Math.min(palette.length - 1, Math.floor(building.shade * palette.length))]);
                batch.setColorAt(index, tint);
            });
            batch.instanceMatrix.needsUpdate = true;
            if (batch.instanceColor) batch.instanceColor.needsUpdate = true;
            this.staticRoot.add(batch);
            this.cityBuildingMesh = batch;
        }
    }

    buildNetworkBusStops() {
        const edges = this.geometry.edges || [];
        const laneById = new Map(edges.flatMap(edge => edge.lanes || []).map(lane => [lane.id, lane]));
        const stopPositions = [];
        for (const stop of this.geometry.bus_stops || []) {
            const roadLane = laneById.get(stop.lane);
            if (!roadLane?.shape?.length) continue;
            const fromDistance = Number(stop.startPos) || 0;
            const toDistance = Number(stop.endPos) || fromDistance;
            const centerOnRoad = this.pointAlongPolyline(roadLane.shape, (fromDistance + toDistance) / 2);
            if (!centerOnRoad) continue;
            const edge = edges.find(item => item.lanes?.some(lane => lane.id === stop.lane));
            const sidewalk = (edge?.lanes || []).find(lane => lane.allow?.includes('pedestrian') && !lane.allow?.includes('passenger') && lane.shape?.length > 1);
            let position = centerOnRoad.point;
            let tangent = centerOnRoad.tangent;
            if (sidewalk) {
                const fraction = centerOnRoad.totalLength > 0
                    ? ((fromDistance + toDistance) / 2) / centerOnRoad.totalLength : 0.5;
                const walkLength = this.pointAlongPolyline(sidewalk.shape, 0).totalLength;
                const walkHeading = this.pointAlongPolyline(sidewalk.shape, Math.max(0, Math.min(1, fraction)) * walkLength);
                position = walkHeading?.point || this.samplePolyline(sidewalk.shape, Math.max(0, Math.min(1, fraction)));
                if (walkHeading) tangent = walkHeading.tangent;
            } else {
                const normal = [-tangent[1], tangent[0]];
                const offset = (Number(roadLane.width) || 3.2) / 2 + 2.1;
                position = [position[0] + normal[0] * offset, position[1] + normal[1] * offset];
            }
            const stopLength = Math.max(8, Math.min(14, Math.max(0, toDistance - fromDistance) * 0.42));
            const group = new THREE.Group();
            group.position.copy(this.worldToSceneCoordinates(position[0], position[1]));
            group.rotation.y = Math.atan2(tangent[0], -tangent[1]);
            const curb = new THREE.Mesh(new THREE.BoxGeometry(3.8, 0.18, stopLength + 2), this.staticMaterials.curb);
            curb.position.y = 0.09; group.add(curb);
            const roof = new THREE.Mesh(new THREE.BoxGeometry(3.0, 0.2, stopLength * 0.62), this.staticMaterials.roof);
            roof.position.y = 2.55; group.add(roof);
            const postGeo = new THREE.BoxGeometry(0.12, 2.45, 0.12);
            for (const x of [-1.3, 1.3]) for (const z of [-stopLength * 0.25, stopLength * 0.25]) {
                const post = new THREE.Mesh(postGeo, this.staticMaterials.curb);
                post.position.set(x, 1.22, z); group.add(post);
            }
            const signPost = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 2.5, 6), this.staticMaterials.curb);
            signPost.position.set(-2.1, 1.25, 0); group.add(signPost);
            const sign = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.72, 0.12), this.staticMaterials.stationRoof);
            sign.position.set(-2.1, 2.4, 0); group.add(sign);
            group.userData.entityId = stop.id; group.userData.type = 'BusStop';
            this.staticRoot.add(group); this.busStopMeshes.push(group);
            stopPositions.push({ ...stop, x: position[0], y: position[1] });
        }
        const station = (this.geometry.nodes || []).find(node => node.id === 'N_STATION_GROUND');
        if (station && stopPositions.length) {
            this.nearestStationBusStop = stopPositions.reduce((best, stop) =>
                Math.hypot(stop.x - station.x, stop.y - station.y) < Math.hypot(best.x - station.x, best.y - station.y) ? stop : best);
            this.addMapLabelAtWorld('BUS STOP / PICKUP', this.nearestStationBusStop.x, this.nearestStationBusStop.y, 4.2, 0xf0cf8a);
        }
    }

    addMapLabel(text, x, y, z, tint = 0xffffff) {
        if (typeof document === 'undefined') return;
        const canvas = document.createElement('canvas'); canvas.width = 512; canvas.height = 96;
        const ctx = canvas.getContext('2d'); if (!ctx) return;
        ctx.font = '600 30px Segoe UI, Arial'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillStyle = '#e5edf0'; ctx.shadowColor = '#08131d'; ctx.shadowBlur = 8;
        ctx.fillText(text, 256, 48, 490);
        const texture = new THREE.CanvasTexture(canvas); if (THREE.sRGBEncoding !== undefined) texture.encoding = THREE.sRGBEncoding;
        const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
        sprite.userData.landmark = true;
        sprite.position.set(x, y, z); sprite.scale.set(Math.max(28, text.length * 1.9), Math.max(5, text.length * 0.32), 1);
        sprite.userData.type = 'MapLabel'; sprite.userData.label = text; sprite.userData.tint = tint;
        this.labelSprites.push(sprite); this.paintLabelSprite(sprite); this.staticRoot.add(sprite);
    }

    addMapLabelAtWorld(text, sumoX, sumoY, elevation = 0, tint = 0xffffff) {
        const position = this.worldToSceneCoordinates(sumoX, sumoY, elevation);
        this.addMapLabel(text, position.x, position.y, position.z, tint);
    }

    buildSignalPoles() {
        const roadEdges = (this.geometry.edges || []).filter(edge =>
            !/rail/i.test(edge.id) && !/rail/i.test(edge.type || '') &&
            (edge.lanes || []).some(lane => lane.shape?.length > 1 &&
                lane.allow?.some(vehicleClass => ['passenger', 'taxi', 'bus', 'motorcycle', 'emergency'].includes(vehicleClass))));
        const signalNodes = (this.geometry.nodes || []).filter(node =>
            ['traffic_light', 'traffic_light_unregulated'].includes(node.type));
        const makeHead = (parent, nodeId, approach) => {
            const laneSets = approach.edges.map(edge => ({
                edge,
                lanes: (edge.lanes || []).filter(lane => lane.shape?.length > 1 &&
                    lane.allow?.some(vehicleClass => ['passenger', 'taxi', 'bus', 'motorcycle', 'emergency'].includes(vehicleClass)))
            })).filter(item => item.lanes.length);
            const samples = laneSets.flatMap(item => item.lanes.map(lane => ({ lane, edge: item.edge,
                end: lane.shape[lane.shape.length - 1], width: Number(lane.width) || 3.2 })));
            if (!samples.length) return null;
            const txRaw = approach.tangent[0], tyRaw = approach.tangent[1];
            const length = Math.hypot(txRaw, tyRaw) || 1;
            const tx = txRaw / length, ty = tyRaw / length;
            const endpoint = samples.reduce((sum, item) => [sum[0] + item.end[0], sum[1] + item.end[1]], [0, 0])
                .map(value => value / samples.length);
            const lead = Math.max(...samples.map(item => this.pointAlongPolyline(item.lane.shape, 0).totalLength));
            const anchor = this.pointAlongPolyline(approach.primaryLane.shape, Math.max(0, lead - 7));
            const center = anchor?.point || endpoint;
            const roadWidth = samples.reduce((sum, item) => sum + item.width, 0);
            // Place each signal on the roadside of its real incoming approach,
            // a short distance back from the junction stop line.
            const rightX = ty, rightY = -tx;
            const lateral = Math.min(6, Math.max(2.2, roadWidth / 2 + 0.8));
            const x = center[0] + rightX * lateral, y = center[1] + rightY * lateral;
            const elevation = Math.max(...samples.map(item => Number(item.lane.elevation) || 0));
            const headGroup = new THREE.Group();
            headGroup.position.copy(this.worldToSceneCoordinates(x, y, elevation));
            headGroup.rotation.y = Math.atan2(-tx, ty);
            const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.16, 4.0, 8), this.staticMaterials.curb);
            pole.position.y = 2.0; pole.castShadow = true; headGroup.add(pole);
            const housingMat = new THREE.MeshStandardMaterial({ color: 0x171d22, roughness: 0.65 });
            const housing = new THREE.Mesh(new THREE.BoxGeometry(0.58, 1.62, 0.48), housingMat);
            housing.position.set(0, 4.25, 0.24); headGroup.add(housing);
            const bulbs = {};
            for (const [name, yPosition, hex] of [['red', 4.78, 0xef4444], ['yellow', 4.25, 0xf59e0b], ['green', 3.72, 0x22c55e]]) {
                const material = new THREE.MeshStandardMaterial({ color: hex, emissive: hex, emissiveIntensity: 0.025 });
                const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.16, 8, 8), material);
                bulb.position.set(0, yPosition, 0.52); headGroup.add(bulb); bulbs[name] = bulb;
            }
            headGroup.userData.incomingEdges = laneSets.map(item => item.edge.id);
            headGroup.userData.bulbs = bulbs;
            headGroup.userData.type = 'TrafficSignalHead';
            parent.add(headGroup);
            return { incomingEdges: headGroup.userData.incomingEdges, bulbs };
        };

        for (const node of signalNodes) {
            const incoming = roadEdges.filter(edge => edge.to === node.id).map(edge => {
                const lanes = (edge.lanes || []).filter(lane => lane.shape?.length > 1 &&
                    lane.allow?.some(vehicleClass => ['passenger', 'taxi', 'bus', 'motorcycle', 'emergency'].includes(vehicleClass)));
                const lane = lanes[0];
                if (!lane) return null;
                const first = lane.shape[0], last = lane.shape[lane.shape.length - 1];
                const tangent = [last[0] - first[0], last[1] - first[1]];
                const norm = Math.hypot(tangent[0], tangent[1]) || 1;
                return { edge, lanes, primaryLane: lane, tangent: [tangent[0] / norm, tangent[1] / norm] };
            }).filter(Boolean);
            const approaches = [];
            for (const candidate of incoming) {
                const match = approaches.find(approach =>
                    approach.tangent[0] * candidate.tangent[0] + approach.tangent[1] * candidate.tangent[1] > 0.82);
                if (match) { match.edges.push(candidate.edge); match.candidates.push(candidate); }
                else approaches.push({ edges: [candidate.edge], candidates: [candidate], primaryLane: candidate.primaryLane, tangent: candidate.tangent });
            }
            const group = new THREE.Group();
            const heads = approaches.map(approach => makeHead(group, node.id, approach)).filter(Boolean);
            if (!heads.length) {
                const fallback = this.createSignalMesh(node.id, node);
                heads.push({ incomingEdges: [], bulbs: fallback.userData.bulbs });
                group.add(fallback);
            }
            group.userData = { entityId: node.id, junctionId: node.id, type: 'TrafficSignal', heads };
            this.signalMeshes.set(node.id, group);
            this.staticRoot.add(group);
        }
    }

    buildPedestrianCrossings() {
        const crossings = (this.geometry.crossings || []).filter(crossing => crossing.shape?.length > 1);
        const stripes = [];
        const spacing = 0.82, stripeDepth = 0.42;
        for (const crossing of crossings) {
            const info = this.pointAlongPolyline(crossing.shape, 0);
            if (!info || info.totalLength < 1.2) continue;
            const count = Math.max(1, Math.floor(info.totalLength / spacing));
            const width = Math.max(2.4, Math.min(6, Number(crossing.width) || 4));
            const used = (count - 1) * spacing;
            const start = (info.totalLength - used) / 2;
            for (let index = 0; index < count; index++) {
                const position = this.pointAlongPolyline(crossing.shape, start + index * spacing);
                if (!position) continue;
                const transform = new THREE.Object3D();
                // SUMO crossing geometry runs across the carriageway. Orient
                // each broad white bar along the carriageway and space bars
                // along the actual exported crossing line.
                transform.position.copy(this.worldToSceneCoordinates(position.point[0], position.point[1], 0.61));
                transform.rotation.y = Math.atan2(position.tangent[0], -position.tangent[1]);
                transform.scale.set(width, 1, stripeDepth);
                transform.updateMatrix();
                stripes.push(transform.matrix.clone());
            }
        }
        if (!stripes.length) return;
        const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 0.055, 1), this.staticMaterials.crosswalk, stripes.length);
        stripes.forEach((matrix, index) => mesh.setMatrixAt(index, matrix));
        mesh.instanceMatrix.needsUpdate = true;
        mesh.userData.layer = 'pedestrianCrossings';
        mesh.renderOrder = 3;
        this.staticRoot.add(mesh);
    }

    setTheme(theme) {
        this.theme = theme === 'light' ? 'light' : 'dark';
        const background = this.theme === 'light' ? 0xe8eef2 : 0x060913;
        this.baseRoadColor = this.theme === 'light' ? 0x59646d : 0x3a444c;
        if (this.scene) {
            this.scene.background?.setHex(background);
            if (this.scene.fog) this.scene.fog.color.setHex(background);
        }
        if (this.groundMesh) this.groundMesh.material.color.setHex(this.theme === 'light' ? 0xd9dedf : 0x111923);
        if (this.staticMaterials?.road) this.staticMaterials.road.color.setHex(this.baseRoadColor);
        for (const material of this.edgeMaterials.values()) material.color.setHex(this.baseRoadColor);
        if (this.staticMaterials?.junction) this.staticMaterials.junction.color.setHex(this.theme === 'light' ? 0x69737a : 0x323b43);
        if (this.staticMaterials?.roadEdge) this.staticMaterials.roadEdge.color.setHex(this.theme === 'light' ? 0x747e84 : 0x707c84);
        if (this.staticMaterials?.laneMark) this.staticMaterials.laneMark.color.setHex(this.theme === 'light' ? 0xf3f5f4 : 0xd3dbe0);
        if (this.staticMaterials?.pedestrianPath) this.staticMaterials.pedestrianPath.color.setHex(this.theme === 'light' ? 0x8f8068 : 0xb8aa8f);
        if (this.staticMaterials?.accessMarker) this.staticMaterials.accessMarker.color.setHex(this.theme === 'light' ? 0x80653b : 0xc3a66f);
        if (this.staticMaterials?.stationPlatform) this.staticMaterials.stationPlatform.color.setHex(this.theme === 'light' ? 0x858d8e : 0x82919a);
        if (this.staticMaterials?.stationRoof) this.staticMaterials.stationRoof.color.setHex(this.theme === 'light' ? 0x667176 : 0x647780);
        if (this.staticMaterials?.building && this.staticRoot) {
            const colors = this.theme === 'light' ? [0xa9b2b0,0xbab7aa,0x9fa9aa,0xb1b5b0] : [0x293740,0x34424a,0x3b474e,0x303b43];
            const color = new THREE.Color();
            for (const batch of this.staticRoot.children.filter(child => child.userData?.layer === 'buildings')) {
                const shades = batch.userData.shades || [];
                for (let i = 0; i < batch.count; i++) {
                    const paletteIndex = Math.min(colors.length - 1, Math.floor((shades[i] ?? (i / batch.count)) * colors.length));
                    batch.setColorAt(i, color.setHex(colors[paletteIndex]));
                }
                if (batch.instanceColor) batch.instanceColor.needsUpdate = true;
            }
        }
        for (const sprite of this.labelSprites) this.paintLabelSprite(sprite);
        if (this.state) this.updateRoadVisualization(this.state);
    }

    paintLabelSprite(sprite) {
        const canvas = sprite.material?.map?.image;
        const ctx = canvas?.getContext?.('2d');
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.font = '600 30px Segoe UI, Arial'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.lineWidth = 7; ctx.strokeStyle = this.theme === 'light' ? 'rgba(245,248,247,.94)' : 'rgba(5,13,20,.94)';
        ctx.fillStyle = this.theme === 'light' ? '#263941' : `#${Number(sprite.userData.tint || 0xe5edf0).toString(16).padStart(6, '0')}`;
        ctx.shadowColor = this.theme === 'light' ? '#ffffff' : '#08131d'; ctx.shadowBlur = 8;
        ctx.strokeText(sprite.userData.label, 256, 48, 490); ctx.fillText(sprite.userData.label, 256, 48, 490);
        sprite.material.map.needsUpdate = true;
    }

    createRibbonMesh(points, width, elev, material, thickness = 0.18) {
        if (points.length < 2) return null;
        const cacheKey = `${width}|${elev}|${thickness}|${points.map(point => `${point[0]},${point[1]}`).join(';')}`;
        let geo = sharedRibbonGeometry.get(cacheKey);
        if (geo) return new THREE.Mesh(geo, material);
        const halfW = width / 2;
        const positions = [];
        const indices = [];

        for (let i = 0; i < points.length; i++) {
            const p = points[i];
            let dir = new THREE.Vector2(1, 0);

            if (i < points.length - 1) {
                dir = new THREE.Vector2(points[i + 1][0] - p[0], points[i + 1][1] - p[1]).normalize();
            } else {
                dir = new THREE.Vector2(p[0] - points[i - 1][0], p[1] - points[i - 1][1]).normalize();
            }
            const normal = new THREE.Vector2(-dir.y, dir.x);

            const pLeft = this.worldToSceneCoordinates(p[0] + normal.x * halfW, p[1] + normal.y * halfW, elev);
            const pRight = this.worldToSceneCoordinates(p[0] - normal.x * halfW, p[1] - normal.y * halfW, elev);

            positions.push(pLeft.x, pLeft.y, pLeft.z);             // top left
            positions.push(pRight.x, pRight.y, pRight.z);           // top right
            positions.push(pLeft.x, pLeft.y - thickness, pLeft.z); // bottom left
            positions.push(pRight.x, pRight.y - thickness, pRight.z);// bottom right

            if (i < points.length - 1) {
                const base = i * 4, next = base + 4;
                indices.push(base, base + 1, next, base + 1, next + 1, next); // road deck
                indices.push(base + 2, next + 2, base + 3, base + 3, next + 2, next + 3); // underside
                indices.push(base, next, base + 2, next, next + 2, base + 2); // left fascia
                indices.push(base + 1, base + 3, next + 1, next + 1, base + 3, next + 3); // right fascia
            }
        }

        geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geo.setIndex(indices);
        geo.computeVertexNormals();
        sharedRibbonGeometry.set(cacheKey, geo);
        return new THREE.Mesh(geo, material);
    }

    update(state) {
        if (!state) return;
        this.state = state;
        this.updateRoadVisualization(state);
        const delta = this.clock.getDelta();
        this.animTime += delta;

        // Update only dynamic TraCI entities; static network geometry is built once.
        if (this.layers.vehicles && state.vehicles) {
            this.updateVehicles(state.vehicles);
        }

        // 3. Update Moving 3D Pedestrians
        if (this.layers.pedestrians && state.pedestrians) {
            this.updatePedestrians(state.pedestrians);
        }

        // 4. Update 3D Traffic Light Signals
        if (this.layers.signals && state.traffic_lights) {
            this.updateTrafficLights(state.traffic_lights);
        }

        // 5. Follow Cam Update (Supports Vehicle, Pedestrian, and Train)
        if (this.followTarget && this.controls) {
            const targetPos = this.followTarget.position;
            if (this.followType === 'train') {
                this.camera.position.lerp(new THREE.Vector3(targetPos.x - 45, targetPos.y + 24, targetPos.z + 45), 0.08);
            } else if (this.followType === 'vehicle') {
                this.camera.position.lerp(new THREE.Vector3(targetPos.x - 25, targetPos.y + 16, targetPos.z + 25), 0.08);
            } else {
                this.camera.position.lerp(new THREE.Vector3(targetPos.x - 12, targetPos.y + 8, targetPos.z + 12), 0.08);
            }
            this.controls.target.lerp(targetPos, 0.1);
        }
    }

    setOverlaySelection(selectedEdges = [], actionEdges = []) {
        this.selectedEdges = new Set(selectedEdges);
        this.actionEdges = new Set(actionEdges);
        if (this.state) this.updateRoadVisualization(this.state);
    }

    setOverlays({ selectedEdges = [], actionEdges = [], vipEdges = [], constructionEdges = [] } = {}) {
        this.selectedEdges = new Set(selectedEdges);
        this.actionEdges = new Set(actionEdges);
        this.vipEdges = new Set(vipEdges);
        this.constructionEdges = new Set(constructionEdges);
        if (this.state) this.updateRoadVisualization(this.state);
    }

    setReroutedRoute(edgeIds = []) {
        this.reroutedEdges = new Set(edgeIds.filter(edgeId => this.roadMeshes.has(edgeId)));
        if (this.state) this.updateRoadVisualization(this.state);
    }

    setCorridors(corridors = []) {
        this.corridors = Array.isArray(corridors) ? corridors : [];
        if (this.staticRoot) this.buildCorridorLabels();
    }

    buildCorridorLabels() {
        if (!this.staticRoot || !this.geometry) return;
        for (const sprite of this.staticRoot.children.filter(child => child.userData?.corridorLabel)) {
            this.staticRoot.remove(sprite);
            sprite.material?.map?.dispose?.(); sprite.material?.dispose?.();
            const index = this.labelSprites.indexOf(sprite); if (index >= 0) this.labelSprites.splice(index, 1);
        }
        for (const corridor of this.corridors) {
            const candidates = (corridor.edges || []).map(id => (this.geometry.edges || []).find(edge => edge.id === id))
                .filter(edge => edge?.lanes?.some(lane => lane.shape?.length > 1));
            if (!candidates.length) continue;
            if (corridor.id === 'Triplicane High Road') {
                for (const [edgeId, label] of [['E_CENTRAL_1', 'BELLS ROAD'], ['E_SOUTH_1', 'TRIPLICANE HIGH ROAD']]) {
                    if (!(corridor.edges || []).includes(edgeId)) continue;
                    const namedEdge = candidates.find(item => item.id === edgeId);
                    const lane = namedEdge?.lanes?.find(item => item.shape?.length > 1 && !item.allow?.includes('pedestrian'));
                    if (!lane) continue;
                    const point = this.samplePolyline(lane.shape, edgeId === 'E_CENTRAL_1' ? 0.76 : 0.5);
                    this.addMapLabelAtWorld(label, point[0], point[1], Math.max(3, Number(lane.elevation) || 0) + 4, 0xd8edf3);
                    this.labelSprites[this.labelSprites.length - 1].userData.corridorLabel = true;
                }
                continue;
            }
            const edge = candidates.reduce((best, current) => {
                const length = item => (item.lanes.find(lane => lane.shape?.length > 1)?.shape || []).reduce((sum, point, i, points) =>
                    i ? sum + Math.hypot(point[0] - points[i - 1][0], point[1] - points[i - 1][1]) : 0, 0);
                return length(current) > length(best) ? current : best;
            });
            const lane = edge.lanes.find(item => item.shape?.length > 1 && !item.allow?.includes('pedestrian')) || edge.lanes[0];
            const point = this.samplePolyline(lane.shape, 0.5);
            const label = String(corridor.id || '').toUpperCase();
            this.addMapLabelAtWorld(label, point[0], point[1], Math.max(3, Number(lane.elevation) || 0) + 3.3, 0xd8edf3);
            this.labelSprites[this.labelSprites.length - 1].userData.corridorLabel = true;
        }
    }

    updateMapLabelVisibility() {
        if (!this.labelSprites.length || !this.camera) return;
        const extent = Math.max(this.networkSpan.x, this.networkSpan.y);
        for (const sprite of this.labelSprites) {
            const detailLimit = sprite.userData.corridorLabel ? extent * 2.1 : extent * 1.85;
            sprite.visible = this.camera.position.distanceTo(sprite.position) <= detailLimit;
        }
    }

    setLayer(layer, enabled) {
        if (!(layer in this.layers)) return;
        this.layers[layer] = enabled;
        if (layer === 'vehicles') this.vehicleMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (layer === 'pedestrians') this.pedestrianMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (layer === 'signals') this.signalMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (layer === 'buildings') {
            if (this.stadiumMeshGroup) this.stadiumMeshGroup.visible = enabled;
            if (this.staticRoot) this.staticRoot.children.filter(child => child.userData?.layer === 'buildings').forEach(child => { child.visible = enabled; });
            if (this.staticRoot) this.staticRoot.children.filter(child => child.userData?.landmark).forEach(child => { child.visible = enabled; });
        }
        if (layer === 'shops') this.roadsideShopMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (this.state) this.updateRoadVisualization(this.state);
    }

    updateRoadVisualization(state) {
        const congestion = state.edges_congestion || {};
        const closedEdges = new Set(state.closed_edges || []);
        this.updateClosureMarkers(closedEdges);
        for (const [edgeId, meshes] of this.roadMeshes.entries()) {
            const reading = congestion[edgeId];
            const ratio = Number(reading?.speed_ratio);
            const occupancy = Number(reading?.occupancy);
            const level = String(reading?.level || '').toLowerCase();
            let color = this.stadiumAccessEdges.has(edgeId)
                ? (this.theme === 'light' ? 0x41494f : 0x151d24) : this.baseRoadColor;
            if (this.layers.congestion && reading && !closedEdges.has(edgeId)) {
                if (level === 'red' || occupancy >= 0.40 || (Number.isFinite(ratio) && ratio <= 0.25)) color = 0xef4444;
                else if (level === 'orange' || occupancy >= 0.25 || (Number.isFinite(ratio) && ratio <= 0.45)) color = 0xf97316;
                else if (level === 'yellow' || occupancy >= 0.15 || (Number.isFinite(ratio) && ratio <= 0.75)) color = 0xfacc15;
                else color = 0x22c55e;
            }
            let highlight = 0x000000;
            if (this.layers.routes && this.selectedEdges.has(edgeId)) highlight = 0x00a8c4;
            if (this.reroutedEdges.has(edgeId)) highlight = 0x00e0c2;
            if (this.layers.vipRoute && this.vipEdges.has(edgeId)) highlight = 0xeab308;
            if (this.layers.construction && this.constructionEdges.has(edgeId)) highlight = 0xf97316;
            // Stadium access stays asphalt-colored when operator actions are
            // present; do not paint this approach purple over the requested
            // road treatment. Congestion, closure, and selected-route states
            // still take precedence below/above as applicable.
            if (this.layers.actions && this.actionEdges.has(edgeId) && !this.stadiumAccessEdges.has(edgeId)) highlight = 0xa78bfa;
            if (closedEdges.has(edgeId)) { color = 0x991b1b; highlight = 0xff4d4d; }
            for (const mesh of meshes) {
                mesh.material.color.setHex(color);
                mesh.material.emissive?.setHex(highlight);
                if (mesh.material.emissiveIntensity !== undefined) mesh.material.emissiveIntensity = highlight === 0 ? 0 : (closedEdges.has(edgeId) ? 0.42 : 0.2);
            }
        }
    }

    updateClosureMarkers(closedEdges) {
        if (!this.closureMarkers) this.closureMarkers = new Map();
        for (const [edgeId, group] of this.closureMarkers) {
            if (!closedEdges.has(edgeId)) { this.scene.remove(group); this.closureMarkers.delete(edgeId); }
        }
        for (const edgeId of closedEdges) {
            if (this.closureMarkers.has(edgeId)) continue;
            const edge = (this.geometry?.edges || []).find(item => item.id === edgeId);
            const lane = edge?.lanes?.find(item => item.shape?.length >= 2 && !item.allow?.includes('pedestrian'));
            if (!lane) continue;
            const p = this.samplePolyline(lane.shape, 0.5), before = this.samplePolyline(lane.shape, 0.49), after = this.samplePolyline(lane.shape, 0.51);
            const width = (edge.lanes || []).filter(item => !item.allow?.includes('pedestrian')).reduce((sum, item) => sum + (Number(item.width) || 3.2), 0);
            const group = new THREE.Group(); group.position.copy(this.worldToSceneCoordinates(p[0], p[1]));
            group.rotation.y = Math.atan2(after[0] - before[0], after[1] - before[1]);
            const beam = new THREE.Mesh(new THREE.BoxGeometry(Math.max(4, width), 0.55, 0.45), new THREE.MeshStandardMaterial({ color: 0xe5a11a, emissive: 0x4c2f04, roughness: 0.62 }));
            beam.position.y = 1.15; group.add(beam);
            const postGeo = new THREE.BoxGeometry(0.35, 1.35, 0.4), postMat = new THREE.MeshStandardMaterial({ color: 0x343a40, roughness: 0.78 });
            for (const x of [-width / 2 + 0.3, width / 2 - 0.3]) { const post = new THREE.Mesh(postGeo, postMat); post.position.set(x, 0.68, 0); group.add(post); }
            const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 64;
            const ctx = canvas.getContext('2d');
            if (ctx) { ctx.fillStyle = '#541515'; ctx.fillRect(0, 0, 256, 64); ctx.fillStyle = '#fff2d1'; ctx.font = 'bold 36px Segoe UI, Arial'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('CLOSED', 128, 32); }
            const sign = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), depthTest: false }));
            sign.position.set(0, 3.3, 0); sign.scale.set(8, 2, 1); group.add(sign);
            group.userData = { edgeId, type: 'ClosureMarker' }; this.scene.add(group); this.closureMarkers.set(edgeId, group);
        }
    }

    updateVehicles(vehicles) {
        const activeIds = new Set();

        for (const v of vehicles) {
            activeIds.add(v.id);
            let mesh = this.vehicleMeshes.get(v.id);

            if (!mesh) {
                mesh = this.createVehicleMesh(v);
                this.vehicleMeshes.set(v.id, mesh);
                this.scene.add(mesh);
            }
            mesh.visible = this.layers.vehicles;

            const elev = (Number(v.z) || 0) + 0.14;
            const targetPos = this.sumoTo3D(v.x, v.y, elev);

            mesh.position.lerp(targetPos, 0.4);

            const targetRotY = -v.angle * (Math.PI / 180);
            mesh.rotation.y = targetRotY;

            mesh.userData = {
                type: 'Vehicle',
                entityId: v.id,
                vType: v.type.toUpperCase(),
                speed: `${v.speed_kmh} km/h`,
                lane: v.lane_id,
                waiting: `${v.waiting_time}s`
            };
        }

        for (const [id, mesh] of this.vehicleMeshes.entries()) {
            if (!activeIds.has(id)) {
                this.scene.remove(mesh);
                this.vehicleMeshes.delete(id);
            }
        }
    }

    createVehicleMesh(v) {
        const group = new THREE.Group();
        const vType = v.type;
        const vehicleWidth = Math.max(1.5, Math.min(3.1, Number(v.width) || 1.85));
        const vehicleLength = Math.max(3.8, Math.min(15, Number(v.length) || 4.7));

        if (vType === 'train') {
            const trainMat = new THREE.MeshStandardMaterial({ color: 0x2563eb, metalness: 0.6, roughness: 0.3 });
            const coachGeo = new THREE.BoxGeometry(3.2, 3.4, 58);
            const coach = new THREE.Mesh(coachGeo, trainMat);
            coach.position.y = 1.7;
            coach.castShadow = true;
            group.add(coach);

            const winMat = new THREE.MeshBasicMaterial({ color: 0xffedd5 });
            const winGeo = new THREE.BoxGeometry(3.3, 1.2, 54);
            const win = new THREE.Mesh(winGeo, winMat);
            win.position.y = 1.8;
            group.add(win);

            const lightGeo = new THREE.SphereGeometry(0.3, 8, 8);
            const lightMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
            const light1 = new THREE.Mesh(lightGeo, lightMat);
            light1.position.set(-1.0, 1.2, -29);
            const light2 = new THREE.Mesh(lightGeo, lightMat);
            light2.position.set(1.0, 1.2, -29);
            group.add(light1, light2);
        } else if (vType === 'bus') {
            const busMat = new THREE.MeshStandardMaterial({ color: 0x9333ea, metalness: 0.4, roughness: 0.5 });
            const bodyGeo = new THREE.BoxGeometry(vehicleWidth, 3.2, Math.max(8.5, vehicleLength));
            const body = new THREE.Mesh(bodyGeo, busMat);
            body.position.y = 1.68;
            body.castShadow = true;
            group.add(body);

            const destMat = new THREE.MeshBasicMaterial({ color: 0xfef08a });
            const destGeo = new THREE.BoxGeometry(vehicleWidth * 0.78, 0.5, 0.4);
            const dest = new THREE.Mesh(destGeo, destMat);
            dest.position.set(0, 3.08, -Math.max(4.4, vehicleLength / 2 - 0.2));
            group.add(dest);
        } else if (vType === 'motorcycle') {
            const bikeMat = new THREE.MeshStandardMaterial({ color: 0xf97316, metalness: 0.7, roughness: 0.3 });
            const bodyGeo = new THREE.BoxGeometry(Math.max(0.7, Math.min(1.05, vehicleWidth * 0.5)), 1.2, Math.max(1.8, Math.min(3, vehicleLength * 0.55)));
            const body = new THREE.Mesh(bodyGeo, bikeMat);
            body.position.y = 0.7;
            body.castShadow = true;
            group.add(body);
        } else {
            const carColor = vType === 'taxi' ? 0xeab308 : 0x06b6d4;
            const carMat = new THREE.MeshStandardMaterial({ color: carColor, metalness: 0.6, roughness: 0.3 });
            const bodyWidth = Math.min(2.25, vehicleWidth);
            const bodyLength = Math.max(4.4, Math.min(5.8, vehicleLength));
            const chassisGeo = new THREE.BoxGeometry(bodyWidth, 0.9, bodyLength);
            const chassis = new THREE.Mesh(chassisGeo, carMat);
            chassis.position.y = 0.55;
            chassis.castShadow = true;
            group.add(chassis);

            const cabinMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.1, metalness: 0.9 });
            const cabinGeo = new THREE.BoxGeometry(bodyWidth * 0.78, 0.7, bodyLength * 0.52);
            const cabin = new THREE.Mesh(cabinGeo, cabinMat);
            cabin.position.set(0, 1.2, -0.12);
            group.add(cabin);

            const headMat = new THREE.MeshBasicMaterial({ color: 0xfffee0 });
            const hGeo = new THREE.BoxGeometry(0.3, 0.2, 0.1);
            const hL = new THREE.Mesh(hGeo, headMat);
            hL.position.set(-bodyWidth * 0.34, 0.55, -bodyLength / 2 - 0.025);
            const hR = new THREE.Mesh(hGeo, headMat);
            hR.position.set(bodyWidth * 0.34, 0.55, -bodyLength / 2 - 0.025);
            group.add(hL, hR);
        }

        return group;
    }

    updatePedestrians(pedestrians) {
        const activeIds = new Set();

        for (const p of pedestrians) {
            activeIds.add(p.id);
            let mesh = this.pedestrianMeshes.get(p.id);

            if (!mesh) {
                mesh = this.createPedestrianMesh(p);
                this.pedestrianMeshes.set(p.id, mesh);
                this.scene.add(mesh);
            }
            mesh.visible = this.layers.pedestrians;

            const targetPos = this.sumoTo3D(p.x, p.y, 0.25);
            mesh.position.lerp(targetPos, 0.4);

            if (p.speed > 0.1 && mesh.userData.leftLeg) {
                const legAngle = Math.sin(this.animTime * 10) * 0.4;
                mesh.userData.leftLeg.rotation.x = legAngle;
                mesh.userData.rightLeg.rotation.x = -legAngle;
            }

            mesh.userData = {
                ...mesh.userData,
                type: 'Pedestrian',
                entityId: p.id,
                flow: p.dest_flow === 'stadium' ? '🏟️ Stadium Bound' : p.dest_flow === 'beach' ? '🌊 Beach Walk' : '🏘️ Local Trip',
                speed: `${(p.speed * 3.6).toFixed(1)} km/h`,
                edge: p.edge_id
            };
        }

        for (const [id, mesh] of this.pedestrianMeshes.entries()) {
            if (!activeIds.has(id)) {
                this.scene.remove(mesh);
                this.pedestrianMeshes.delete(id);
            }
        }
    }

    createPedestrianMesh(p) {
        const group = new THREE.Group();

        let shirtColor = 0x94a3b8;
        if (p.dest_flow === 'stadium') shirtColor = 0xfacc15;
        else if (p.dest_flow === 'beach') shirtColor = 0x38bdf8;

        const shirtMat = new THREE.MeshStandardMaterial({ color: shirtColor, roughness: 0.8 });
        const skinMat = new THREE.MeshStandardMaterial({ color: 0xca8a04, roughness: 0.9 });
        const pantsMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.9 });

        const headGeo = new THREE.SphereGeometry(0.25, 8, 8);
        const head = new THREE.Mesh(headGeo, skinMat);
        head.position.y = 1.6;
        group.add(head);

        const torsoGeo = new THREE.CylinderGeometry(0.25, 0.28, 0.7, 8);
        const torso = new THREE.Mesh(torsoGeo, shirtMat);
        torso.position.y = 1.05;
        torso.castShadow = true;
        group.add(torso);

        const legGeo = new THREE.CylinderGeometry(0.09, 0.09, 0.7, 6);
        const leftLeg = new THREE.Mesh(legGeo, pantsMat);
        leftLeg.position.set(-0.12, 0.35, 0);
        const rightLeg = new THREE.Mesh(legGeo, pantsMat);
        rightLeg.position.set(0.12, 0.35, 0);
        group.add(leftLeg, rightLeg);

        group.userData.leftLeg = leftLeg;
        group.userData.rightLeg = rightLeg;

        return group;
    }

    updateTrafficLights(trafficLights) {
        if (!this.geometry || !this.geometry.nodes) return;

        for (const [tlId, tl] of Object.entries(trafficLights)) {
            const node = this.geometry.nodes.find(n => n.id === tlId);
            if (!node) continue;

            let signalMesh = this.signalMeshes.get(tlId);
            if (!signalMesh) {
                signalMesh = this.createSignalMesh(tlId, node);
                this.signalMeshes.set(tlId, signalMesh);
                (this.staticRoot || this.scene).add(signalMesh);
            }

            const heads = signalMesh.userData.heads || [{
                incomingEdges: [],
                bulbs: signalMesh.userData.bulbs
            }];
            const links = Array.isArray(tl.controlled_links) ? tl.controlled_links : [];
            for (const head of heads) {
                const incomingEdges = new Set(head.incomingEdges || []);
                const relevantLinks = links.filter(link =>
                    (link.incoming_edges || []).some(edgeId => incomingEdges.has(edgeId)));
                const codes = relevantLinks.map(link => String(link.state || '')).join('');
                let color = tl.color;
                if (relevantLinks.length) {
                    if (/[gG]/.test(codes)) color = 'green';
                    else if (/[yY]/.test(codes)) color = 'yellow';
                    else if (/[rR]/.test(codes)) color = 'red';
                    else color = 'off';
                }
                const bulbs = head.bulbs;
                if (!bulbs) continue;
                bulbs.red.material.emissiveIntensity = color === 'red' ? 2.5 : 0.025;
                bulbs.yellow.material.emissiveIntensity = color === 'yellow' ? 2.5 : 0.025;
                bulbs.green.material.emissiveIntensity = color === 'green' ? 2.5 : 0.025;
            }
        }
    }

    createSignalMesh(tlId, node) {
        const group = new THREE.Group();
        const pos = this.sumoTo3D(node.x, node.y, 0);
        group.position.copy(pos);

        const poleGeo = new THREE.CylinderGeometry(0.2, 0.25, 6.0, 8);
        const poleMat = new THREE.MeshStandardMaterial({ color: 0x334155, metalness: 0.8 });
        const pole = new THREE.Mesh(poleGeo, poleMat);
        pole.position.y = 3.0;
        pole.castShadow = true;
        group.add(pole);

        const boxGeo = new THREE.BoxGeometry(0.8, 2.2, 0.6);
        const boxMat = new THREE.MeshStandardMaterial({ color: 0x0f172a });
        const box = new THREE.Mesh(boxGeo, boxMat);
        box.position.set(0, 5.2, 0.4);
        group.add(box);

        const bulbGeo = new THREE.SphereGeometry(0.25, 8, 8);
        
        const redMat = new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0xef4444, emissiveIntensity: 0.1 });
        const redBulb = new THREE.Mesh(bulbGeo, redMat);
        redBulb.position.set(0, 5.8, 0.7);
        group.add(redBulb);

        const yelMat = new THREE.MeshStandardMaterial({ color: 0xf59e0b, emissive: 0xf59e0b, emissiveIntensity: 0.1 });
        const yelBulb = new THREE.Mesh(bulbGeo, yelMat);
        yelBulb.position.set(0, 5.2, 0.7);
        group.add(yelBulb);

        const grnMat = new THREE.MeshStandardMaterial({ color: 0x10b981, emissive: 0x10b981, emissiveIntensity: 0.1 });
        const grnBulb = new THREE.Mesh(bulbGeo, grnMat);
        grnBulb.position.set(0, 4.6, 0.7);
        group.add(grnBulb);

        group.userData = {
            entityId: tlId,
            type: 'TrafficSignal',
            bulbs: { red: redBulb, yellow: yelBulb, green: grnBulb }
        };

        return group;
    }

    focusCamera(preset) {
        if (!this.controls) return;
        this.followTarget = null;
        this.followType = null;

        if (preset === 'overview' || preset === 'isometric' || preset === 'reset') {
            if (this.defaultCameraPose) {
                this.camera.position.copy(this.defaultCameraPose.position);
                this.controls.target.copy(this.defaultCameraPose.target);
            }
        } else if (preset === 'topdown') {
            const span = Math.max(this.networkSpan.x, this.networkSpan.y);
            const center = this.studyAreaCenter || this.networkCenter;
            this.controls.target.copy(center);
            this.camera.position.set(center.x, span * 1.7, center.z + 1);
        } else if (preset === 'stadium') {
            const p = this.geometry?.polygons?.find(x => x.id === 'poly_stadium');
            const c = p ? this.polygonCentroid(p.shape) : { x: this.networkCenter.x, y: -this.networkCenter.z };
            const station = (this.geometry?.nodes || []).find(node => node.id === 'N_STATION_GROUND');
            const targetX = station ? (c.x + station.x) / 2 : c.x;
            const targetY = station ? (c.y + station.y) / 2 : c.y;
            const target = this.worldToSceneCoordinates(targetX, targetY, 4.5);
            const localSpan = this.getStadiumAreaViewSpan();
            this.controls.target.copy(target);
            this.camera.position.copy(target).add(new THREE.Vector3(localSpan * 0.42, localSpan * 0.8, localSpan * 0.82));
        } else if (preset === 'station') {
            const p = this.geometry?.polygons?.find(x => x.id === 'poly_station_elevated');
            const c = p ? this.polygonCentroid(p.shape) : { x: this.networkCenter.x, y: -this.networkCenter.z };
            this.controls.target.copy(this.worldToSceneCoordinates(c.x, c.y, this.getRailElevation() + 1));
            this.camera.position.copy(this.controls.target).add(new THREE.Vector3(40, 65, 40));
        } else if (preset === 'beach') {
            const p = this.geometry?.polygons?.find(x => x.id === 'poly_beach');
            const c = p ? this.polygonCentroid(p.shape) : { x: this.networkCenter.x, y: -this.networkCenter.z };
            this.controls.target.copy(this.worldToSceneCoordinates(c.x, c.y));
            this.camera.position.copy(this.controls.target).add(new THREE.Vector3(this.networkSpan.x * 0.12, this.networkSpan.y * 0.22, this.networkSpan.y * 0.26));
        } else if (preset === 'follow_car') {
            const cars = Array.from(this.vehicleMeshes.values()).filter(m => m.userData.vType !== 'TRAIN');
            if (cars.length > 0) {
                this.followTarget = cars[0];
                this.followType = 'vehicle';
            }
        } else if (preset === 'follow_ped') {
            if (this.pedestrianMeshes.size > 0) {
                this.followTarget = this.pedestrianMeshes.values().next().value;
                this.followType = 'pedestrian';
            }
        } else if (preset === 'follow_train') {
            const trains = Array.from(this.vehicleMeshes.values()).filter(m => m.userData.vType === 'TRAIN');
            if (trains.length > 0) {
                this.followTarget = trains[0];
                this.followType = 'train';
            }
        }
        this.controls.update();
    }

    animate() {
        requestAnimationFrame(() => this.animate());

        if (this.controls) {
            this.controls.update();
        }
        this.updateMapLabelVisibility();

        if (this.waterMesh) {
            const time = this.clock.getElapsedTime();
            this.waterMesh.position.y = -0.05 + Math.sin(time * 1.5) * 0.1;
        }

        this.renderer.render(this.scene, this.camera);
    }
}
