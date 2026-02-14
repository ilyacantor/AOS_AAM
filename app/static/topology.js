/**
 * AAM Topology Visualization
 *
 * Renders the interactive vis.js network graph on the /ui/topology page.
 * Extracted from the Python f-string monolith for maintainability.
 */

let network = null;
let allNodes = [];
let allEdges = [];
let physicsEnabled = true;

const nodeColors = {
    fabric_plane: {
        'IPAAS': '#22d3ee',
        'API_GATEWAY': '#a78bfa',
        'EVENT_BUS': '#f97316',
        'DATA_WAREHOUSE': '#10b981'
    },
    pipe: '#60a5fa',
    source_system: '#94a3b8',
    candidate: '#c084fc'
};

const nodeShapes = {
    fabric_plane: 'diamond',
    pipe: 'dot',
    source_system: 'square',
    candidate: 'triangle'
};

async function loadTopology(fabricFilter = 'all', sorFilter = 'all', detailLevel = 'summary') {
    let url = '/api/topology/summary';

    if (detailLevel === 'all') {
        url = '/api/topology';
    } else if (fabricFilter !== 'all') {
        url = `/api/topology/plane/${fabricFilter}`;
    }

    const response = await fetch(url);
    let data = await response.json();

    // Apply SOR filter client-side
    if (sorFilter !== 'all') {
        if (sorFilter === 'show') {
            // Show only SOR nodes
            data.nodes = data.nodes.filter(n =>
                n.metadata && n.metadata.is_sor === true || n.type === 'fabric_plane'
            );
        } else if (sorFilter === 'hide') {
            // Hide SOR nodes
            data.nodes = data.nodes.filter(n =>
                !n.metadata || n.metadata.is_sor !== true
            );
        }
        // Filter edges to only those with both nodes present
        const nodeIds = new Set(data.nodes.map(n => n.id));
        data.edges = data.edges.filter(e =>
            nodeIds.has(e.source) && nodeIds.has(e.target)
        );
    }

    allNodes = data.nodes.map(n => {
        let color = n.type === 'fabric_plane'
            ? nodeColors.fabric_plane[n.metadata.plane_type] || '#64748b'
            : nodeColors[n.type] || '#64748b';
        let borderWidth = 1;
        let borderColor = undefined;
        if (n.metadata && n.metadata.is_authoritative) {
            color = '#f59e0b';
            borderWidth = 3;
            borderColor = '#fbbf24';
        }
        return {
            id: n.id,
            label: n.label,
            shape: nodeShapes[n.type] || 'dot',
            color: borderColor ? { background: color, border: borderColor } : color,
            borderWidth: borderWidth,
            size: n.type === 'fabric_plane' ? 30 : (n.type === 'pipe' ? 20 : 15),
            font: { color: '#ffffff', size: 12 },
            title: buildTooltip(n),
            nodeData: n
        };
    });

    allEdges = data.edges.map(e => ({
        id: e.id,
        from: e.source,
        to: e.target,
        color: { color: '#475569', opacity: 0.6 },
        width: e.type === 'candidate_to_pipe' ? 2 : 1,
        dashes: e.type === 'candidate_for_source',
        arrows: { to: { enabled: true, scaleFactor: 0.5 } }
    }));

    // Update stats
    if (data.stats) {
        // Canonical KPIs: Pipes (= candidates), Fabrics, SORs
        document.getElementById('stat-pipes').textContent = data.stats.total_candidates || 0;
        document.getElementById('stat-fabrics').textContent = data.stats.fabrics || 0;
        document.getElementById('stat-sors').textContent = data.stats.sors || 0;
        document.getElementById('stat-drift').textContent = data.stats.pipes_with_drift || 0;
    }

    renderNetwork();
}

function buildTooltip(node) {
    let lines = [node.label.replace('\n', ' — ')];
    if (node.type === 'fabric_plane') {
        if (node.metadata.vendor) lines.push('Vendor: ' + node.metadata.vendor);
        lines.push('Type: ' + (node.metadata.plane_type || 'unknown'));
        if (node.metadata.connected !== undefined) lines.push('Connected: ' + node.metadata.connected + ' / ' + node.metadata.total);
    } else if (node.type === 'source_system') {
        if (node.metadata.is_authoritative) lines.push('Farm-Authoritative SOR');
        else if (node.metadata.is_sor) lines.push('SOR (candidate-derived)');
        if (node.metadata.domain) lines.push('Domain: ' + node.metadata.domain);
        if (node.metadata.confidence) lines.push('Confidence: ' + node.metadata.confidence);
        if (node.metadata.category) lines.push('Category: ' + node.metadata.category);
        if (node.metadata.connected !== undefined) lines.push('Connected: ' + node.metadata.connected + ' / ' + node.metadata.total);
    } else {
        if (node.metadata.fabric_plane) lines.push('Plane: ' + node.metadata.fabric_plane);
        if (node.metadata.source_system) lines.push('Source: ' + node.metadata.source_system);
        if (node.metadata.category) lines.push('Category: ' + node.metadata.category);
        if (node.metadata.status) lines.push('Status: ' + node.metadata.status);
    }
    return lines.join('\n');
}

function renderNetwork() {
    const container = document.getElementById('topology-container');
    const data = {
        nodes: new vis.DataSet(allNodes),
        edges: new vis.DataSet(allEdges)
    };

    const options = getLayoutOptions();

    network = new vis.Network(container, data, options);

    network.on('click', function(params) {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const node = allNodes.find(n => n.id === nodeId);
            if (node) showNodeDetails(node);
        } else {
            closeDetails();
        }
    });

    network.on('doubleClick', function(params) {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            const node = allNodes.find(n => n.id === nodeId);
            if (node && node.nodeData.type === 'pipe') {
                window.location.href = `/ui/pipes/${node.nodeData.metadata.pipe_id}`;
            }
        }
    });
}

function getLayoutOptions() {
    const layoutType = document.getElementById('layout-select').value;

    const baseOptions = {
        nodes: {
            borderWidth: 2,
            shadow: true
        },
        edges: {
            smooth: { type: 'continuous' }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            zoomView: true,
            dragView: true
        }
    };

    if (layoutType === 'hierarchical') {
        return {
            ...baseOptions,
            layout: {
                hierarchical: {
                    direction: 'UD',
                    sortMethod: 'hubsize',
                    levelSeparation: 100,
                    nodeSpacing: 150
                }
            },
            physics: false
        };
    } else if (layoutType === 'circular') {
        return {
            ...baseOptions,
            layout: {
                improvedLayout: true
            },
            physics: {
                enabled: true,
                solver: 'repulsion',
                repulsion: {
                    nodeDistance: 200
                }
            }
        };
    } else {
        return {
            ...baseOptions,
            physics: {
                enabled: true,
                solver: 'forceAtlas2Based',
                forceAtlas2Based: {
                    gravitationalConstant: -50,
                    springLength: 100,
                    springConstant: 0.08
                },
                stabilization: { iterations: 100 }
            }
        };
    }
}

function showNodeDetails(node) {
    const details = document.getElementById('node-details');
    const title = document.getElementById('detail-title');
    const content = document.getElementById('detail-content');

    title.textContent = node.label;

    let html = `<div class="field"><div class="field-label">Type</div><div class="field-value">${node.nodeData.type}</div></div>`;

    const meta = node.nodeData.metadata;
    for (const [key, value] of Object.entries(meta)) {
        if (value && key !== 'central' && key !== 'color') {
            let displayValue = value;
            if (Array.isArray(value)) {
                displayValue = value.length > 0 ? value.join(', ') : '(none)';
            }
            const label = key.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
            html += `<div class="field"><div class="field-label">${label}</div><div class="field-value">${displayValue}</div></div>`;
        }
    }

    if (node.nodeData.type === 'pipe') {
        html += `<div style="margin-top:12px;"><a href="/ui/pipes/${meta.pipe_id}" class="btn btn-sm">View Pipe Details</a></div>`;
    }

    content.innerHTML = html;
    details.classList.add('visible');
}

function closeDetails() {
    document.getElementById('node-details').classList.remove('visible');
}

function applyTopologyFilters() {
    const assetFilter = document.getElementById('asset-filter').value;
    const detailLevel = document.getElementById('detail-filter').value;

    // Map single filter to fabric/sor parameters
    let fabricFilter = 'all';
    let sorFilter = 'all';

    if (assetFilter === 'sors') {
        sorFilter = 'show';
    } else if (assetFilter === 'fabrics') {
        fabricFilter = 'all';
        sorFilter = 'hide';
    } else if (assetFilter !== 'all') {
        // Specific fabric type
        fabricFilter = assetFilter;
    }

    loadTopology(fabricFilter, sorFilter, detailLevel);
}

var _lastLayout = 'physics';
function handleLayoutAction(val) {
    const sel = document.getElementById('layout-select');
    if (val === '_fit') {
        if (network) network.fit();
        sel.value = _lastLayout;
        return;
    }
    if (val === '_unlock') {
        togglePhysics();
        sel.value = _lastLayout;
        return;
    }
    _lastLayout = val;
    renderNetwork();
}

function changeLayout() {
    renderNetwork();
}

function resetView() {
    document.getElementById('asset-filter').value = 'all';
    document.getElementById('detail-filter').value = 'full';
    document.getElementById('layout-select').value = 'physics';
    _lastLayout = 'physics';
    physicsEnabled = true;
    loadTopology('all');
}

function fitToScreen() {
    if (network) network.fit();
}

function refreshData() {
    applyTopologyFilters();
}

function togglePhysics() {
    physicsEnabled = !physicsEnabled;
    const btn = document.getElementById('physics-toggle');

    if (physicsEnabled) {
        btn.textContent = 'Unlock Positions';
        btn.classList.remove('btn-warning');
        if (network) {
            network.setOptions({ physics: getLayoutOptions().physics });
        }
    } else {
        btn.textContent = 'Lock Positions';
        btn.classList.add('btn-warning');
        if (network) {
            // Disable physics - nodes stay where you put them
            network.setOptions({ physics: false });
        }
    }
}

// Initialize
loadTopology();
