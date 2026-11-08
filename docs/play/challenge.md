# Challenge: the worst detour

For more worlds and six ways to solve, [explore the task ladders](ladders.md).

<link rel="stylesheet" href="../../assets/css/atoms2-roads.css">

<p class="roads-badge"><span data-roads-badge>Designed example (roads design record)</span></p>
<p><a href="../../assets/data/atoms2/roads.json">Metro design record</a> has 12 junctions and 23 public, undirected, weighted roads. For every closure of at most two roads, find its cheapest A-to-L route. Which closure has the highest cheapest cost?</p>

<aside class="roads-scope"><strong>Answer shape and scope</strong><br>One witness: up to two closed road IDs and the shortest surviving A-to-L route. For each closure, choose the cheapest surviving route; break ties by junction order. Across closures with equal worst cost, choose the first closed set alphabetically. All 277 closures (including none) are computed in your browser. Each simple route costs at most 88, inside JavaScript's exact integer range. This does not verify a v2 definition.</aside>

<section class="roads-card roads-challenge" data-roads-challenge>
<h2>Submit one witness</h2>
<p>Close up to two roads, then choose junctions from A to L. Click a closed road to reopen it, or use the text fields. The map and fields stay in sync.</p>
<button class="a2-btn roads-map-zoom" type="button" data-roads-zoom aria-pressed="false" aria-controls="roads-metro-map">Zoom in on map</button>
<p class="roads-map-cue" data-roads-map-cue role="status">The whole map, from A to L, is shown. Zoom in to read road labels.</p>
<div id="roads-metro-map" class="roads-map-wrap roads-map-challenge" data-roads-map aria-label="Interactive Metro map, 12 junctions and 23 weighted roads"></div>
<details class="roads-road-list"><summary>Road IDs and weights (text alternative)</summary><p data-roads-edge-list></p></details>
<form>
<label>Closed road IDs, separated by commas (leave blank for no closures)<input name="closed" autocomplete="off" placeholder="AB, AC"></label>
<label>Route junctions, separated by commas (for example <code>A, D, F, H, K, L</code>)<input name="route" autocomplete="off" placeholder="A, D, F, H, K, L" required></label>
<button class="a2-btn" type="submit">Check answer</button>
</form>
<p data-roads-report role="status">The judge shows a valid route when yours fails, a better witness when one exists, or the exact input error.</p>
<button class="a2-btn" type="button" data-roads-reveal aria-expanded="false" aria-controls="roads-all">Reveal the 277-case check</button>
<div id="roads-all" data-roads-all hidden></div>
</section>

This tests closures and route costs, not proof of a promoted definition. Need the earlier steps? <a href="../../learn/">Inspect the dependency ladder</a>.

<script src="../../assets/js/atoms2/roads.js"></script>
