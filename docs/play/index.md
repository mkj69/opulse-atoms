<link rel="stylesheet" href="../assets/css/atoms2-lab-computer.css">
<link rel="stylesheet" href="../assets/css/atoms2-define.css">
<link rel="stylesheet" href="../assets/css/atoms2-boundary.css">
<div data-a2="computerLab"></div>

## Definition workshop {#definition-workshop}

The workshop checks syntax, sorts and selected cases in your browser. It cannot certify or promote a v2 definition. The Example operation uses a nonnegative second input; for signed inputs, use the given <code>mul</code> fixture instead. Use the separate computer preview above to inspect a finite machine case. Inputs and intermediate integers must stay within -9007199254740991..9007199254740991.

The browser case-check method enumerates a finite scope or samples seeded cases. Without a reference or canonicalization contract, evaluating cases does not establish equivalence.

<details><summary>Core checks for laws and bridges</summary><p>The Python core checks laws with <code>opulse.atoms.laws.verify_law</code> and replays rewrites with <code>replay_rewrite</code>; it checks bridges with <code>opulse.atoms.bridges.verify_bridge</code>. Workshop law and bridge tabs check only syntax, sorts and layers, not those core contracts.</p></details>

You can edit and rerun a definition stored in this session. Storing it again replaces that name; changes to its source also change dependent hashes, and old dependent case evidence detaches. Given world atoms cannot be replaced.

Use **Build four-kind preview** to add a browser-only object, operation, combinator and observation to one robot session. The first three form a dependency chain. This preview keeps the observation in a separate branch; it does not implement the 0.5 core rule that permits pure definitions on observed values. Observations cannot act or read the truth except through probes. Each case check states its own finite scope.

Type the ASCII storage form; the preview shows notation v3.

<div data-a2="define"></div>

## Keep exploring

[Take a six-angle task ladder](ladders.md) to compute, invert, decide, describe, induce or create in the exported worlds.

[Try a scoped challenge](challenge.md) or open the [Legacy-v1 runner](legacy.md). The legacy runner uses the published v1 dialect and does not check v2 definitions.

<script src="../assets/js/atoms2/lab-preview-world.js" defer></script>
<script src="../assets/js/atoms2/boundary.js" defer></script>
<script src="../assets/js/atoms2/lab-computer.js" defer></script>
<script src="../assets/js/atoms2/n3-convert.js" defer></script>
<script src="../assets/js/atoms2/define.js" defer></script>
