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

# ---------------------------------------------------
# Define distance values (400 m and 800 m)
# ---------------------------------------------------
walk_distances = [400, 800]

# ---------------------------------------------------
# Load all crossings
# ---------------------------------------------------
places = gpd.read_file("data/places.geojson")
print(f"Loaded {len(places)} crossings from places.geojson")
print("Places CRS:", places.crs)

# ---------------------------------------------------
# Loop over each distance (400 m, 800 m)
# ---------------------------------------------------
for max_distance in walk_distances:
    print(f"\n============================")
    print(f"🚶 Starting walkshed for {max_distance} m")
    print(f"============================")

    all_reachable = []

    # ---------------------------------------------------
    # Loop through each crossing
    # ---------------------------------------------------
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

        # --- Reproject place to same CRS ---
        start_point = place.geometry
        if places.crs != roads.crs:
            start_point = gpd.GeoSeries([start_point], crs=places.crs).to_crs(roads.crs).iloc[0]

        # --- Repair near-touching geometries ---
        network_union = union_all(roads.geometry)
        roads.geometry = roads.geometry.apply(lambda g: snap(g, network_union, tolerance=1))

        # --- Build graph ---
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
                    G.add_edge(p1, p2, fid=ridx, weight=dist)

        print("   Graph built with", len(G.nodes), "nodes and", len(G.edges), "edges")
        if len(G.nodes) == 0:
            print(f"⚠️ Empty graph for {crossing_name}, skipping.")
            continue

        # --- Nearest node lookup ---
        node_points = [Point(n) for n in G.nodes]
        tree = STRtree(node_points)
        try:
            nearest_idx = tree.nearest(start_point)
        except Exception:
            nearest_idx = tree.nearest(start_point.buffer(5))

        if isinstance(nearest_idx, (int, np.integer)):
            nearest_geom = node_points[nearest_idx]
        else:
            nearest_geom = nearest_idx

        if nearest_geom is None:
            print(f"⚠️ Could not find a nearest node for {crossing_name}, skipping.")
            continue

        start_node = (nearest_geom.x, nearest_geom.y)
        print("Start node found:", start_node)

        # --- Compute reachable nodes ---
        lengths = nx.single_source_dijkstra_path_length(G, start_node, cutoff=max_distance, weight="weight")
        print(f"   ✅ Found {len(lengths)} reachable nodes (within {max_distance} m)")

        # --- Clip segments ---
        reachable_edges = set()
        partial_segments = []

        for (u, v, data) in G.edges(data=True):
            u_dist = lengths.get(u)
            v_dist = lengths.get(v)

            if u_dist is not None and v_dist is not None:
                reachable_edges.add(data["fid"])
            elif u_dist is not None or v_dist is not None:
                inside_dist = u_dist if u_dist is not None else v_dist
                geom = roads.iloc[data["fid"]].geometry
                if geom is None:
                    continue

                edge_len = geom.length
                remaining = max_distance - inside_dist

                if remaining > 0 and remaining < edge_len:
                    try:
                        truncated = substring(geom, 0, remaining, normalized=False)
                        partial_segments.append({
                            "fid": data["fid"],
                            "geometry": truncated
                        })
                    except Exception as e:
                        print(f"   ⚠️ substring error on fid={data['fid']}: {e}")

        # Convert to GeoDataFrame
        partial_gdf = gpd.GeoDataFrame(partial_segments, geometry="geometry", crs=roads.crs) if partial_segments else \
                      gpd.GeoDataFrame(columns=["fid", "geometry"], geometry="geometry", crs=roads.crs)

        full_gdf = roads.loc[list(reachable_edges)].copy() if reachable_edges else \
                   gpd.GeoDataFrame(columns=roads.columns, geometry="geometry", crs=roads.crs)

        reachable_roads = pd.concat([full_gdf, partial_gdf], ignore_index=True, sort=False)
        reachable_roads = gpd.GeoDataFrame(reachable_roads, geometry="geometry", crs=roads.crs)

        # Add metadata
        reachable_roads["crossing_id"] = i
        reachable_roads["crossing_name"] = crossing_name
        reachable_roads["network_file"] = road_file
        reachable_roads["reachable_nodes"] = len(lengths)
        reachable_roads["max_distance"] = max_distance

        if not reachable_roads.empty:
            all_reachable.append(reachable_roads)

    # ---------------------------------------------------
    # Export combined file for this distance
    # ---------------------------------------------------
    if all_reachable:
        reachable_all = gpd.GeoDataFrame(pd.concat(all_reachable, ignore_index=True), crs=roads.crs)
        reachable_all = reachable_all.to_crs(epsg=4326)

        output_file = f"data/reachable_lines_{max_distance}m.geojson"
        if os.path.exists(output_file):
            backup = output_file.replace(".geojson", "_backup.geojson")
            os.replace(output_file, backup)
            print(f"Backed up existing file to {backup}")

        reachable_all.to_file(output_file, driver="GeoJSON")
        print(f"✅ Saved walkshed to {output_file} ({max_distance} m)")
    else:
        print(f"⚠️ No reachable lines computed for {max_distance} m")

print("\n✅ All distances complete.")
