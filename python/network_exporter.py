import sumolib
import xml.etree.ElementTree as ET
from .config import NET_FILE, ADDITIONAL_FILE

def get_network_geometry():
    """
    Exports full network topology, lane polylines, junction coordinates,
    bus stops, pedestrian crossings, and landmark polygons for the UI renderer.
    """
    net = sumolib.net.readNet(NET_FILE)
    bbox = net.getBBoxXY()
    network_root = ET.parse(NET_FILE).getroot()
    location = network_root.find("location")
    raw_offset = (location.get("netOffset", "0,0") if location is not None else "0,0").split(",")
    net_offset = (float(raw_offset[0]), float(raw_offset[1])) if len(raw_offset) >= 2 else (0.0, 0.0)
    node_elevations = {
        node.get("id"): float(node.get("z", 0.0))
        for node in network_root.findall("junction")
    }
    lane_elevations = {}
    lane_shapes_3d = {}
    for edge_node in network_root.findall("edge"):
        from_z = node_elevations.get(edge_node.get("from"), 0.0)
        to_z = node_elevations.get(edge_node.get("to"), 0.0)
        for lane_node in edge_node.findall("lane"):
            tokens = lane_node.get("shape", "").split()
            points_3d = []
            has_explicit_z = False
            explicit_z = []
            for index, token in enumerate(tokens):
                coords = token.split(",")
                if len(coords) < 2:
                    continue
                try:
                    x, y = float(coords[0]), float(coords[1])
                    if len(coords) > 2:
                        z = float(coords[2]); has_explicit_z = True; explicit_z.append(z)
                    else:
                        fraction = index / max(1, len(tokens) - 1)
                        z = from_z + (to_z - from_z) * fraction
                    points_3d.append([round(x, 2), round(y, 2), round(z, 2)])
                except ValueError:
                    continue
            if explicit_z:
                lane_elevations[lane_node.get("id")] = round(sum(explicit_z) / len(explicit_z), 2)
            elif points_3d:
                lane_elevations[lane_node.get("id")] = round(
                    sum(point[2] for point in points_3d) / len(points_3d), 2)
            if has_explicit_z or abs(from_z - to_z) > 1e-6:
                lane_shapes_3d[lane_node.get("id")] = points_3d

    # 1. Regular Edges and Lanes
    edges_data = []
    for e in net.getEdges():
        if e.isSpecial():
            continue
        lanes_data = []
        for l in e.getLanes():
            lane_shape = l.getShape()
            lane_data = {
                "id": l.getID(),
                "shape": [[round(pt[0], 2), round(pt[1], 2)] for pt in lane_shape],
                # SUMO networks may carry a real z coordinate (e.g. the
                # elevated Chepauk MRTS). Preserve it instead of flattening it
                # in the geometry API; 2D shapes remain at ground level.
                "elevation": lane_elevations.get(l.getID(), round(
                    sum(pt[2] for pt in lane_shape if len(pt) > 2) /
                    max(1, sum(1 for pt in lane_shape if len(pt) > 2)), 2)),
                "width": round(l.getWidth(), 2),
                "speed": round(l.getSpeed(), 2),
                "allow": list(l.getPermissions())
            }
            if l.getID() in lane_shapes_3d:
                lane_data["shape_3d"] = lane_shapes_3d[l.getID()]
            lanes_data.append(lane_data)
        edges_data.append({
            "id": e.getID(),
            "type": e.getType(),
            "from": e.getFromNode().getID(),
            "to": e.getToNode().getID(),
            "lanes": lanes_data
        })

    # 2. Nodes / Junctions
    nodes_data = []
    for n in net.getNodes():
        nodes_data.append({
            "id": n.getID(),
            "x": round(n.getCoord()[0], 2),
            "y": round(n.getCoord()[1], 2),
            "type": n.getType(),
            "shape": [[round(pt[0], 2), round(pt[1], 2)] for pt in n.getShape()] if n.getShape() else []
        })

    # 3. Pedestrian Crossings (Parsed directly from network XML internal edges)
    crossings_data = []
    try:
        for e in network_root.findall("edge"):
            func = e.get("function")
            if func == "crossing":
                for lane in e.findall("lane"):
                    raw_shape = lane.get("shape", "")
                    pts = []
                    for pair in raw_shape.strip().split():
                        if "," in pair:
                            x, y = pair.split(",")
                            pts.append([round(float(x), 2), round(float(y), 2)])
                    crossings_data.append({
                        "id": lane.get("id"),
                        "width": float(lane.get("width", 3.0)),
                        "shape": pts
                    })
    except Exception as ex:
        print(f"Warning extracting crossings: {ex}")

    # 4. Additionals: Bus Stops, Train Stops, Landmarks, Polygons
    bus_stops_data = []
    polygons_data = []
    try:
        tree = ET.parse(ADDITIONAL_FILE)
        root = tree.getroot()
        for bs in root.findall("busStop"):
            bus_stops_data.append({
                "id": bs.get("id"),
                "name": bs.get("name", bs.get("id")),
                "lane": bs.get("lane"),
                "startPos": float(bs.get("startPos", 0)),
                "endPos": float(bs.get("endPos", 0)),
                "lines": bs.get("lines", "").split()
            })
        for poly in root.findall("poly"):
            raw_shape = poly.get("shape", "")
            pts = []
            for pair in raw_shape.strip().split():
                if "," in pair:
                    x, y = pair.split(",")
                    pts.append([float(x), float(y)])
            
            raw_color = poly.get("color", "100,100,100,150").split(",")
            r = int(raw_color[0]) if len(raw_color) > 0 else 100
            g = int(raw_color[1]) if len(raw_color) > 1 else 100
            b = int(raw_color[2]) if len(raw_color) > 2 else 100
            a = float(raw_color[3]) / 255.0 if len(raw_color) > 3 else 0.5
            
            # Netconvert has already moved network geometry by netOffset. The
            # additional.xml polygons are authored in source-network coordinates,
            # so move their vertices into the same SUMO coordinate frame here.
            aligned_pts = [[round(x + net_offset[0], 2), round(y + net_offset[1], 2)] for x, y in pts]
            polygons_data.append({
                "id": poly.get("id"),
                "shape": aligned_pts,
                "color": f"rgba({r},{g},{b},{a})",
                "layer": int(poly.get("layer", 0))
            })
    except Exception as ex:
        print(f"Warning loading additionals geometry: {ex}")

    return {
        "bbox": {
            "min_x": round(bbox[0][0], 2),
            "min_y": round(bbox[0][1], 2),
            "max_x": round(bbox[1][0], 2),
            "max_y": round(bbox[1][1], 2)
        },
        "coordinate_frame": {"net_offset": [round(net_offset[0], 2), round(net_offset[1], 2)]},
        "edges": edges_data,
        "nodes": nodes_data,
        "crossings": crossings_data,
        "bus_stops": bus_stops_data,
        "polygons": polygons_data
    }
