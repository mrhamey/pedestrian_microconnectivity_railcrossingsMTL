import geopandas as gpd
import networkx as nx
from shapely.geometry import Point
from shapely.strtree import STRtree
from shapely import union_all
from shapely.ops import snap, substring
import numpy as np
import pandas as pd
import os

# ---------------------------------------------------
# Road network mapping per crossing name
# ---------------------------------------------------
network_map = {
    "De l’Epée Crossing": "data/roadnetwork_clipped_pedestrian_Delepeecrossing.geojson",
    "Skatepark Crossing": "data/roadnetwork_clipped_pedestrian_Skateparkcrossing.geojson",
    "Outdoor Gym Crossing": "data/roadnetwork_clipped_pedestrian_Gymcrossing.geojson",
    "Rue Cartier Crossing": "data/roadnetwork_clipped_pedestrian_Cartiercrossing.geojson",
}

default_network = "data/roadnetwork_clipped_pedestrian_default.geojson"
max_distance = 400  # meters along network

# ---------------------------------------------------
# Load all crossings
# ---------------------------------------------------
places = gpd.read_file("data/places.geojson")
print(f"Loaded {len(places)} crossings from places.geojson")
print("Places CRS:", places.crs)

# ---------------------------------------------------
# Loop through each crossing
# ---------------------------------------------------
all_reachable = []

for i, (idx, place) in enumerate(places.iterrows(), start=1):
    crossing_name = place.get("name", f"Crossing_{i}")
    print(f"\n➡️ Processing: {crossing_name}")

    # --- Select correct network file ---
    road_file = network_map.get(crossing_name, default_network)
    print(f"Using road network: {road_file}")

    if not os.path.exists(road_file):
        print(f"⚠️ Road file missing for {crossing_name}: {road_file} — skipping.")
        continue

    # --- Load and prepare road network ---
    roads = gpd.read_file(road_file).to_crs(epsg=3857)
    print("Roads CRS:", roads.crs)

    # --- Reproject place to same CRS (if needed) ---
    start_point = place.geometry
    if places.crs != roads.crs:
        start_point = gpd.GeoSeries([start_point], crs=places.crs).to_crs(roads.crs).iloc[0]

    # --- Repair near-touching geometries ---
    network_union = union_all(roads.geometry)
    roads.geometry = roads.geometry.apply(lambda g: snap(g, network_union, tolerance=1))

    # --- Build networkx graph (handles LineStrings + MultiLineStrings) ---
    G = nx.Graph()

    for ridx, row in roads.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        if geom.geom_type == "MultiLineString":
            lines = geom.geoms
        else:
            lines = [geom]

        for line in lines:
            coords = list(line.coords)
            for j in range(len(coords) - 1):
                p1, p2 = coords[j], coords[j + 1]
                dist = Point(p1).distance(Point(p2))
                # store the geometry index so we can retrieve it later
                G.add_edge(p1, p2, fid=ridx, weight=dist)

    print("   Graph built with", len(G.nodes), "nodes and", len(G.edges), "edges")

    if len(G.nodes) == 0:
        print(f"⚠️ Empty graph for {crossing_name}, skipping.")
        continue

    # --- Build spatial index for nearest node lookup ---
    node_points = [Point(n) for n in G.nodes]
    tree = STRtree(node_points)

    # robust nearest handling: STRtree.nearest may return index or geometry
    try:
        nearest_idx = tree.nearest(start_point)
    except Exception:
        # fallback: try small buffer search
        nearest_idx = tree.nearest(start_point.buffer(5))

    if isinstance(nearest_idx, (int, np.integer)):
        nearest_geom = node_points[nearest_idx]
    else:
        nearest_geom = nearest_idx

    # If nearest_geom is still None, skip
    if nearest_geom is None:
        print(f"⚠️ Could not find a nearest node for {crossing_name}, skipping.")
        continue

    start_node = (nearest_geom.x, nearest_geom.y)
    print("Start node found:", start_node)

    # --- Compute reachable network segment distances ---
    lengths = nx.single_source_dijkstra_path_length(G, start_node, cutoff=max_distance, weight="weight")
    print(f"   ✅ Found {len(lengths)} reachable nodes (within {max_distance} m)")

    # ---------------------------------------------------
    # Clip partial segments at the 400 m limit (if needed)
    # ---------------------------------------------------
    reachable_edges = set()
    partial_segments = []

    for (u, v, data) in G.edges(data=True):
        u_dist = lengths.get(u)
        v_dist = lengths.get(v)

        if u_dist is not None and v_dist is not None:
            # Entire edge is within cutoff
            reachable_edges.add(data['fid'])

        elif u_dist is not None or v_dist is not None:
            # Edge crosses the boundary (one node inside, one outside)
            inside_dist = u_dist if u_dist is not None else v_dist
            geom = roads.iloc[data['fid']].geometry

            # some geometries could be MultiLineString; handle by taking the first linestring if needed
            if geom is None:
                continue
            edge_len = geom.length

            remaining = max_distance - inside_dist

            if remaining > 0 and remaining < edge_len:
                try:
                    truncated = substring(geom, 0, remaining, normalized=False)
                    partial_segments.append({
                        'fid': data['fid'],
                        'geometry': truncated
                    })
                except Exception as e:
                    print(f"   ⚠️ substring error on fid={data['fid']}: {e}")

    # Convert partials to GeoDataFrame (may be empty)
    if partial_segments:
        partial_gdf = gpd.GeoDataFrame(partial_segments, geometry='geometry', crs=roads.crs)
    else:
        partial_gdf = gpd.GeoDataFrame(columns=['fid', 'geometry'], geometry='geometry', crs=roads.crs)

    # Combine clipped and full segments (may be empty)
    full_gdf = roads.loc[list(reachable_edges)].copy() if reachable_edges else gpd.GeoDataFrame(columns=roads.columns, geometry='geometry', crs=roads.crs)
    reachable_roads = pd.concat([full_gdf, partial_gdf], ignore_index=True, sort=False)
    reachable_roads = gpd.GeoDataFrame(reachable_roads, geometry='geometry', crs=roads.crs)

    # Add metadata fields
    reachable_roads["crossing_id"] = i
    reachable_roads["crossing_name"] = crossing_name
    reachable_roads["network_file"] = road_file
    reachable_roads["reachable_nodes"] = len(lengths)

    print(f"   Reachable edges (full): {len(full_gdf)}")
    print(f"   Partial clipped segments: {len(partial_gdf)}")
    print(f"   Total features to append: {len(reachable_roads)}")

    # Append only if there is geometry
    if not reachable_roads.empty:
        all_reachable.append(reachable_roads)
    else:
        print(f"⚠️ No reachable segments for {crossing_name} — nothing appended.")

# ---------------------------------------------------
# Combine all results and export
# ---------------------------------------------------
if all_reachable:
    # Combine all sub-results
    reachable_all = gpd.GeoDataFrame(pd.concat(all_reachable, ignore_index=True), crs=roads.crs)

    # Reset index to avoid duplicate feature id warnings on write
    reachable_all.reset_index(drop=True, inplace=True)

    # ✅ Reproject to WGS84 for Leaflet (EPSG:4326)
    if reachable_all.crs != "EPSG:4326":
        reachable_all = reachable_all.to_crs(epsg=4326)

    # Export (backup existing file)
    output_file = "data/reachable_lines_all.geojson"
    if os.path.exists(output_file):
        backup = output_file.replace(".geojson", "_backup.geojson")
        os.replace(output_file, backup)
        print(f"Backed up existing file to {backup}")

    reachable_all.to_file(output_file, driver="GeoJSON")

    print(f"\n✅ Saved combined reachable lines to {output_file}")
    print(f"📏 CRS of saved file: {reachable_all.crs}")
else:
    print("⚠️ No reachable lines computed — check your inputs.")
