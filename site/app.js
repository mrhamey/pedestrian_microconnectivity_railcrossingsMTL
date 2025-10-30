
const map = L.map('map', {
    center: [45.528144, -73.606535],
    zoom: 15,
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
                color: 'blue',
                weight: 3,
                opacity: 0.5
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
                        color = 'yellow';
                        break;
                    case 'Formal_Crossing':
                        color = 'green';
                        break;
                    case 'Informal_Crossing':
                        color = 'red';
                        break;
                }

                // Create and return the marker with the color based on category
                return L.circleMarker(latlng, {
                    radius: 10,  // Adjust size of the marker
                    fillColor: color,
                    color: 'black',  // Border color
                    weight: 2,     // Border width
                    opacity: 1,    // Border opacity
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
// --- Load and handle reachable lines ---
let reachableLayer = null;
let allReachables = null;

// 1️⃣ Load all reachable lines once
fetch('data/reachable_lines_all.geojson')
    .then(r => r.json())
    .then(data => {
        allReachables = data;
        console.log("✅ Reachable lines data loaded:", allReachables.features.length);
    })
    .catch(err => console.error("❌ Error loading reachable lines:", err));


// 2️⃣ Once crossings load, attach click events for filtering
fetch('data/places.geojson')
    .then(r => r.json())
    .then(crossings => {
        L.geoJSON(crossings, {
            pointToLayer: function (feature, latlng) {
                let color;
                switch (feature.properties.category) {
                    case 'Under_Construction': color = 'yellow'; break;
                    case 'Formal_Crossing': color = 'green'; break;
                    case 'Informal_Crossing': color = 'red'; break;
                }
                return L.circleMarker(latlng, {
                    radius: 10,
                    fillColor: color,
                    color: 'black',
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 1.0,
                    pane: 'markerPane'
                });
            },
            onEachFeature: function (feature, layer) {
    const name = feature.properties.name;
    const desc = feature.properties.description;

    // When user clicks a crossing
    layer.on('click', function () {
        // 🪄 Update side panel instead of popup
        document.getElementById('info-name').textContent = name || "Unnamed crossing";
        document.getElementById('info-desc').textContent = desc || "No description available.";

        if (!allReachables) {
            console.warn("Reachable lines not loaded yet!");
            return;
        }

        // Remove existing reachable layer
        if (reachableLayer) {
            map.removeLayer(reachableLayer);
        }

        // Filter reachable lines
        const filtered = {
            ...allReachables,
            features: allReachables.features.filter(
                f => f.properties.crossing_name === name
            )
        };

        if (filtered.features.length === 0) {
            document.getElementById('info-desc').textContent += "\nNo reachable lines found.";
            return;
        }

        // Add new reachable lines to map
        reachableLayer = L.geoJSON(filtered, {
            style: {
                color: 'orange',
                weight: 4,
                opacity: 1.0
            }
        }).addTo(map);

        // Optional zoom to show lines
        map.fitBounds(reachableLayer.getBounds());

        console.log(`✅ Showing ${filtered.features.length} reachable lines for "${name}"`);
    });
}
        }).addTo(map);
    })
    .catch(err => console.error("❌ Error loading crossings:", err));

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
