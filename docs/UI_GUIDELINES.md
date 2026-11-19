# Desktop UI guidelines

What a screen of the AlgaMetrix desktop app has to do before it is finished.
The rules are short because most of them are enforced by code: the tokens in
`desktop/theme.py`, the field catalogue in `desktop/fields.py`, the widgets in
`desktop/widgets.py` and the chart helpers in `desktop/charts.py`. A screen
assembled from those parts gets the right spacing, colours, units and states
without deciding any of it locally. Run `python scripts/ui_screenshots.py OUT`
to render every screen off-screen and look at the result.

## Tokens, not values

* Colours, the type scale, spacing steps and radii live in `desktop/theme.py`.
  Screens name a role (`INK_2`, `LINE`, `ACCENT`, `WARNING`), never a hex value.
* One interactive colour (`ACCENT`), with hover and pressed steps. State colours
  (`SUCCESS`, `WARNING`, `DANGER`, `INFO`) mean a state and are never used to
  decorate or to tell series apart.
* Every text colour clears 4.5:1 on the white surface it sits on. Captions use
  `INK_3`, the lightest tone that still passes; nothing lighter carries text.
* Type: 13 px body, 12 px captions, 14/16 px headings, 24 px for the one big
  number on a KPI tile. Nothing under 11 px.
* The chart palette is the validated categorical order in `theme.SERIES`;
  a single-series chart uses slot 1, polarity uses `BURDEN` / `CREDIT`.
  Run the validator in the data-viz reference before changing it.

## Layout and navigation

* Inputs on the left, grouped by process step and numbered in process order:
  organism, cultivation, harvest and drying, downstream, waste feed, schedule,
  economics, life-cycle background. Results on the right, one tab per question.
* A page is a scroll area when it can grow; a chart never fixes a height that
  hides its axis labels.
* Every command has a menu entry with a shortcut; buttons repeat the command
  but never own the key (two owners of one key means neither fires).
* The layout must hold at 1180 × 760 logical pixels and scale with the display.

## Forms

* Every numeric field comes from `desktop/fields.py`: a label, a unit shown
  next to the control, the range it accepts, a one-paragraph meaning, and the
  provenance of its default. A field that is not in the catalogue is a bug.
* Provenance is what the data declares: the `source` of a factor in
  `data/lcia.yaml`, the `notes` of a preset, the `source` of a cost-scaling
  block. A placeholder default says so. Never invent a citation for a tooltip.
* A control the engine does not read under the current configuration is
  disabled, together with its label and unit, and its tooltip says why.
* The engine's admissibility check (`algametrix.inputcheck`) decides what is
  possible. An error marks the field red, a warning amber, and the message is
  in the field's tooltip and in the banner at the top of the Overview page.
  Nothing is computed, exported or compared while an error stands.
* Numbers commit on Enter, focus-out or the arrows, not on every keystroke.

## Results

* Every number carries a unit and a basis: per kg of which product, per year,
  at the plant gate, allocated by what. KPI tiles have a basis line; table
  headers name the unit; chart axes name the unit.
* The functional unit, the system boundary (cradle-to-gate, attributional),
  the allocation and the price basis (EUR as entered, no conversion) are
  stated on the Overview page, repeated in the header chips, and printed in
  the report. A page that shows a cost or an impact without them is incomplete.
* Precision: three significant figures for derived quantities, two decimals
  for a price per kg, one for years, none for percentages of a share. Never
  more than the model has.
* Charts: one value axis with its unit; thin bars on a hairline grid; largest
  values labelled at the tip, the rest left to the axis and the table beside
  the chart; a legend whenever two kinds of mark share a plot; hover shows the
  exact value. Ranked bars instead of pies. No dual axes.
* Every chart has a table twin on the same page.

## States

* Empty: a page that has nothing to show says what would fill it and how
  (`EmptyState`), never a blank area.
* Loading: an analysis that takes more than a moment shows a wait cursor, a
  status line and a disabled run button until it returns.
* Error: a refused case is a banner and marked fields, with the exact message
  of the engine, and the previous result is not left on screen.

## Validation page

* The evidence class of every published comparison is printed in its row, with
  the definition in the tooltip, and the caveat that none of these is a
  prospective validation stays on the page. Calibrated rows are never shown
  as independent tests.
* Fit and range verdicts are words; colour only repeats them.

## Before a screen ships

1. Open it at 1440 × 900 and at 1180 × 760. Nothing clipped, no horizontal
   scroll in the input column.
2. Tab through it. Focus is visible on every control, in reading order.
3. Hover every number: unit, basis and, for an input, the source.
4. Make the case inadmissible. The banner, the field marks and the empty states
   appear; the exports refuse.
5. Switch to a heterotrophic system and back. Units, disabled rows and preset
   notes follow.
6. `pytest tests/test_desktop_window.py tests/test_wizard.py tests/test_desktop_ui.py`.

## Sources

The chart rules follow the data-visualisation method Anthropic ships with
Claude Code (form before colour, validated categorical order, one axis, thin
marks, selective labels). The form, feedback and accessibility rules distil
the UX guideline set of the open-source UI/UX Pro Max project (MIT) to what
applies to a scientific Qt desktop tool; its style catalogue, landing-page
patterns and web stacks do not apply here and are not used. The scientific
rules (unit and basis on every number, boundary and price basis stated,
precision, evidence classes visible) are AlgaMetrix's own and take precedence.
