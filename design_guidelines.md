# Salesforce OAuth Connector - Design Guidelines

## Design Approach
**Utility-Focused Design System Approach** - This is a developer/admin tool requiring maximum clarity and minimal friction. Primary goals: reliability, simplicity, and clear status feedback.

**Reference:** Bootstrap/Tailwind admin dashboard patterns - clean, functional, no decorative elements.

## Core Design Principles

### 1. Clarity Over Aesthetics
- **Single-column layouts** - No complex grids, everything flows top to bottom
- **High contrast text** - Black on white for all critical information
- **Large, obvious buttons** - No ambiguity about what to click
- **Status-first design** - Connection status is always visible at the top

### 2. Error Prevention & Recovery
- **Validation before submission** - All form fields validated client-side
- **Clear error messages** - No technical jargon, actionable instructions
- **Undo-friendly** - Disconnect option always available when connected
- **State persistence** - Show what environment was last used

### 3. Progressive Disclosure
- **Hide complexity** - OAuth details hidden until needed
- **Show what matters** - Only display relevant fields for selected environment
- **Step-by-step** - One action at a time, clear next steps

## Layout System

**Spacing:** Tailwind units of 4, 6, 8 for consistency (p-4, m-6, gap-8)

**Container:** Max-width of `max-w-2xl` (672px) - comfortable reading, no wasted space

**Sections:** Clear visual separation with `border-b border-gray-200` and `py-8`

## Typography

**Font Stack:** System fonts via Tailwind defaults
- Headings: `font-bold text-2xl` (main), `font-semibold text-lg` (sections)
- Body: `text-base` (16px) for readability
- Code/Technical: `font-mono text-sm bg-gray-100 px-2 py-1 rounded`

## Component Library

### Status Indicator
- **Connected:** Green circle + "Connected" text + last sync time
- **Disconnected:** Gray circle + "Disconnected" text
- **Error:** Red circle + "Error" text + error message below

### Configuration Form
- **Environment selector:** Radio buttons (Production/Sandbox/Custom) with descriptions
- **Conditional inputs:** Custom domain field only appears when "Custom" selected
- **Client credentials:** Two text inputs (Client ID, Client Secret) with helper text
- **Submit button:** Full-width, high contrast, disabled until form valid

### Connection Card
- **Compact info display:** Environment, Instance URL, Token expiry in grid
- **Action buttons:** Test Connection (primary), Disconnect (secondary/danger)
- **Timestamps:** Last updated, expires at in relative time

### Test Results Panel
- **Success state:** Green border, JSON response in collapsible code block
- **Error state:** Red border, error message prominently displayed
- **Loading state:** Simple spinner with "Testing connection..." text

## Page Structure

```
┌─────────────────────────────────────────┐
│  Header: "Salesforce OAuth Connector"   │
│  Status Indicator (prominent)           │
├─────────────────────────────────────────┤
│                                         │
│  [IF DISCONNECTED]                      │
│    Configuration Form                   │
│    └─ Start OAuth Flow button          │
│                                         │
│  [IF CONNECTED]                         │
│    Connection Details Card              │
│    └─ Test / Disconnect buttons         │
│                                         │
│  [Test Results Panel]                   │
│    (appears after test click)           │
│                                         │
├─────────────────────────────────────────┤
│  Footer: Health status, docs link      │
└─────────────────────────────────────────┘
```

## Interaction Patterns

### OAuth Flow
1. User fills form → clicks "Start OAuth Flow"
2. Button shows loading state, then opens new tab with auth URL
3. After approval, callback updates status automatically
4. Success message appears, connection details shown

### Token Refresh
- **Transparent to user** - Happens automatically before API calls
- **Only show errors** - If refresh fails, show clear error with reconnect option

### Testing Connection
- Click "Test Connection" → Button shows spinner
- Results appear below in expandable panel
- Success shows Salesforce limits data (proves auth works)
- Error shows specific failure reason

## Accessibility

- All form inputs have labels (not placeholders)
- Buttons have adequate size (min-h-10) and touch targets
- Color is not the only indicator (icons + text for status)
- Tab navigation follows logical flow
- Error messages associated with inputs via aria-describedby

## No Animations
Keep it simple - instant state changes, no transitions. This is a tool, not an app.

## Critical UX Requirements

1. **Callback URL visibility** - Display the callback URL prominently with copy button
2. **Environment clarity** - Show which Salesforce environment (prod/sandbox) currently connected
3. **Token expiry warning** - If token expires in <1 hour, show yellow warning
4. **One-click reconnect** - If error state, show "Reconnect" button that preserves config
5. **No manual JSON editing** - All configuration via form fields

## Images
**No images needed** - This is a utility interface. Icons only (status indicators, copy button).