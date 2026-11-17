---
name: Business Intelligence Agent
description: A local evidence-led investigation surface for e-commerce performance.
colors:
  sodium: "#f1d56d"
  violet: "#aaa1ff"
  blue: "#79baff"
  cyan: "#66d9e8"
  green: "#83d9ad"
  orange: "#ffad79"
  magenta: "#ff8497"
  ground: "#15171b"
  plate: "#1c1f24"
  rule: "#373c43"
  ink: "#f0efe8"
  muted: "#b7bbc1"
typography:
  display:
    fontFamily: '"Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "clamp(28px, 3.1vw, 39px)"
    fontWeight: 570
    lineHeight: 1.14
    letterSpacing: "-0.035em"
  headline:
    fontFamily: '"Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "16px"
    fontWeight: 620
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: '"Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "17px"
    fontWeight: 610
    lineHeight: 1.3
    letterSpacing: "-0.012em"
  body:
    fontFamily: '"Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"Segoe UI", "Helvetica Neue", Arial, sans-serif'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  control: "2px"
  dot: "50%"
components:
  button-primary:
    backgroundColor: "{colors.sodium}"
    textColor: "#201e17"
    rounded: "{rounded.control}"
    padding: "0 15px"
    height: "42px"
    typography: "{typography.label}"
  window-select:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
    height: "42px"
    typography: "{typography.label}"
  finding-priority:
    backgroundColor: "transparent"
    textColor: "{colors.magenta}"
    typography: "{typography.label}"
---

# Design System: Business Intelligence Agent

## Overview

**Creative North Star: "The Calibrated Signal Rail"**

The interface treats an investigation as an observable route: a business signal leads to measured evidence, then to a bounded next test. A single off-centre rail anchors the page while rules, ticks, and segmented rows carry hierarchy. The dark working plate keeps long comparisons legible; spectral accents behave like fine instrument marks rather than large blocks of color.

The interface is an operational tool, not a marketing dashboard. It surfaces synthetic-data status and comparison windows before asking the user to interpret a finding. Explanations distinguish measurement from hypothesis, and actions remain testable rather than claiming guaranteed impact.

**Key Characteristics:**
- Charcoal field, bone text, and precise one-pixel rules.
- Seven spectral hairlines as identity; color is never the only status cue.
- Findings read in a signal → evidence → next-test sequence.
- Flat surfaces and open layout instead of rounded card stacks.

## Colors

A restrained charcoal palette carries content; narrow spectral colors mark the rail, metrics, and investigation states.

### Primary
- **Sodium Signal** (`#f1d56d`): Primary run action, revenue trace, and the lead rail tick.

### Secondary
- **Violet Emission** (`#aaa1ff`): First spectral mark.
- **Blue Emission** (`#79baff`): Evidence-route labels and second spectral mark.
- **Cyan Emission** (`#66d9e8`): Average-order-value marker and third spectral mark.

### Tertiary
- **Green Emission** (`#83d9ad`): Dataset-ready state and test-action rule.
- **Orange Emission** (`#ffad79`): Sixth spectral mark.
- **Return Signal** (`#ff8497`): Return-rate marker and high-priority state.

### Neutral
- **Working Charcoal** (`#15171b`): Main background and chart ground.
- **Instrument Plate** (`#1c1f24`): Method panel.
- **Rule Gray** (`#373c43`): Section and table dividers.
- **Bone Ink** (`#f0efe8`): Primary text and measured values.
- **Measurement Gray** (`#b7bbc1`): Supporting text and labels.

### Named Rules
**The Hairline Rule.** Keep spectral color to thin marks, borders, and lines; do not turn it into large status panels.

**The Evidence-Is-Not-Cause Rule.** Use a route to connect a signal to its measurements and next test, never a visual arrow that claims the measured association proves causation.

## Typography

**Display Font:** `"Segoe UI", "Helvetica Neue", Arial, sans-serif`
**Body Font:** `"Segoe UI", "Helvetica Neue", Arial, sans-serif`
**Label/Mono Font:** Same system sans; tabular numerals are used for measured values.

**Character:** A familiar system sans keeps this information-dense tool native to the operating environment. Size, weight, tracking, and tabular figures distinguish the hierarchy; no decorative display face competes with the data.

### Hierarchy
- **Display** (570, `clamp(28px, 3.1vw, 39px)`, 1.14): Main page heading.
- **Headline** (620, 16px, 1.25): Section titles such as the investigation route.
- **Title** (610, 17px, 1.3): Finding titles.
- **Body** (400, 15px, 1.5): General interface copy; long explanatory copy stays in a readable measure.
- **Label** (400, 10–12px, 1.5, occasional uppercase tracking): Dataset, state, evidence, and chart labels.

### Named Rules
**The Measured-Value Rule.** Use tabular numerals for values and period comparisons so changes remain easy to scan.

## Layout

The working surface is a centered field with a maximum width of 1320px and an off-centre rail at 22px. At wide widths, four period metrics form a ruled row; the investigation route follows them before the revenue trace and comparison panel. Findings separate a signal summary from evidence and a next test. The footer records data source, storage, and scope.

At 760px and below, metrics become two columns and analysis panels stack. Findings become a single-column route. At 480px and below, horizontal page padding tightens, the header simplifies, and findings stack evidence and action vertically. Rules, generous section spacing, and tabular values maintain the instrument-like rhythm.

## Elevation & Depth

The system is flat by default and uses no box shadows. A restrained radial charcoal shift gives the page slight environmental depth; tonal plates, hairline borders, and overlap-free grouping define structure. Focus is explicit and offset rather than conveyed by a shadow.

### Named Rules
**The Flat-By-Default Rule.** Use surface tone and one-pixel rules for hierarchy; reserve motion and color for a meaningful state change.

## Shapes

Controls use a near-square 2px radius. The live-state dot alone is circular. Rows and panels remain rectangular, separated by rules rather than rounded containers. Rail ticks are thin lines; priority markers are open squares.

## Components

### Primary Action
- **Shape:** Near-square corners (2px).
- **Primary:** Sodium background with dark text, 42px high, 15px horizontal padding.
- **Hover / Focus:** A small lift and brighter sodium fill on hover; a clear offset sodium outline on keyboard focus.
- **Disabled:** Reduced opacity, no lift, and progress cursor while an investigation runs.

### Window Selector
- **Style:** Charcoal plate, thin gray border, near-square corners, 42px minimum height.
- **Focus:** Two-pixel offset sodium outline.
- **Behavior:** Offers only the supported 7, 14, 30, 60, and 90 day windows.

### Dataset Tag
- **Style:** Transparent ground, green text, and a small green live-state dot.
- **Behavior:** Names synthetic data directly; it is not an interactive control.

### Period Metrics
- **Style:** Four open columns separated by one-pixel rules; no card fill or shadow.
- **Value:** Large tabular figure; directional comparison below uses text and sign as well as color.
- **Responsive:** Two-column layout at compact widths.

### Investigation Route
- **Style:** Finding summaries align with the page rail; evidence and next test form adjacent columns at wide widths and a vertical sequence on mobile.
- **State:** Priority uses a labeled value, line mark, and shape; color is supplementary.
- **Behavior:** Evidence names each comparison and observation; explanatory copy states uncertainty; the next test is a bounded recommendation.

### Revenue Trace
- **Style:** Inline SVG line chart on the working ground, with thin sodium line, subtle filled area, quiet axis rules, and labeled dates.
- **Behavior:** Accessible chart name summarizes period and sample count; daily values remain tied to the selected window.

### Navigation
- **Style:** Compact top bar with a spectral identity mark, product label, synthetic-data state, and local DuckDB context.
- **Mobile:** Preserve the identity and synthetic-data state; suppress secondary storage text when space is constrained.

## Do's and Don'ts

### Do:
- **Do** keep signal, measured evidence, and next test visibly distinct and ordered.
- **Do** pair a color marker with readable text or line form for state and priority.
- **Do** label synthetic data and show comparison dates near metrics.
- **Do** keep evidence values tabular and period-aligned.

### Don't:
- **Don't** use a large colored panel or gradient to stand in for evidence.
- **Don't** use rounded-card grids or shadows to organize this surface.
- **Don't** imply a measured association proves a cause.
- **Don't** use spectral color as the sole meaning of a finding.
