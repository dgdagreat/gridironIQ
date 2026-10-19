# Build & publish the dashboard (Tableau Public)

~20–30 minutes end to end. Tableau Public is free; the catch is that your workbook
is published publicly — which is exactly what you want for a portfolio link.

## 0. Install & connect

1. Download **Tableau Public** (free): https://public.tableau.com/app/discover (needs a free Tableau Public account to save/publish).
2. Open it → **Connect → To a File → Text file** → pick `tableau/data/champion_premium_by_position.csv`.
3. In the Data Source tab, use **Add → Text file** to also bring in the other four CSVs. (They're separate sources — no joins needed; each sheet uses one.)
4. For any cap-share field (`champion_premium`, `cap_pct`, `avg_cap_pct`), right-click the field → **Default Properties → Number Format → Percentage** (1–2 decimals).

## 1. Sheet — "Champions pay up / value" (the headline)

Source: `champion_premium_by_position`.
- **Columns:** `champion_premium`  •  **Rows:** `position`.
- Sort `position` descending by `champion_premium` (toolbar sort button).
- Drag `spend_tilt` to **Color** (green = pay up, grey/orange = value).
- Drag `champion_premium` to **Label**.
- Title: **"Where Super Bowl winners overspend"**. This is a diverging bar — the single most memorable view.

## 2. Sheet — "Cap allocation by era"

Source: `positional_spending_by_era`.
- **Columns:** `era`  •  **Rows:** `position`  •  **Color:** `avg_cap_pct` (sequential).
- Mark type **Square** → a heatmap of how spend shifted (watch QB and WR climb).
- Add `avg_cap_pct` to Label.

## 3. Sheet — "Spend vs winning" (interactive)

Source: `team_season_positional_long`.
- Filter `pos_group` to a single position (show the filter as a dropdown: right-click → **Show Filter**) — start on QB.
- **Columns:** `cap_pct` (AVG)  •  **Rows:** `season`, or use `AVG(cap_pct)` vs an outcome breakdown.
- Drag `outcome` to **Color** (Won SB / SB appearance / Did not reach SB).
- This lets a viewer ask "do teams that spend big at QB win more?" live.

## 4. Sheet — "On-field efficiency" (today)

Source: `team_epa`.
- **Columns:** `net_epa_play`  •  **Rows:** `team` (sorted desc).
- Color by `net_epa_play` (red–blue diverging). Optional: a second bar sheet for `off_epa_play` vs `def_epa_play_allowed`.

*(Optional 5th: `value_board` scatter — `pay_pct` on Columns, `caliber_pct` on Rows, size = `value_index`, a 45° reference line separates overpaid from underpaid.)*

## 5. Assemble the dashboard

1. **New Dashboard** (bottom tab). Set Size → **Automatic** (or Desktop 1200×800).
2. Drag the four sheets in: headline bar top-left, era heatmap top-right, spend-vs-win bottom-left, EPA bottom-right.
3. Add a **Text** object at the top for the title + one-line thesis:
   *"Championship teams pay a premium at TE, EDGE and QB — and find value at LB and RB. ~25 years of cap data."*
4. Set the `pos_group` filter on sheet 3 to **"Use as Filter"** so it drives interactivity.
5. Add a caption crediting the pipeline: *"dbt + DuckDB/Databricks · data: nflverse / OverTheCap."*

## 6. Publish & link

1. **File → Save to Tableau Public As…** → sign in → name it `GridironIQ — NFL Roster Construction`.
2. It opens in the browser with a public URL (e.g. `public.tableau.com/app/profile/you/viz/GridironIQ/...`).
3. In **Edit Details**, set a thumbnail and description; allow the workbook to be downloaded if you want it reproducible.
4. Put the link in the main repo `README.md` and your résumé/LinkedIn. Optional: embed it with the `<script>` snippet Tableau's **Share → Embed Code** gives you.

## Notes
- Keep the CSVs next to the `.twb` (or publish an **extract**, which Tableau does by default on Public) so the viz isn't tied to your local paths.
- To refresh with new data: re-run `export_data.py`, then in Tableau **Data → Refresh**, and re-publish.
