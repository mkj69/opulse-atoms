---
hide:
  - navigation
---

<link rel="stylesheet" href="../../assets/css/learn.css">

# Six kinds, one grammar

Six kinds describe what can be defined. The grammar world runs the object, operation, combinator and observation below. The law, bridge and template remain designs or use separate core examples.

## Read a mark

In a display formula, a mark is one glyph with an optional index. The glyph tells you the kind: a suit or shape is an operation, a double-struck capital an object, a Greek capital a combinator, a hatted capital an observation, `≡` a law and `↝` a bridge. In the [fixed example legend](../reference/notation-v3.md), <code class="n3" data-n3-ascii="\dia_6">♦₆</code> is an operation named f6. Digits starting 1 to 9 select a defined atom; digits starting with 0 number an overflow given when a kind runs out of unindexed glyphs; a letter identifies a parameter slot, as in <code class="n3" data-n3-ascii="\dia_a">♦ₐ</code>. No index means a given, such as <code class="n3" data-n3-ascii="\bbZ">ℤ</code>. A real world's legend identifies its own marks and signatures; you cannot infer its names from this example's numbers.

Read the bracket after the mark before reading its arguments. Parentheses `( )` pass values, square brackets `[ ]` pass atoms, and angle brackets `⟨ ⟩` pass hidden state. In C8, <code class="n3" data-n3-ascii="\Theta_1&#91;\dia_a&#93; x = { \dia_a (\dia_a x) }">Θ₁[♦ₐ] x = { ♦ₐ (♦ₐ x) }</code> defines a combinator that applies its operation slot twice. C9, <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3 =&gt; 12">Θ₁[♡₄₅] 3 ⇒ 12</code>, supplies a defined operation to that slot. In C11, <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt; = { not \hatW&lt;&#124;s&#124;&gt; and not \hatU&lt;&#124;s&#124;&gt; }">Ô₁⟨s⟩ = { not Ŵ⟨s⟩ and not Û⟨s⟩ }</code>, angle brackets identify the state read by granted probes. A signature line such as <code class="n3" data-n3-ascii="(+) : \bbZ \x \bbZ -&gt; \bbZ">(+) : ℤ × ℤ → ℤ</code> gives input and output types; a formula line such as <code class="n3" data-n3-ascii="a \dia_6 b = { (a @) * b }">a ♦₆ b = { (a @) * b }</code> gives a definition. A left superscript on a header identifies its layer, not a different kind.

The site's formulas use these marks. The source declarations and historical exports remain in ASCII machine notation; the v3-ASCII copy spelling, such as `\dia_6` for <code class="n3" data-n3-ascii="\dia_6">♦₆</code>, maps each display token back to ASCII. [Read the notation reference](../reference/notation-v3.md) for the complete table and all C examples.

A world need not open every kind for invention. If only operation is open, you can define new operations but still use given objects, combinators and observations. This is the classic Opulse case. Other worlds open several kinds; laws and bridges are listed when a world opens them. [Filter by open kinds in the Worlds catalog](../worlds/index.md).

<p class="a2-learn-lede">The eight-operand expression below has 429 binary parse trees when no precedence is assumed. Each kind gives a different way to work with those trees.</p>

The grammar kernel encodes its word value as a token sequence with the same tokens. The infix grouping and proposed tree and postfix forms are schematic, not core output.

<div class="a2-learn-app" data-a2-learn="kinds" data-source="../../assets/data/atoms2/grammar.json" data-walk="../../assets/data/atoms2/walk.json" data-core="../../assets/data/atoms2/grammar_core.json">
  <p role="status">Loading the grammar core runs...</p>
</div>

<noscript>The grammar core export records bounded checked-input scopes for the object, split operation, chart combinator and parse-count observation. A separate core call of the observation returns Ok(429) for an eight-operand Word outside that checked scope. The grammar law and postfix bridge are designs. JavaScript is needed to show the records.</noscript>

[Continue to checks and limits](checks.md)

<script src="../../assets/js/atoms2/learn-evidence.js"></script>
<script src="../../assets/js/atoms2/learn-kinds.js"></script>
