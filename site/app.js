
const map = L.map('map', {
    center: [45.528144, -73.606535],
    zoom: 14,
    zoomControl: true,         // Enables the zoom +/- buttons
    dragging: true,            // Allows panning with mouse/touch
    scrollWheelZoom: true,     // Allows zooming with mouse wheel
    doubleClickZoom: true,     // Allows zooming with double click
    boxZoom: true,             // Enables box zoom
    touchZoom: true            // Enables pinch zoom on mobile
}); /// i've added the above features bc zoom/panning has been unreliable

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 20
}).addTo(map);

let streetsData = null;

// --- Load the road network GeoJSON ---
fetch('data/roadnetwork_clipped_pedestrian_default.geojson')
    // this is a roadnetwork file that has been clipped to save resources and 
    // to focus on the study area. Tool used : https://mapshaper.org to save as csv, then https://geojson.io to convert csv to geojson
    .then(r => r.json())
    .then(roads => {
        streetsData = roads;

        // Add the street network to the map
        L.geoJSON(roads, {
            style: {
                color: '#FFFFFF',
                weight: 3,
                opacity: 0.9
            }
        }).addTo(map);
    })
    .catch(err => console.error("❌ Error loading roads GeoJSON:", err));


// --- Load the crossings (points) GeoJSON ---
fetch('data/places.geojson')
    .then(r => r.json())
    .then(crossings => {
        // Add the crossing points directly
        L.geoJSON(crossings, {
            pointToLayer: function (feature, latlng) {
                // Set color based on category field
                let category = feature.properties.category;
                let color;

                // setting point colour based on type of crossing
                switch (category) {
                    case 'Under_Construction':
                        color = '#f7f793';
                        break;
                    case 'Formal_Crossing':
                        color = '#62b955ff';
                        break;
                    case 'Informal_Crossing':
                        color = '#82ee71ff';
                        break;
                }

                // Create and return the marker with the color based on category
                return L.circleMarker(latlng, {
                    radius: 10,  // Adjust size of the marker
                    fillColor: color,
                    color: 'black',  // Border color
                    weight: 2,     // Border width
                    opacity: 0.5,    // Border opacity
                    fillOpacity: 1.0,  // Fill opacity
                    pane: 'markerPane' // according to chatGPT, this is how i ensure proper layering 
                    // of symbols
                });
            },
            onEachFeature: function (feature, layer) {
                // Check if the feature has name and description
                if (feature.properties && feature.properties.name && feature.properties.description) {
                    layer.bindPopup(
                        `<strong>${feature.properties.name}</strong><br>${feature.properties.description}`
                    );
                }
            }
        }).addTo(map);
    })
    .catch(err => console.error("❌ Error loading crossings GeoJSON:", err));
// --- Load reachable lines for 400m + 800m ---
let reachable400 = null;
let reachable800 = null;
let reachableLayer400 = null;
let reachableLayer800 = null;

// Load 400m file
fetch('data/reachable_lines_400m.geojson')
    .then(r => r.json())
    .then(data => {
        reachable400 = data;
        console.log("✅ 400m reachable lines loaded:", reachable400.features.length);
    });

// Load 800m file
fetch('data/reachable_lines_800m.geojson')
    .then(r => r.json())
    .then(data => {
        reachable800 = data;
        console.log("✅ 800m reachable lines loaded:", reachable800.features.length);
    });

// --- Click interaction on crossings (same as your code, modified slightly) ---
fetch('data/places.geojson')
    .then(r => r.json())
    .then(crossings => {
        L.geoJSON(crossings, {
            pointToLayer: function (feature, latlng) {
                let color;
                switch (feature.properties.category) {
                    case 'Under_Construction': color = '#f7f793'; break;
                    case 'Formal_Crossing': color = '#62b955ff'; break;
                    case 'Informal_Crossing': color = '#82ee71ff'; break;
                }
                return L.circleMarker(latlng, {
                    radius: 10,
                    fillColor: color,
                    color: 'black',
                    weight: 2,
                    opacity: 0.5,
                    fillOpacity: 1.0,
                    pane: 'markerPane'
                });
            },
            onEachFeature: function (feature, layer) {
                const name = feature.properties.name;
                const desc = feature.properties.description;

                layer.on('click', function () {
                    document.getElementById('info-name').textContent = name || "Unnamed crossing";
                    document.getElementById('info-desc').textContent = desc || "No description available.";

                    // Make sure data exists
                    if (!reachable400 || !reachable800) {
                        console.warn("🚧 Walkshed files not fully loaded yet.");
                        return;
                    }

                    // Remove previous layers
                    if (reachableLayer400) map.removeLayer(reachableLayer400);
                    if (reachableLayer800) map.removeLayer(reachableLayer800);

                    // Filter 400m & 800m features for this crossing
                    const filtered400 = {
                        ...reachable400,
                        features: reachable400.features.filter(f => f.properties.crossing_name === name)
                    };
                    const filtered800 = {
                        ...reachable800,
                        features: reachable800.features.filter(f => f.properties.crossing_name === name)
                    };

                    // Add 800m first (light orange)
                    reachableLayer800 = L.geoJSON(filtered800, {
                        style: {
                            color: '#ec9696ff',     // light pink
                            weight: 3,
                            opacity: 1.0
                        }
                    }).addTo(map);

                    // Add 400m second (darker orange on top)
                    reachableLayer400 = L.geoJSON(filtered400, {
                        style: {
                            color: '#f05f5fff',     
                            weight: 4,
                            opacity: 1.0
                        }
                    }).addTo(map);

                    // Fit to the larger (800m) extent if available
                    if (filtered800.features.length > 0) {
                        map.fitBounds(reachableLayer800.getBounds());
                    } else if (filtered400.features.length > 0) {
                        map.fitBounds(reachableLayer400.getBounds());
                    }

                    console.log(`✅ Showing walksheds for "${name}" (400m + 800m)`);
                });
            }
        }).addTo(map);
    });

// --- Information box code ---
document.addEventListener("DOMContentLoaded", function () {
    // Your tab switching function
    window.openTab = function(evt, tabId) {
        const pages = document.getElementsByClassName("tab-page");
        for (let i = 0; i < pages.length; i++) {
            pages[i].style.display = "none";
        }

        const tabs = document.getElementsByClassName("tab-link");
        for (let i = 0; i < tabs.length; i++) {
            tabs[i].classList.remove("active");
        }

        document.getElementById(tabId).style.display = "block";
        evt.currentTarget.classList.add("active");
    };
});
