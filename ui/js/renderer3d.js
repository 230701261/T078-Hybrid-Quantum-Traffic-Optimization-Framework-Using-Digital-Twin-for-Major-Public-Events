/**
 * Three.js 3D Digital Twin WebGL Simulation
 * Realistic Stadium Sizing & Clearance Setback, Urban Coastal Road with DUAL Continuous Sidewalks,
 * Open Sandy Beach & Ocean, Roadside Shops, Single Stadium Station, and Time-Dependent Heavy Event Congestion.
 */

// Buffer geometry is immutable after construction, so both synchronized map
// scenes can share the same CPU-side road ribbon geometry.
const sharedRibbonGeometry = new Map();

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
        this.roadMeshes = new Map();
        this.baseRoadColor = 0x1e293b;
        this.theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
        this.groundMesh = null;
        this.selectedEdges = new Set();
        this.actionEdges = new Set();
        this.vipEdges = new Set();
        this.constructionEdges = new Set();
        this.overlayLayers = { congestion: true, routes: true, actions: true };
        this.onEntitySelected = null;
        this.floodlightTowers = [];
        this.stadiumMeshGroup = null;
        this.waterMesh = null;
        this.busStopMeshes = [];
        this.roadsideShopMeshes = [];

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
        this.camera.position.set(450, 360, -80);

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
            this.controls.target.set(440, 10, -400); // Focus on Stadium center
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
            while (obj && !obj.userData.entityId && obj.parent !== this.scene) {
                obj = obj.parent;
            }
            if (obj && obj.userData && (obj.userData.entityId || obj.userData.edgeId || obj.userData.junctionId)) {
                found = obj.userData;
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

    sumoTo3D(sumoX, sumoY, elevation = 0) {
        return new THREE.Vector3(sumoX, elevation, -sumoY);
    }

    setGeometry(geoData) {
        this.geometry = geoData;
        this.build3DEnvironment();
    }

    setTheme(theme) {
        this.theme = theme === 'light' ? 'light' : 'dark';
        const background = this.theme === 'light' ? 0xe8eef2 : 0x060913;
        this.baseRoadColor = this.theme === 'light' ? 0x596a78 : 0x1e293b;
        if (this.scene) {
            this.scene.background?.setHex(background);
            if (this.scene.fog) this.scene.fog.color.setHex(background);
        }
        if (this.groundMesh) this.groundMesh.material.color.setHex(this.theme === 'light' ? 0xd7e0e6 : 0x090d1a);
        for (const meshes of this.roadMeshes.values()) {
            for (const mesh of meshes) mesh.material.color.setHex(this.baseRoadColor);
        }
    }

    build3DEnvironment() {
        if (!this.geometry) return;

        // 1. Base Ground Terrain
        const groundGeo = new THREE.PlaneGeometry(3800, 3800);
        const groundMat = new THREE.MeshStandardMaterial({ color: this.theme === 'light' ? 0xd7e0e6 : 0x090d1a, roughness: 0.95, metalness: 0.05 });
        this.groundMesh = new THREE.Mesh(groundGeo, groundMat);
        this.groundMesh.rotation.x = -Math.PI / 2;
        this.groundMesh.position.set(450, -0.2, -400);
        this.groundMesh.receiveShadow = true;
        this.scene.add(this.groundMesh);

        // 2. Marina Coastal Road with DUAL Sidewalks and Open Beach (Zero Dedicated Statue Park)
        this.buildMarinaCoastalRoad();

        // 3. Roads, Sidewalks, and Dedicated 4.5m Orange Walkway
        this.build3DRoads();

        // 4. MA Chidambaram Stadium (Clear Setback Buffer from Surrounding Roads)
        this.buildStadium();

        // 5. Single Primary Elevated MRTS Railway Station & Viaduct (Z=8m)
        this.buildMRTSViaductAndStation();

        // 6. Enlarged Yellow 3D Bus Stop Shelters
        this.buildBusStops();

        // 7. Accurately Aligned Roadside Commercial Shops (Beside roads, setback behind sidewalks)
        this.buildRoadsideShops();

        // 8. Surrounding City Context Buildings
        this.buildCityBuildings();
    }

    buildMarinaCoastalRoad() {
        // ==================== 1. EAST ROADSIDE CONTINUOUS SIDEWALK (COASTAL WALKWAY) ====================
        // Continuous sidewalk directly along the beach-side road curb (Width = 4.5m)
        const eastSidewalkGeo = new THREE.PlaneGeometry(4.5, 1300);
        const eastSidewalkMat = new THREE.MeshStandardMaterial({ color: 0x475569, roughness: 0.85 });
        const eastSidewalk = new THREE.Mesh(eastSidewalkGeo, eastSidewalkMat);
        eastSidewalk.rotation.x = -Math.PI / 2;
        eastSidewalk.position.set(747.0, 0.06, -260);
        eastSidewalk.receiveShadow = true;
        this.scene.add(eastSidewalk);

        // Low Coastal Roadside Curb / Railing along the East Sidewalk (X = 749.5)
        const curbGeo = new THREE.BoxGeometry(0.5, 0.4, 1300);
        const curbMat = new THREE.MeshStandardMaterial({ color: 0x64748b, roughness: 0.7 });
        const curb = new THREE.Mesh(curbGeo, curbMat);
        curb.position.set(749.5, 0.2, -260);
        curb.castShadow = true;
        this.scene.add(curb);

        // Subtle coastal light poles along the eastern sidewalk every 50m
        const poleGeo = new THREE.CylinderGeometry(0.12, 0.15, 5.5, 6);
        const poleMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.8 });
        for (let z = -520; z <= 120; z += 50) {
            const pole = new THREE.Mesh(poleGeo, poleMat);
            pole.position.set(749.0, 2.75, z);
            pole.castShadow = true;
            this.scene.add(pole);
        }

        // ==================== 2. TWO NATURAL COASTAL MONUMENT SCULPTURES (SUBTLE & DECORATIVE) ====================
        // Situated naturally on small stone platforms off the walking path
        const monConfigs = [
            { x: 753, z: -350, h: 4.5 },
            { x: 753, z: -80, h: 4.0 }
        ];
        const stoneMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, roughness: 0.7, metalness: 0.2 });
        for (const m of monConfigs) {
            const group = new THREE.Group();
            const baseGeo = new THREE.BoxGeometry(3.0, 0.6, 3.0);
            const base = new THREE.Mesh(baseGeo, stoneMat);
            base.position.y = 0.3;
            group.add(base);

            const pillarGeo = new THREE.CylinderGeometry(0.5, 0.8, m.h, 6);
            const pillar = new THREE.Mesh(pillarGeo, stoneMat);
            pillar.position.y = 0.6 + m.h / 2;
            group.add(pillar);

            group.position.set(m.x, 0, m.z);
            this.scene.add(group);
        }

        // ==================== 3. OPEN SANDY BEACH & OCEAN WATER (NATURAL COASTLINE, X >= 755) ====================
        // Open sandy beach plane (starts cleanly at X = 755 beyond the east sidewalk)
        const sandGeo = new THREE.PlaneGeometry(165, 1300);
        const sandMat = new THREE.MeshStandardMaterial({ color: 0xd97706, roughness: 0.95, metalness: 0.05 });
        const sand = new THREE.Mesh(sandGeo, sandMat);
        sand.rotation.x = -Math.PI / 2;
        sand.position.set(837.5, 0.02, -260);
        sand.receiveShadow = true;
        this.scene.add(sand);

        // Ocean Water Plane (Bay of Bengal, X > 920)
        const waterGeo = new THREE.PlaneGeometry(1500, 1600, 32, 32);
        const waterMat = new THREE.MeshStandardMaterial({
            color: 0x0284c7,
            roughness: 0.1,
            metalness: 0.9,
            transparent: true,
            opacity: 0.92
        });
        this.waterMesh = new THREE.Mesh(waterGeo, waterMat);
        this.waterMesh.rotation.x = -Math.PI / 2;
        this.waterMesh.position.set(1670, -0.05, -260);
        this.scene.add(this.waterMesh);
    }

    build3DRoads() {
        const roadMat = new THREE.MeshStandardMaterial({ color: this.baseRoadColor, roughness: 0.85 });
        const sidewalkMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.9 });
        const orangePedMat = new THREE.MeshStandardMaterial({ color: 0xf97316, roughness: 0.75, metalness: 0.1 });
        const railBedMat = new THREE.MeshStandardMaterial({ color: 0x1e3a8a, roughness: 0.6 });

        for (const edge of this.geometry.edges) {
            const isRail = edge.id.includes('RAIL');
            const isOrangePed = edge.id.includes('PED_') || edge.type === 'pedestrian_orange';

            for (const lane of edge.lanes) {
                if (lane.shape.length < 2) continue;

                const isSidewalk = lane.allow.includes('pedestrian') && !lane.allow.includes('passenger');
                const elev = isRail ? 7.8 : isOrangePed ? 0.22 : isSidewalk ? 0.18 : 0.08;
                const mat = isRail ? railBedMat : isOrangePed ? orangePedMat : isSidewalk ? sidewalkMat
                    : new THREE.MeshStandardMaterial({ color: this.baseRoadColor, roughness: 0.85 });

                const mesh = this.createRibbonMesh(lane.shape, lane.width, elev, mat);
                if (mesh) {
                    mesh.receiveShadow = true;
                    if (!isRail && !isOrangePed && !isSidewalk) {
                        mesh.userData.edgeId = edge.id;
                        if (!this.roadMeshes.has(edge.id)) this.roadMeshes.set(edge.id, []);
                        this.roadMeshes.get(edge.id).push(mesh);
                    }
                    this.scene.add(mesh);
                }
            }
        }

        // Crossings
        if (this.geometry.crossings) {
            const crossMat = new THREE.MeshBasicMaterial({ color: 0xe2e8f0 });
            for (const c of this.geometry.crossings) {
                if (c.shape && c.shape.length >= 2) {
                    const cMesh = this.createRibbonMesh(c.shape, c.width || 3.0, 0.12, crossMat);
                    if (cMesh) this.scene.add(cMesh);
                }
            }
        }
    }

    createRibbonMesh(points, width, elev, material) {
        if (points.length < 2) return null;
        const cacheKey = `${width}|${elev}|${points.map(point => `${point[0]},${point[1]}`).join(';')}`;
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

            const pLeft = new THREE.Vector3(p[0] + normal.x * halfW, elev, -(p[1] + normal.y * halfW));
            const pRight = new THREE.Vector3(p[0] - normal.x * halfW, elev, -(p[1] - normal.y * halfW));

            positions.push(pLeft.x, pLeft.y, pLeft.z);
            positions.push(pRight.x, pRight.y, pRight.z);

            if (i < points.length - 1) {
                const base = i * 2;
                indices.push(base, base + 1, base + 2);
                indices.push(base + 1, base + 3, base + 2);
            }
        }

        geo = new THREE.BufferGeometry();
        geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geo.setIndex(indices);
        geo.computeVertexNormals();
        sharedRibbonGeometry.set(cacheKey, geo);
        return new THREE.Mesh(geo, material);
    }

    buildStadium() {
        this.stadiumMeshGroup = new THREE.Group();
        const center = new THREE.Vector3(440, 0, -440);

        // ==================== SCALED STADIUM DIMENSIONS (>30m BUFFER FROM SURROUNDING ROADS) ====================
        // Outer bowl radius = 48m, height = 18m
        const bowlGeo = new THREE.CylinderGeometry(48, 40, 18, 48, 1, true);
        const bowlMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.7, metalness: 0.3, side: THREE.DoubleSide });
        const bowl = new THREE.Mesh(bowlGeo, bowlMat);
        bowl.position.set(0, 9, 0);
        bowl.castShadow = true;
        bowl.receiveShadow = true;
        this.stadiumMeshGroup.add(bowl);

        // Seating Tiers (CSK Yellow & Blue)
        const tier1Geo = new THREE.CylinderGeometry(43, 33, 9, 48, 1, true);
        const tier1Mat = new THREE.MeshStandardMaterial({ color: 0xfacc15, roughness: 0.8 });
        const tier1 = new THREE.Mesh(tier1Geo, tier1Mat);
        tier1.position.set(0, 5.5, 0);
        this.stadiumMeshGroup.add(tier1);

        const tier2Geo = new THREE.CylinderGeometry(36, 28, 4, 48, 1, true);
        const tier2Mat = new THREE.MeshStandardMaterial({ color: 0x1d4ed8, roughness: 0.8 });
        const tier2 = new THREE.Mesh(tier2Geo, tier2Mat);
        tier2.position.set(0, 2.0, 0);
        this.stadiumMeshGroup.add(tier2);

        // Central Cricket Ground / Pitch
        const fieldGeo = new THREE.CircleGeometry(27, 48);
        const fieldMat = new THREE.MeshStandardMaterial({ color: 0x15803d, roughness: 0.9 });
        const field = new THREE.Mesh(fieldGeo, fieldMat);
        field.rotation.x = -Math.PI / 2;
        field.position.set(0, 0.1, 0);
        field.receiveShadow = true;
        this.stadiumMeshGroup.add(field);

        const pitchGeo = new THREE.PlaneGeometry(4.5, 16);
        const pitchMat = new THREE.MeshStandardMaterial({ color: 0xd4a373, roughness: 0.95 });
        const pitch = new THREE.Mesh(pitchGeo, pitchMat);
        pitch.rotation.x = -Math.PI / 2;
        pitch.position.set(0, 0.15, 0);
        this.stadiumMeshGroup.add(pitch);

        // Tensile Canopy Roof Ring (Inner: 36m, Outer: 52m)
        const roofGeo = new THREE.RingGeometry(36, 52, 48);
        const roofMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3, metalness: 0.1, side: THREE.DoubleSide });
        const roof = new THREE.Mesh(roofGeo, roofMat);
        roof.rotation.x = -Math.PI / 2;
        roof.position.set(0, 18.5, 0);
        roof.castShadow = true;
        this.stadiumMeshGroup.add(roof);

        // 4 Floodlight Towers (Radius = 48m, Lit on Event Day)
        const towerOffsets = [
            { x: 48, z: 48 },
            { x: -48, z: 48 },
            { x: 48, z: -48 },
            { x: -48, z: -48 }
        ];

        this.floodlightTowers = [];
        for (const off of towerOffsets) {
            const towerGroup = new THREE.Group();
            
            const mastGeo = new THREE.CylinderGeometry(0.8, 1.8, 38, 6);
            const mastMat = new THREE.MeshStandardMaterial({ color: 0x64748b, metalness: 0.7 });
            const mast = new THREE.Mesh(mastGeo, mastMat);
            mast.position.set(off.x, 19, off.z);
            mast.castShadow = true;
            towerGroup.add(mast);

            const headGeo = new THREE.BoxGeometry(6.5, 4.0, 2.0);
            const headMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, emissive: 0xffffff, emissiveIntensity: 0.2 });
            const head = new THREE.Mesh(headGeo, headMat);
            head.position.set(off.x, 38, off.z);
            head.lookAt(0, 8, 0);
            towerGroup.add(head);

            const spot = new THREE.SpotLight(0xfffbeb, 0.0, 260, Math.PI / 4, 0.5, 1);
            spot.position.set(off.x, 38, off.z);
            spot.target.position.set(0, 5, 0);
            spot.castShadow = true;
            towerGroup.add(spot);
            towerGroup.add(spot.target);

            this.floodlightTowers.push({ group: towerGroup, light: spot, headMat: headMat });
            this.stadiumMeshGroup.add(towerGroup);
        }

        this.stadiumMeshGroup.position.copy(center);
        this.scene.add(this.stadiumMeshGroup);
    }

    buildMRTSViaductAndStation() {
        // Concrete Support Pillars along elevated railway viaduct (Z=8m)
        const pillarGeo = new THREE.CylinderGeometry(1.4, 1.8, 7.8, 8);
        const pillarMat = new THREE.MeshStandardMaterial({ color: 0x475569, roughness: 0.9 });
        
        const viaductPoints = [
            { x: 390, y: 880 }, { x: 420, y: 790 }, { x: 460, y: 680 },
            { x: 490, y: 530 }, { x: 520, y: 390 }, { x: 518, y: 210 },
            { x: 515, y: 20 }, { x: 510, y: -120 }
        ];

        for (const pt of viaductPoints) {
            const pillar = new THREE.Mesh(pillarGeo, pillarMat);
            pillar.position.set(pt.x, 3.9, -pt.y);
            pillar.castShadow = true;
            pillar.receiveShadow = true;
            this.scene.add(pillar);
        }

        // Single Primary Chepauk MRTS Elevated Station Building (Red Circle on map)
        const stnGroup = new THREE.Group();
        const stnBodyGeo = new THREE.BoxGeometry(20, 12, 65);
        const stnBodyMat = new THREE.MeshStandardMaterial({ color: 0x1e3a8a, roughness: 0.5, metalness: 0.4 });
        const stnBody = new THREE.Mesh(stnBodyGeo, stnBodyMat);
        stnBody.position.set(520, 7.5, -390);
        stnBody.castShadow = true;
        stnGroup.add(stnBody);

        // Platform Roof
        const roofGeo = new THREE.BoxGeometry(24, 1.2, 70);
        const roofMat = new THREE.MeshStandardMaterial({ color: 0x60a5fa, metalness: 0.3 });
        const stnRoof = new THREE.Mesh(roofGeo, roofMat);
        stnRoof.position.set(520, 14.0, -390);
        stnGroup.add(stnRoof);

        // Vertical Stairs / Elevator Tower connecting Elevated Platform (Y=8m) down to Ground Plaza (Y=0m)
        const stairsGeo = new THREE.BoxGeometry(10, 8.5, 12);
        const stairsMat = new THREE.MeshStandardMaterial({ color: 0x3b82f6, roughness: 0.4 });
        const stairs = new THREE.Mesh(stairsGeo, stairsMat);
        stairs.position.set(508, 4.25, -390);
        stairs.castShadow = true;
        stnGroup.add(stairs);

        this.scene.add(stnGroup);
    }

    buildBusStops() {
        // 7 Enlarged Yellow 3D Bus Stop Shelters with Waiting Areas
        const busStopPositions = [
            { id: 'BS_1_NORTH', x: 95, y: 765, rot: 0 },
            { id: 'BS_2_WEST_UP', x: 65, y: 660, rot: Math.PI / 2 },
            { id: 'BS_3_WEST_DOWN', x: 85, y: 300, rot: Math.PI / 2 },
            { id: 'BS_4_CENTRAL', x: 348, y: 530, rot: Math.PI / 2 },
            { id: 'BS_5_EAST_UP', x: 725, y: 440, rot: -Math.PI / 2 },
            { id: 'BS_6_EAST_DOWN', x: 715, y: 160, rot: -Math.PI / 2 },
            { id: 'BS_7_SOUTH', x: 500, y: 32, rot: 0 }
        ];

        const shelterBodyGeo = new THREE.BoxGeometry(6.5, 3.2, 3.0);
        const shelterBodyMat = new THREE.MeshStandardMaterial({ color: 0xfacc15, roughness: 0.4, metalness: 0.3 }); // Yellow
        
        const roofGeo = new THREE.BoxGeometry(7.2, 0.4, 3.8);
        const roofMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, metalness: 0.8 });

        const signGeo = new THREE.BoxGeometry(4.0, 0.8, 0.15);
        const signMat = new THREE.MeshBasicMaterial({ color: 0x0f172a });

        for (const bs of busStopPositions) {
            const group = new THREE.Group();
            
            // Yellow Shelter Canopy Box
            const body = new THREE.Mesh(shelterBodyGeo, shelterBodyMat);
            body.position.y = 1.6;
            body.castShadow = true;
            group.add(body);

            // Dark Roof
            const roof = new THREE.Mesh(roofGeo, roofMat);
            roof.position.y = 3.3;
            group.add(roof);

            // "BUS STOP" Signboard
            const sign = new THREE.Mesh(signGeo, signMat);
            sign.position.set(0, 2.5, 1.55);
            group.add(sign);

            // Waiting Plaza Slab
            const plazaGeo = new THREE.BoxGeometry(8.0, 0.15, 5.0);
            const plazaMat = new THREE.MeshStandardMaterial({ color: 0x475569, roughness: 0.9 });
            const plaza = new THREE.Mesh(plazaGeo, plazaMat);
            plaza.position.set(0, 0.08, 0);
            group.add(plaza);

            group.position.set(bs.x, 0, -bs.y);
            group.rotation.y = bs.rot;
            this.scene.add(group);
            this.busStopMeshes.push(group);
        }
    }

    buildRoadsideShops() {
        // Accurately positioned & road-facing commercial shops with 4.5m to 8m setbacks behind sidewalks
        const shopDefinitions = [
            // North Major Road (Wallajah Rd) — North Side (Facing South, rotY = 0)
            { x: 160, z: -795, w: 10, d: 8, h: 5.5, rot: 0, color: 0x0284c7, type: "Tea & Snacks" },
            { x: 235, z: -790, w: 12, d: 9, h: 6.0, rot: 0, color: 0xd97706, type: "Restaurant" },
            { x: 480, z: -720, w: 11, d: 8, h: 5.0, rot: 0, color: 0x16a34a, type: "Convenience" },
            { x: 575, z: -680, w: 14, d: 10, h: 6.5, rot: 0, color: 0x9333ea, type: "Retail Store" },
            { x: 650, z: -640, w: 10, d: 8, h: 5.0, rot: 0, color: 0xe11d48, type: "Bakery & Cafe" },

            // North Major Road — South Side (Facing North, rotY = Math.PI)
            { x: 200, z: -665, w: 11, d: 8, h: 5.5, rot: Math.PI, color: 0x2563eb, type: "Electronics" },
            { x: 480, z: -665, w: 10, d: 8, h: 5.0, rot: Math.PI, color: 0xca8a04, type: "Fast Food" },

            // West Major Road (Mount Rd) — West Side (Facing East, rotY = -Math.PI/2)
            { x: 35, z: -720, w: 8, d: 12, h: 5.5, rot: -Math.PI / 2, color: 0x2563eb, type: "General Store" },
            { x: 35, z: -580, w: 9, d: 10, h: 5.0, rot: -Math.PI / 2, color: 0x059669, type: "Medical Shop" },
            { x: 42, z: -440, w: 11, d: 12, h: 6.5, rot: -Math.PI / 2, color: 0xd97706, type: "Hotel & Mess" },
            { x: 52, z: -280, w: 9, d: 10, h: 5.0, rot: -Math.PI / 2, color: 0x7c3aed, type: "Tea Stall" },
            { x: 62, z: -160, w: 12, d: 11, h: 6.0, rot: -Math.PI / 2, color: 0x0891b2, type: "Electronics" },

            // West Major Road — East Side (Facing West, rotY = Math.PI/2)
            { x: 110, z: -600, w: 9, d: 10, h: 5.0, rot: Math.PI / 2, color: 0x16a34a, type: "Bookstore" },
            { x: 115, z: -420, w: 10, d: 11, h: 5.5, rot: Math.PI / 2, color: 0xe11d48, type: "Cafe" },

            // Central Stadium Approach Road (Facing East, rotY = -Math.PI/2)
            { x: 318, z: -620, w: 8, d: 7, h: 4.5, rot: -Math.PI / 2, color: 0xeab308, type: "Sports Goods" },
            { x: 318, z: -510, w: 9, d: 8, h: 5.0, rot: -Math.PI / 2, color: 0xf97316, type: "CSK Merchandise" },
            { x: 320, z: -430, w: 8, d: 7, h: 4.5, rot: -Math.PI / 2, color: 0x10b981, type: "Match Kiosk" },
            { x: 322, z: -320, w: 9, d: 8, h: 5.0, rot: -Math.PI / 2, color: 0x6366f1, type: "Cafe & Juice" },
            { x: 325, z: -200, w: 10, d: 8, h: 5.5, rot: -Math.PI / 2, color: 0xec4899, type: "Food Court" },

            // Stadium Perimeter Kiosks (Setback safely inside plaza at Z = -350)
            { x: 410, z: -350, w: 6, d: 4.5, h: 3.5, rot: 0, color: 0xfacc15, type: "Jersey Stall" },
            { x: 455, z: -350, w: 6, d: 4.5, h: 3.5, rot: 0, color: 0xf97316, type: "Ticket Booth" },

            // South Major Road (Bells Rd) — South Side (Facing North, rotY = Math.PI)
            { x: 170, z: -105, w: 11, d: 9, h: 5.5, rot: Math.PI, color: 0x059669, type: "Pharmacy" },
            { x: 260, z: -70, w: 12, d: 9, h: 6.0, rot: Math.PI, color: 0x2563eb, type: "Department Store" },
            { x: 380, z: -30, w: 10, d: 8, h: 5.0, rot: Math.PI, color: 0xd97706, type: "Tea & Snacks" },
            { x: 580, z: 12, w: 12, d: 10, h: 6.5, rot: Math.PI, color: 0x7c3aed, type: "Restaurant" },
            { x: 660, z: 28, w: 10, d: 8, h: 5.0, rot: Math.PI, color: 0x0891b2, type: "Beach Store" }
        ];

        for (const s of shopDefinitions) {
            const group = new THREE.Group();
            
            // Shop Main Building
            const bodyGeo = new THREE.BoxGeometry(s.w, s.h, s.d);
            const bodyMat = new THREE.MeshStandardMaterial({ color: s.color, roughness: 0.6, metalness: 0.2 });
            const body = new THREE.Mesh(bodyGeo, bodyMat);
            body.position.y = s.h / 2;
            body.castShadow = true;
            body.receiveShadow = true;
            group.add(body);

            // Front Storefront Awning
            const awningGeo = new THREE.BoxGeometry(s.w + 0.4, 0.35, 1.8);
            const awningMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.4 });
            const awning = new THREE.Mesh(awningGeo, awningMat);
            awning.position.set(0, s.h * 0.65, s.d / 2 + 0.7);
            group.add(awning);

            // Storefront Signboard
            const signGeo = new THREE.BoxGeometry(s.w * 0.8, 0.7, 0.15);
            const signMat = new THREE.MeshBasicMaterial({ color: 0x0f172a });
            const sign = new THREE.Mesh(signGeo, signMat);
            sign.position.set(0, s.h * 0.85, s.d / 2 + 0.12);
            group.add(sign);

            // Front Glass Window
            const glassGeo = new THREE.BoxGeometry(s.w * 0.75, s.h * 0.45, 0.1);
            const glassMat = new THREE.MeshStandardMaterial({ color: 0x38bdf8, roughness: 0.1, metalness: 0.8 });
            const glass = new THREE.Mesh(glassGeo, glassMat);
            glass.position.set(0, s.h * 0.3, s.d / 2 + 0.08);
            group.add(glass);

            group.position.set(s.x, 0, s.z);
            group.rotation.y = s.rot;
            this.scene.add(group);
            this.roadsideShopMeshes.push(group);
        }
    }

    buildCityBuildings() {
        const mats = [
            new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.8 }),
            new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.7 }),
            new THREE.MeshStandardMaterial({ color: 0x475569, roughness: 0.6 })
        ];

        const buildingPositions = [
            { x: 140, z: -680, w: 40, d: 35, h: 22 },
            { x: 190, z: -550, w: 45, d: 40, h: 28 },
            { x: 150, z: -400, w: 40, d: 35, h: 18 },
            { x: 170, z: -250, w: 45, d: 40, h: 26 },
            { x: 520, z: -780, w: 50, d: 35, h: 25 },
            { x: 640, z: -750, w: 55, d: 40, h: 30 }
        ];

        for (const b of buildingPositions) {
            const geo = new THREE.BoxGeometry(b.w, b.h, b.d);
            const mat = mats[Math.floor(Math.random() * mats.length)];
            const mesh = new THREE.Mesh(geo, mat);
            mesh.position.set(b.x, b.h / 2, b.z);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            this.scene.add(mesh);
        }
    }

    update(state) {
        if (!state) return;
        this.state = state;
        this.updateRoadVisualization(state);
        const delta = this.clock.getDelta();
        this.animTime += delta;

        // 1. Update Scenario Atmosphere (Day / Event Floodlights)
        const isEvent = state.scenario === 'event_day';
        for (const ft of this.floodlightTowers) {
            ft.light.intensity = isEvent ? 3.0 : 0.0;
            ft.headMat.emissiveIntensity = isEvent ? 1.8 : 0.2;
        }

        // 2. Update Moving 3D Vehicles
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

    setLayer(layer, enabled) {
        if (!(layer in this.layers)) return;
        this.layers[layer] = enabled;
        if (layer === 'vehicles') this.vehicleMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (layer === 'pedestrians') this.pedestrianMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (layer === 'signals') this.signalMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (layer === 'buildings' && this.stadiumMeshGroup) this.stadiumMeshGroup.visible = enabled;
        if (layer === 'shops') this.roadsideShopMeshes.forEach(mesh => { mesh.visible = enabled; });
        if (this.state) this.updateRoadVisualization(this.state);
    }

    updateRoadVisualization(state) {
        const congestion = state.edges_congestion || {};
        for (const [edgeId, meshes] of this.roadMeshes.entries()) {
            const reading = congestion[edgeId];
            let color = this.baseRoadColor;
            if (this.layers.congestion && reading) {
                const ratio = Number(reading.speed_ratio);
                color = ratio > 0.75 ? 0x16a34a : ratio > 0.5 ? 0xeab308 : ratio > 0.25 ? 0xf97316 : 0xdc2626;
            }
            if (this.layers.routes && this.selectedEdges.has(edgeId)) color = 0x22d3ee;
            if (this.layers.vipRoute && this.vipEdges.has(edgeId)) color = 0xfacc15;
            if (this.layers.construction && this.constructionEdges.has(edgeId)) color = 0xf97316;
            if (this.layers.actions && this.actionEdges.has(edgeId)) color = 0xa78bfa;
            for (const mesh of meshes) mesh.material.color.setHex(color);
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

            const elev = v.type === 'train' ? 8.1 : 0.25;
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
            const bodyGeo = new THREE.BoxGeometry(2.5, 3.2, 10.5);
            const body = new THREE.Mesh(bodyGeo, busMat);
            body.position.y = 1.6;
            body.castShadow = true;
            group.add(body);

            const destMat = new THREE.MeshBasicMaterial({ color: 0xfef08a });
            const destGeo = new THREE.BoxGeometry(2.0, 0.5, 0.4);
            const dest = new THREE.Mesh(destGeo, destMat);
            dest.position.set(0, 3.0, -5.2);
            group.add(dest);
        } else if (vType === 'motorcycle') {
            const bikeMat = new THREE.MeshStandardMaterial({ color: 0xf97316, metalness: 0.7, roughness: 0.3 });
            const bodyGeo = new THREE.BoxGeometry(0.8, 1.2, 2.0);
            const body = new THREE.Mesh(bodyGeo, bikeMat);
            body.position.y = 0.6;
            body.castShadow = true;
            group.add(body);
        } else {
            const carColor = vType === 'taxi' ? 0xeab308 : 0x06b6d4;
            const carMat = new THREE.MeshStandardMaterial({ color: carColor, metalness: 0.6, roughness: 0.3 });
            const chassisGeo = new THREE.BoxGeometry(1.8, 0.8, 4.4);
            const chassis = new THREE.Mesh(chassisGeo, carMat);
            chassis.position.y = 0.5;
            chassis.castShadow = true;
            group.add(chassis);

            const cabinMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.1, metalness: 0.9 });
            const cabinGeo = new THREE.BoxGeometry(1.5, 0.65, 2.3);
            const cabin = new THREE.Mesh(cabinGeo, cabinMat);
            cabin.position.set(0, 1.1, -0.2);
            group.add(cabin);

            const headMat = new THREE.MeshBasicMaterial({ color: 0xfffee0 });
            const hGeo = new THREE.BoxGeometry(0.3, 0.2, 0.1);
            const hL = new THREE.Mesh(hGeo, headMat);
            hL.position.set(-0.6, 0.5, -2.2);
            const hR = new THREE.Mesh(hGeo, headMat);
            hR.position.set(0.6, 0.5, -2.2);
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
                this.scene.add(signalMesh);
            }

            const bulbs = signalMesh.userData.bulbs;
            if (bulbs) {
                bulbs.red.material.emissiveIntensity = tl.color === 'red' ? 1.8 : 0.1;
                bulbs.yellow.material.emissiveIntensity = tl.color === 'yellow' ? 1.8 : 0.1;
                bulbs.green.material.emissiveIntensity = tl.color === 'green' ? 1.8 : 0.1;
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

        if (preset === 'overview') {
            this.camera.position.set(450, 750, -100);
            this.controls.target.set(440, 0, -400);
        } else if (preset === 'stadium') {
            this.camera.position.set(440, 160, -220);
            this.controls.target.set(440, 15, -440);
        } else if (preset === 'station') {
            this.camera.position.set(560, 60, -300);
            this.controls.target.set(520, 10, -390);
        } else if (preset === 'junction') {
            this.camera.position.set(50, 70, -680);
            this.controls.target.set(50, 0, -780);
        } else if (preset === 'bus_stop') {
            this.camera.position.set(370, 40, -480);
            this.controls.target.set(348, 2, -530);
        } else if (preset === 'beach') {
            this.camera.position.set(820, 90, -180);
            this.controls.target.set(748, 0, -260);
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

        if (this.waterMesh) {
            const time = this.clock.getElapsedTime();
            this.waterMesh.position.y = -0.05 + Math.sin(time * 1.5) * 0.1;
        }

        this.renderer.render(this.scene, this.camera);
    }
}
