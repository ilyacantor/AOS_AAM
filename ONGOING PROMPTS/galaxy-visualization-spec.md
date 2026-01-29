# Galaxy Visualization Specification

This document describes the visual behavior, node interactions, and movement physics for the Galaxy orbital visualization in the AOS Intent Map application.

---

## Overview

The Galaxy View displays query hypotheses as nodes orbiting a central persona indicator. Nodes are positioned based on their type (primary, hypothesis, secondary) and are continuously simulated using D3.js force physics.

---

## Visual Structure

### Background Layers

1. **Base Background**: Solid dark color `#080b12`
2. **Starfield Pattern**: Randomly generated stars (30 per 100x100px tile)
   - Star size: 0.3-1.8px radius
   - Star opacity: 10-50%
3. **Nebula Gradient**: Radial gradient from center
   - Center: `#1a1f3c` at 80% opacity
   - Mid (40%): `#0f1424` at 50% opacity
   - Edge: `#080b12` at 100% opacity

### Orbital Rings

Three concentric rings at fixed radii from center:

| Ring | Radius | Style | Label |
|------|--------|-------|-------|
| Core | 120px | Solid | "Core" |
| Inner | 220px | Dashed (8,4) | "Inner" |
| Outer | 340px | Dashed (8,4) | "Outer" |

Each ring has:
- Main stroke: `rgba(79, 172, 254, 0.25)`, 1px width
- Glow effect: `rgba(79, 172, 254, 0.1)`, 8px width, 4px blur

### Central Persona Indicator

Located at exact center of visualization:
- Outer circle: 45px radius, `rgba(79, 172, 254, 0.08)` fill, `rgba(79, 172, 254, 0.4)` stroke
- Inner circle: 30px radius, `rgba(15, 20, 36, 0.9)` fill, `#4facfe` stroke (2px)
- Persona name text: `#4facfe`, 11px, bold
- "PERSONA" label: `rgba(79, 172, 254, 0.6)`, 8px, monospace

---

## Node Anatomy

Each node consists of multiple layered elements:

### 1. Data Quality Ring (Outer)

- **Purpose**: Indicates data quality percentage
- **Radius**: `18 + (confidence * 38)` pixels
- **Stroke Width**: 3px
- **Color**: Cluster color at `(data_quality * 0.6)` opacity
- **Style**: Partial arc (dasharray) where filled portion = `circumference * data_quality`
- **Rotation**: -90 degrees (starts at top)

### 2. Main Node Circle

- **Radius**: `14 + (confidence * 32)` pixels
- **Fill**: Cluster color with type-based opacity
- **Glow Filter**: Colored glow effect per cluster (12px + 4px blur layers)
- **Stroke**: Cluster color, type-based width and dash pattern

### 3. Inner Highlight

- **Radius**: `7 + (confidence * 16)` pixels
- **Stroke**: `rgba(255,255,255,0.35)`, 1px
- **Fill**: None

### 4. Confidence Text (Center)

- **Content**: Confidence percentage (e.g., "85%")
- **Font**: Monospace, bold
- **Size**: 13px if confidence > 0.6, else 10px
- **Color**: `rgba(255,255,255,0.95)`

### 5. Semantic Label (Below Node)

- **Position**: `22 + (confidence * 32)` pixels below center
- **Font**: 10px, medium weight
- **Format**: Prefix + Label based on confidence:

| Confidence | Prefix | Prefix Color | Label Style |
|------------|--------|--------------|-------------|
| > 90% | "Exact Match: " | `#43e97b` | Normal |
| > 70% | "Likely: " | `#fee140` | Normal |
| <= 70% | "Potential: " | `#64748b` | Label + "?" |

### 6. Freshness Indicator (Top-Right)

- **Position**: Top-right corner of node
- **Size**: 5px radius circle
- **Stroke**: `#0f1424`, 2px (background contrast)
- **Fill Color by Freshness**:
  - <= 2 hours: `#43e97b` (green)
  - <= 12 hours: `#fee140` (yellow)
  - <= 24 hours: `#fa709a` (pink)
  - > 24 hours: `#64748b` (gray)

### 7. Type Badge (Below Label)

- **Position**: `36 + (confidence * 32)` pixels below center
- **Content**: Node type in uppercase (e.g., "PRIMARY")
- **Font**: 8px, monospace, uppercase
- **Color**: `#64748b`

---

## Cluster Colors

```javascript
{
  Finance: "#4facfe",
  Growth: "#f093fb",
  Operations: "#43e97b",
  Product: "#fa709a",
  Engineering: "#fee140"
}
```

---

## Type-Based Styling

| Type | Stroke Width | Dash Array | Opacity |
|------|--------------|------------|---------|
| primary | 3px | none | 1.0 |
| hypothesis | 2px | "4,2" | 0.85 |
| secondary | 1px | "2,2" | 0.70 |

---

## Node Sizing Formula

All size calculations are based on confidence (0-1 scale):

| Element | Formula |
|---------|---------|
| Data Quality Ring | `18 + (confidence * 38)` px |
| Main Circle | `14 + (confidence * 32)` px |
| Inner Highlight | `7 + (confidence * 16)` px |
| Collision Radius | `20 + (confidence * 40)` px |

**Example**: A node with 0.85 confidence:
- Main circle radius: `14 + (0.85 * 32) = 41.2px`
- Quality ring radius: `18 + (0.85 * 38) = 50.3px`

---

## Connection Lines

Lines connect center to each node:
- **Origin**: Center of visualization (persona indicator)
- **Terminus**: Node center position
- **Color**: Node's cluster color
- **Width**: `type_stroke_width * 0.5`
- **Opacity**: `0.1 + (confidence * 0.15)`
- **Dash Pattern**: Same as node type

---

## Physics Simulation (D3.js Force Layout)

### Forces Applied

1. **Charge Force**: `forceManyBody().strength(-200)`
   - Negative value causes nodes to repel each other
   
2. **Center Force**: `forceCenter(centerX, centerY).strength(0.01)`
   - Weak attraction toward center prevents drift
   
3. **Collision Force**: `forceCollide().radius(d => 20 + d.confidence * 40)`
   - Prevents nodes from overlapping
   - Radius accounts for visual size
   
4. **Radial Force**: `forceRadial().strength(0.6)`
   - Positions nodes on appropriate orbital ring based on type:
     - `primary` → 120px radius (Core)
     - `hypothesis` → 220px radius (Inner)
     - `secondary` → 340px radius (Outer)

### Alpha Decay

- **Decay Rate**: 0.015 (controls how quickly simulation settles)
- **Behavior**: Slower decay allows more organic settling movement

### Initial Node Positioning

```javascript
// Each node starts on its designated orbit with random jitter
const angle = (index / totalNodes) * 2 * Math.PI - Math.PI/2;
const jitter = (Math.random() - 0.5) * 40;
x = centerX + Math.cos(angle) * (orbitRadius + jitter);
y = centerY + Math.sin(angle) * (orbitRadius + jitter);
```

---

## Mouse Interactions

### Hover Behavior

1. **Node Raise**: Hovered node moves to front (z-order)
2. **Size Pulse**: Main circle grows by 4px radius
   - From: `14 + (confidence * 32)`
   - To: `18 + (confidence * 36)`
   - Duration: 150ms transition
3. **Tooltip Display**: Shows detailed node information

### Hover End

1. **Size Restore**: Returns to original radius
   - Duration: 150ms transition
2. **Tooltip Hide**: Removes tooltip

### Click Behavior

- Triggers `onNodeClick` callback with full node data
- Used to open detail modal in parent component

### Drag Behavior

**Drag Start**:
```javascript
simulation.alphaTarget(0.3).restart();  // Reheat simulation
node.fx = node.x;  // Fix x position
node.fy = node.y;  // Fix y position
```

**During Drag**:
```javascript
node.fx = event.x;  // Update fixed x
node.fy = event.y;  // Update fixed y
```

**Drag End**:
```javascript
simulation.alphaTarget(0);  // Cool down simulation
node.fx = null;  // Release x constraint
node.fy = null;  // Release y constraint
// Node will drift back toward its orbital ring
```

---

## Tooltip Structure

Appears on hover, positioned relative to cursor:
- **Position**: 10px right, above cursor
- **Style**: Card-style with blur backdrop

**Content**:
- Node label (bold) + ID (monospace, muted)
- Type badge (colored by cluster)
- Description (if available, left-bordered)
- 2x2 grid:
  - Confidence percentage (primary color)
  - Data Quality percentage (accent color)
  - Freshness with colored dot
  - Cluster with colored dot
- Optional section (if metadata exists):
  - Dimensions list (pill badges)
  - Logic type
  - Event binding

---

## Animation Timeline

| Event | Element | Property | Duration | Easing |
|-------|---------|----------|----------|--------|
| Page Load | All nodes | Position | ~2-3s settling | Force simulation |
| Hover In | Main circle | Radius | 150ms | Default |
| Hover Out | Main circle | Radius | 150ms | Default |
| Drag | Node | Position | Real-time | N/A |
| Drag Release | Node | Position | ~1-2s settling | Force simulation |

---

## Rendering Order (Z-Index)

From back to front:
1. Background layers
2. Orbital rings
3. Connection lines
4. Persona indicator
5. Node groups (hovered node raised to top)
6. Tooltip overlay

---

## Data Requirements

Each node requires:

```typescript
interface GalaxyNode {
  id: string;           // Unique identifier
  label: string;        // Display name
  confidence: number;   // 0-1, drives sizing
  cluster: string;      // Finance/Growth/Operations/Product/Engineering
  data_quality: number; // 0-1, drives quality ring
  freshness: string;    // "2h", "12h", etc.
  type: "primary" | "hypothesis" | "secondary";
  
  // Optional proof chain fields
  description?: string;
  dimensions?: string[];
  logic_type?: string;
  event_binding?: string;
}
```

---

## Performance Notes

- Simulation runs continuously until alpha reaches near-zero
- All transitions use D3's built-in transition system
- SVG filters (glow effects) are pre-generated in `<defs>`
- Tooltip is a React component, not SVG (allows rich styling)
- Cleanup: Simulation is stopped on component unmount
