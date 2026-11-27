# Review Intelligence Dashboard — V11

A standalone, desktop-browser Dash application for exploring SQLite review data. Review counts, sentiment statistics, timelines, and evidence are **deterministic**; interpretation narratives live in separate JSON files under `interpretations/`.

## Run

Requires Python 3.10+.

```bash
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8050`. The default page is **Playground**; **All chapters · Report** is next in the sidebar. Supply a newer database by replacing `data/reviews.db` or setting `REVIEWS_DB` to an absolute path before restarting the application.

## Pages

- **Playground:** daily total recommended review counts above zero and non-recommended counts below zero; markers for October 23 (patch 1.1.2), October 30 (1.1.3), November 9 (1.2), and November 19 (hotfix 1.2.1). Those markers are provided dates, **not** evidence of patch effects. Patch dates beyond the loaded reviews remain visible without invented review counts. Filter any tag by positive, negative, neutral, or mixed sentiment; optionally intersect with a second tag. Explore sentiment over time and browse original reviews.
- **What went well:** meaningful co-op, specific named puzzles, and art vs story. Named puzzles and art/story use simple **positive vs negative** review-mention bars; the unrelated second-step co-tag views were removed.
- **What went wrong:** puzzle frustration, technical progression, fandom/expectations. Puzzle frustration and fandom show **positive vs negative** tag mentions directly. Technical progression keeps the named-puzzle × negative technical-tag heatmap, with review-level click-through, but no right-hand related-tag view.
- **Unexpected findings:** recommendation versus written-review sentiment, playtime, October 20–25 launch shift, and motion sickness. Puzzle vs Bug Uncertainty has been removed as a report case, but its review data remains available via Playground.
- **Evidence explorer:** any supported chart segment opens the exact matching review IDs, original review bodies, tag sentiments, and highlighted source spans. A review chip jumps to its verified span. Export a selected cohort or individual review to JSON.
- **Evidence manifest:** filtering logic, matching IDs, data fingerprint, and quote-span validation.

## Recommendation vs sentiment

A **recommendation** is the player's binary thumbs-up/thumbs-down verdict (`rating`). **Overall review sentiment** is a separate classification of the whole written review (`overall_sentiment`), with positive, negative, neutral, or mixed values. *Mixed* denotes textual praise and criticism in the same review and does not override the recommendation. **Tag sentiment** is separately classified for each tag assignment. Some reviews have multiple sentiments assigned to the same tag, so tag-mention categories are not always mutually exclusive.

## Updating and translation

Replacing the SQLite file refreshes deterministic calculations at the next app start. Existing narratives are versioned separately and flagged as potentially stale when the data fingerprint changes; the app does not automatically invoke AI. Translation of review bodies is offered on demand through the optional Google Cloud Translation API integration; without API configuration, the dashboard remains functional. No offline translation provider was added.

## Project layout

- `app.py` — Dash pages, charts, navigation, overlays, and evidence interactions.
- `analytics/` — read-only SQLite analysis, review filtering, translation and JSON exports.
- `interpretations/` — editorial interpretation JSON files, independent of numeric calculations.
- `assets/` — UI styling and browser interaction support.
- `tests/` — database-backed regression tests.

## Testing and release limitations

V11 passed Python compilation plus 12 focused automated regression tests covering chart construction, review totals, patch markers, evidence populations, exports and the technical heatmap. The complete historical test suite did not finish in the available runtime. Dash was not installed in the authoring environment, so the live browser render and click interactions have **not** been smoke-tested here.

The *complete* ZIP includes the supplied review database. Check access rights before committing or sharing it. The *source-only* ZIP omits the database. For team deployment, run on an authenticated internal server; exposing Dash's development server is not a production security setup.
