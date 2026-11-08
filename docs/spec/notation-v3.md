# Notation v3

Notation v3 is the site's formula notation. It has two spellings of the same token stream: a Unicode display form and a token-for-token v3-ASCII copy form. The Python machine declaration language is separate and unchanged. Definitions in exports, datasets and training data retain that machine notation; the site generates display formulas from it and copies v3-ASCII rather than substituting an ASCII machine declaration for a visible formula.

## Reading a formula

1. One atom has one mark: a glyph family indicates its kind and the index identifies its reference. Operations use suits and shapes, objects double-struck capitals, combinators Greek capitals, observations hatted capitals, laws `≡`, and bridges `↝` or `⇝`. Templates use the family of the kind they produce. An additional kind can use `◈` with a superscript kind number.
2. Digits starting 1 to 9 identify a defined atom; digits starting with 0 number an overflow given when a kind runs out of unindexed glyphs. Overflow givens use `01`, `02`, ... in given order per kind (`♦₀₇` copies as `\dia_07`); `0` alone and `00` prefixes are invalid. A subscript letter is a parameter slot, no index means a given, and a `⌞e⌟` index splices in the atom computed by `e`. A superscript at the left of a definition header mark denotes its layer; a prime on an observation reads its previous value.
3. Marks may be infix, prefix or postfix. One free mark fits in a term; group a compound operand with parentheses. Marks bind more tightly than arithmetic and comparison signs. Ordinary binary signs have fixed precedence and are not invented marks.
4. After a mark, `( )` holds values, `[ ]` holds atom arguments and produces a derived mark, and `⟨ ⟩` holds hidden state. Adjacent brackets attach to the mark even if spaces intervene. A list `[ ]` elsewhere is a value, not atom parameters.
5. `=` defines; `==` compares; `⇒` shows a result or, with `?`, asks for one; `:` introduces a signature or a quantified law; `⊢` attaches a checked condition. A law mark between two grouped expressions denotes one rewrite step. A case body uses braces with `if` and `else`.
6. Given signs build objects: `∈` and `∣` refine a set, `×` makes a product, `/` quotients by an operation, and `↾` seals an interface. Bracketed atom parameters make a template of any kind; `⌜ ⌝` quotes a statement as a value.

Definitions have formula-only bodies. A signature is a separate line carrying types and, if needed, a layer superscript. The per-world legend supplies the long name, kind and signature associated with each mark. A glyph alone cannot tell you which named atom a world assigned to that mark.

## World legend assignment

Mark assignment is deterministic for each world. First, given arithmetic, comparison and logic operations with the matching names and arities use their binary signs. Remaining layer-0 givens take unindexed marks of their own kind, in symbol-table order: operations take `@ # $ &` and then the operation families, objects the double-struck capitals (ℤ and 𝔹 are fixed for integers and booleans), combinators the Greek capitals, observations the hatted capitals. A mark never borrows another kind's family: an operation that reads a field or constructs an object still has an operation mark, and the name of an atom never chooses its glyph. If a kind exhausts its unindexed families, later givens receive leading-zero digit indices `01`, `02`, ... in given order per kind, without a layer marker.

Defined atoms have a digit index within their kind, ordered by layer and then by their order in the export. They start at 1 per kind and never start with 0: no family-and-index-string pair is reused within a world. Operations choose families by arity: unary marks cycle through down/up filled and open triangles; binary marks cycle through suits; arities zero and three or more cycle through squares, circles, lozenges and stars. Objects cycle through the allowed double-struck capitals, combinators through the Greek table and observations through the hatted table; laws use `≡` and bridges use `↝`. Atoms of one kind are told apart by their index. Generated machine names are still names in the legend, not alternative marks.

Each export's legend lists givens in declaration order, then defined atoms in layer and definition order. Each entry includes the ASCII mark, display mark, name, kind, layer, origin and optional signature in both spellings. Within a world, the mapping between name and mark works in both directions. Regeneration depends on the ordered atoms, their kinds, layers and arities, not a hash of unrelated export content. The token mapping between v3-ASCII and display remains global and does not require the world legend.

## Symbol table

| Kind | Display families | v3-ASCII families | Examples |
| --- | --- | --- | --- |
| Operation | ♠ ♤ ♥ ♡ ♦ ♢ ♣ ♧ ■ □ ● ○ ▲ △ ▼ ▽ ◆ ◇ ★ ☆ | `\spade \wspade \heart \wheart \dia \wdia \club \wclub \sq \wsq \dot \wdot \up \wup \dn \wdn \lz \wlz \st \wst` | <code class="n3" data-n3-ascii="a \dia_6 b">a ♦₆ b</code>, <code class="n3" data-n3-ascii="\dn_2 a">▼₂ a</code>; givens `@ # $ &` and binary signs `+ - * / %` |
| Object | Double-struck capitals except reserved ℂ 𝔽 ℕ ℙ ℚ ℝ | `\bbA` through `\bbZ` except those reserved initials | <code class="n3" data-n3-ascii="\bbD_1(2, 4)">𝔻₁(2, 4)</code>; given <code class="n3" data-n3-ascii="\bbZ">ℤ</code> and <code class="n3" data-n3-ascii="\bbB">𝔹</code> |
| Combinator | Γ Δ Θ Λ Ξ Π Σ Φ Ψ Ω | `\Gamma \Delta \Theta \Lambda \Xi \Pi \Sigma \Phi \Psi \Omega` | <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3">Θ₁[♡₄₅] 3</code> |
| Observation | Â Ĉ Ê Ĝ Ĥ Î Ĵ Ô Ŝ Û Ŵ Ŷ Ẑ | `\hatA \hatC \hatE \hatG \hatH \hatI \hatJ \hatO \hatS \hatU \hatW \hatY \hatZ` | <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt;">Ô₁⟨s⟩</code>; <code class="n3" data-n3-ascii="\hatS_2&#x27;">Ŝ₂′</code> |
| Law | ≡ | `\eqv` | <code class="n3" data-n3-ascii="\eqv_1">≡₁</code> |
| Bridge | ↝ ⇝ | `\squig \Squig` | <code class="n3" data-n3-ascii="\squig_1(m)">↝₁(m)</code> |
| Template | The produced kind's family followed by `[ ]` | The same family's ASCII name | <code class="n3" data-n3-ascii="\bbK_4&#91;\bbX_t, \dia_a&#93;">𝕂₄[𝕏ₜ, ♦ₐ]</code> |
| Further kind k | ◈ with an unbounded superscript kind number | `\k` followed by the kind number | <code class="n3" data-n3-ascii="\k7_3(x)">◈⁷₃(x)</code> is `\k7_3(x)` |

The index follows the family name with `_`: <code class="n3" data-n3-ascii="\dia_6">♦₆</code> is `\dia_6`, a numbered given <code class="n3" data-n3-ascii="\dia_07">♦₀₇</code> is `\dia_07`, and <code class="n3" data-n3-ascii="\dia_a">♦ₐ</code> is `\dia_a`. A layer goes before it (`¹♠₃` = `^1\spade_3`), a prime after it (`Ŝ₂′` = `\hatS_2'`). A splice is `⌞e⌟` / `{| e |}`. Superscript kind numbers and atom indices are unbounded decimal integers. Only one display spelling is registered for each family; the global mapping does not consult the world legend.

| Display sign | v3-ASCII | Use |
| --- | --- | --- |
| `⇒ → ↦ ⊢` | <code>=&gt; -&gt; &#124;-&gt; &#124;-</code> | Result, type arrow, lambda, check |
| `⟨ ⟩ ⌜ ⌝ ⌞ ⌟` | <code>&lt;&#124; &#124;&gt; &#91;&#124; &#124;&#93; {&#124; &#124;}</code> | State, quote, splice delimiters |
| `× ∈ ∀ ∣ ↾ ↓` | `\x \in \all \mid \seal \dec` | Product, membership, quantifier, refinement, sealing, measure |
| `⊤ ⊥ …` | `\top \bot ...` | Boolean values and ellipsis |
| `= == != < <= > >= and or not if else` | Identical ASCII | Definitions, comparisons and case logic |

ASCII uses `\family_index`, not the machine parser's named declaration syntax. Both spellings use lowercase Latin variables and capitalised constants (`E`, `P1`, `Metro`). A name from a legend is not an alternate spelling for a mark.

## Grammar and printing

Lexing is longest-match and independent of kind. A mark is an optional layer, a family, an optional digit/letter/splice index and optional prime. Binary signs (`+ - * / % == != < <= > >= × ∈ ↾ and or not`) are separate from marks; `@ # $ &` are given operation marks. A binary sign stands for an operation value only when immediately before `)`, `,` or `]`, as in <code class="n3" data-n3-ascii="\Phi_2&#91;+&#93;">Φ₂[+]</code>. Arithmetic and comparison givens use binary signs when their world names and arities match the corresponding built-ins.

From weakest to strongest, expressions use lambda or `let`, `or`, `and`, unary `not` or `↓`, non-chained comparisons and membership, sealing, addition/subtraction, multiplication/division/modulo, product `×`, unary minus, then marked terms. A term accepts one free mark; further marked operations need explicit grouping. Mark argument brackets can chain for currying. Statements are expressions optionally followed by a definition, result, signature or law and an optional `⊢` check. Quantified laws may group variables from different domains with commas. Case braces accept a plain value, refinement, or ordered `if`/`else` arms. The printer preserves explicit grouping and emits canonical single spacing.

Here `e` means an expression, `mg` a mark with zero or more atom-argument brackets, `u` an operand and `items` a comma-separated, possibly empty list. The precedence levels above expand to the following statement and term forms:

```text
stmt  := e ('=' e check? | '⇒' e | ':' (signature | '∀' binders '.' e) check?)?
check := '⊢' e | '⊢' '↓' e | '⊢' ('fuel' | 'legacy')
binders := VAR (',' VAR)* '∈' e (',' VAR (',' VAR)* '∈' e)*
e     := 'let' VAR '=' e 'in' e | 'rec' local '=' e check 'in' e
       | 'memo' 'rec' local '=' e check 'in' e | precedence-expression ('↦' e)?
local := mg '(' items ')'
term  := mg (('(' items ')' | '⟨' items '⟩') operand-tail | u | empty)
       | u (mg u?)?
mg    := MARK ('[' items ']')*
u     := VAR | NUM | STR | CONST | '?' | '⊤' | '⊥' | '…'
       | '(' items ')' | '[' items ']' | '⌜' stmt '⌝'
       | '{' e ('}' | '∣' e '}' | (',' ('if' e | 'else') (';' e)?)+ '}')
       | mg ('(' items ')' | '⟨' items '⟩') | program
items := (item (',' item)*)?
item  := e | VAR ':' e | standalone-binary-sign
```

The local recursion binder must use an operation slot. A leading mark followed by `( )` or `⟨ ⟩` is a call; followed by an operand it is prefix, otherwise it is a bare reference. After an operand, a mark is infix if another operand follows and postfix otherwise. An operand with a second free mark needs parentheses. A bare binary sign is an item only before `)`, `,` or `]`; `-` and `not` require this lookahead to distinguish them from unary operators. These rules apply identically to both spellings.

Published definitions also use these extensions to the base grammar:

| Form | Rule |
| --- | --- |
| Strings and literals | Double-quoted JSON-escaped ASCII strings; unary negative numbers, including within lists; booleans `⊤` / `⊥`. |
| Failure and unknown | `fail("reason")` and `unknown("fuel")` each take one parenthesized item. |
| Let | `let x = e in e` binds as weakly as lambda; the word `in` is distinct from membership `∈`. |
| Recursion | `rec ♦ᵣ(x, y) = e ⊢ ↓ m in ♦ᵣ(a, b)`; measures may instead be `fuel` or `legacy`. `memo rec` memoizes it. A matching tail call may print as self-recursion of the defined mark. |
| Constructor atoms | A sort with several forms assigns each form a separate operation mark, such as `♣₄(x, y)` or `♣₅()`. A sort with exactly one declared form, or one form observed in the export when none is declared, calls its object mark instead: `𝔻₁(2, 4)`. The legend lists forms and constructor atoms; records accept named fields such as `pos: (2, 3)`. |
| Objects | Variants sum forms with `+`; product uses `×`; quotient, refinement, constants and template instances use the forms above. |
| Programs | `prog (x = 0, y = 1) entry L0 { L0: x := e; jump L1; L1: halt x }`; `if c jump L1 else L2` terminates conditionally. Labels are uppercase constants with optional digits; other machine labels receive stable `L0`, `L1`, ... names. |
| Names | Variables start lowercase and may then use letters, digits or `_`; reserved keywords (`let in rec fail unknown memo prog entry jump halt fuel legacy if else and or not`) are not variables. The converter appends `_` to conflicting or non-lowercase machine names. Constants are capitalised words (`E`, `P1`, `Metro`); a value form without fields whose name is capitalised prints as that constant, so a route reads `A, D, F` rather than as constructor calls. |

Parsing a formula does not check that a mark is used at the right kind. Kind checking must reject semantically invalid forms, even if they parse. The display and ASCII printers produce canonical text; for canonical formulas, parsing either spelling and printing it back preserves the exact text.

## Example legend

The C examples use a fixed illustrative legend, not a universal name assignment. Givens: `+` add, `*` mul, `@` rev, `#` tri, `ℤ` integers, `𝔹` booleans, `Ŵ` wall, `Û` water and `Ĉ` cell colour. Defined operations: `♠₃` mul (layer 1), `♦₆` f6, `▼₂` g2, `♤₂₈` f28, `♢₉` reduce, `◆₄₁` make, `♢₄₂` num, `♢₄₃` den, `♢₁₄` mod12, `◇₄₄` fmul, `◇₄₆` fadd, `♤₈` head, `♤₉` tail, `♢₁₁` size, `♢₁₂` is_zero, `♡₄₅` double and `♧₄₇` grow. Objects: `𝔻₁` Frac, `ℍ₂` Hour, `𝕄₃` Robot, `𝕂₄` Quot, `𝕋₅` Pair, `𝕊₆` SeenMap, `𝔾₇` Grid and `𝕀₈` Island. Combinators: `Θ₁` twice, `Φ₂` fold, `Ψ₃` until_stable, `Λ₄` twice-of and `Ω₅` compose. Observations: `Ô₁` front_free, `Ŝ₂` red_streak, `Î₃` islands, `Ĵ₄` regions and `Ĥ₅` hand. `≡₁` is mul_comm; `↝₁` is to_grid.

## C1-C20 examples

Each row is one canonical formula in both spellings. Repeated labels are separate examples from the same case; `⇒ ?` asks for an answer rather than asserting one.

| Case | Display | v3-ASCII |
| --- | --- | --- |
| C1 | <code class="n3" data-n3-ascii="a \dia_6 b = { (a @) * b }">a ♦₆ b = { (a @) * b }</code> | <code>a \dia_6 b = { (a @) * b }</code> |
| C2 | <code class="n3" data-n3-ascii="\dn_2 a = { # a, if a &gt;= 59; a \wspade_28 a, else }">▼₂ a = { # a, if a >= 59; a ♤₂₈ a, else }</code> | <code>\dn_2 a = { # a, if a &gt;= 59; a \wspade_28 a, else }</code> |
| C3 | <code class="n3" data-n3-ascii="a ^1\spade_3 b = { 0, if b == 0; a + (a \spade_3 (b - 1)), else }">a ¹♠₃ b = { 0, if b == 0; a + (a ♠₃ (b - 1)), else }</code> | <code>a ^1\spade_3 b = { 0, if b == 0; a + (a \spade_3 (b - 1)), else }</code> |
| C4 | <code class="n3" data-n3-ascii="\bbD_1 = { (n, d) \in \bbZ \x \bbZ \mid d != 0 } / \wdia_9 \seal &#91;\lz_41, \wdia_42, \wdia_43&#93;">𝔻₁ = { (n, d) ∈ ℤ × ℤ ∣ d != 0 } / ♢₉ ↾ [◆₄₁, ♢₄₂, ♢₄₃]</code> | <code>\bbD_1 = { (n, d) \in \bbZ \x \bbZ \mid d != 0 } / \wdia_9 \seal &#91;\lz_41, \wdia_42, \wdia_43&#93;</code> |
| C5 | <code class="n3" data-n3-ascii="\bbD_1(2, 4) =&gt; \bbD_1(1, 2)">𝔻₁(2, 4) ⇒ 𝔻₁(1, 2)</code> | <code>\bbD_1(2, 4) =&gt; \bbD_1(1, 2)</code> |
| C5 | <code class="n3" data-n3-ascii="&#91;1, 2, 3&#93;">[1, 2, 3]</code> | <code>&#91;1, 2, 3&#93;</code> |
| C5 | <code class="n3" data-n3-ascii="\bbH_2(14) =&gt; \bbH_2(2)">ℍ₂(14) ⇒ ℍ₂(2)</code> | <code>\bbH_2(14) =&gt; \bbH_2(2)</code> |
| C5 | <code class="n3" data-n3-ascii="\bbM_3(pos: (2, 3), facing: E)">𝕄₃(pos: (2, 3), facing: E)</code> | <code>\bbM_3(pos: (2, 3), facing: E)</code> |
| C6 | <code class="n3" data-n3-ascii="\bbK_4&#91;\bbX_t, \dia_a&#93; = \bbX_t / \dia_a">𝕂₄[𝕏ₜ, ♦ₐ] = 𝕏ₜ / ♦ₐ</code> | <code>\bbK_4&#91;\bbX_t, \dia_a&#93; = \bbX_t / \dia_a</code> |
| C6 | <code class="n3" data-n3-ascii="\bbT_5&#91;\bbX_t, \bbY_t&#93; = \bbX_t \x \bbY_t">𝕋₅[𝕏ₜ, 𝕐ₜ] = 𝕏ₜ × 𝕐ₜ</code> | <code>\bbT_5&#91;\bbX_t, \bbY_t&#93; = \bbX_t \x \bbY_t</code> |
| C6 | <code class="n3" data-n3-ascii="\bbD_1 = \bbK_4&#91;\bbT_5&#91;\bbZ, \bbZ&#93;, \wdia_9&#93;">𝔻₁ = 𝕂₄[𝕋₅[ℤ, ℤ], ♢₉]</code> | <code>\bbD_1 = \bbK_4&#91;\bbT_5&#91;\bbZ, \bbZ&#93;, \wdia_9&#93;</code> |
| C6 | <code class="n3" data-n3-ascii="\bbH_2 = \bbK_4&#91;\bbZ, \wdia_14&#93;">ℍ₂ = 𝕂₄[ℤ, ♢₁₄]</code> | <code>\bbH_2 = \bbK_4&#91;\bbZ, \wdia_14&#93;</code> |
| C7 | <code class="n3" data-n3-ascii="\wlz_44 : \bbD_1 \x \bbD_1 -&gt; \bbD_1">◇₄₄ : 𝔻₁ × 𝔻₁ → 𝔻₁</code> | <code>\wlz_44 : \bbD_1 \x \bbD_1 -&gt; \bbD_1</code> |
| C7 | <code class="n3" data-n3-ascii="x \wlz_44 y = { \lz_41((\wdia_42 x) \spade_3 (\wdia_42 y), (\wdia_43 x) \spade_3 (\wdia_43 y)) }">x ◇₄₄ y = { ◆₄₁((♢₄₂ x) ♠₃ (♢₄₂ y), (♢₄₃ x) ♠₃ (♢₄₃ y)) }</code> | <code>x \wlz_44 y = { \lz_41((\wdia_42 x) \spade_3 (\wdia_42 y), (\wdia_43 x) \spade_3 (\wdia_43 y)) }</code> |
| C8 | <code class="n3" data-n3-ascii="\Theta_1&#91;\dia_a&#93; x = { \dia_a (\dia_a x) }">Θ₁[♦ₐ] x = { ♦ₐ (♦ₐ x) }</code> | <code>\Theta_1&#91;\dia_a&#93; x = { \dia_a (\dia_a x) }</code> |
| C8 | <code class="n3" data-n3-ascii="\Phi_2&#91;\dia_a&#93;(z, l) = { z, if l == &#91;&#93;; \Phi_2&#91;\dia_a&#93;(z \dia_a (\wspade_8 l), \wspade_9 l), else }">Φ₂&#91;♦ₐ&#93;(z, l) = { z, if l == []; Φ₂&#91;♦ₐ&#93;(z ♦ₐ (♤₈ l), ♤₉ l), else }</code> | <code>\Phi_2&#91;\dia_a&#93;(z, l) = { z, if l == &#91;&#93;; \Phi_2&#91;\dia_a&#93;(z \dia_a (\wspade_8 l), \wspade_9 l), else }</code> |
| C8 | <code class="n3" data-n3-ascii="\Psi_3&#91;\dia_a&#93; x = { x, if (\dia_a x) == x; \Psi_3&#91;\dia_a&#93; (\dia_a x), else } &#124;- \dec \wdia_11">Ψ₃[♦ₐ] x = { x, if (♦ₐ x) == x; Ψ₃[♦ₐ] (♦ₐ x), else } ⊢ ↓ ♢₁₁</code> | <code>\Psi_3&#91;\dia_a&#93; x = { x, if (\dia_a x) == x; \Psi_3&#91;\dia_a&#93; (\dia_a x), else } &#124;- \dec \wdia_11</code> |
| C9 | <code class="n3" data-n3-ascii="\Theta_1&#91;\wheart_45&#93; 3 =&gt; 12">Θ₁[♡₄₅] 3 ⇒ 12</code> | <code>\Theta_1&#91;\wheart_45&#93; 3 =&gt; 12</code> |
| C9 | <code class="n3" data-n3-ascii="\Phi_2&#91;+&#93;(0, &#91;1, 2, 3, 4&#93;) =&gt; 10">Φ₂&#91;+&#93;(0, [1, 2, 3, 4]) ⇒ 10</code> | <code>\Phi_2&#91;+&#93;(0, &#91;1, 2, 3, 4&#93;) =&gt; 10</code> |
| C10 | <code class="n3" data-n3-ascii="\Theta_1&#91;x &#124;-&gt; x * 3&#93; 2 =&gt; 18">Θ₁[x ↦ x * 3] 2 ⇒ 18</code> | <code>\Theta_1&#91;x &#124;-&gt; x * 3&#93; 2 =&gt; 18</code> |
| C11 | <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt; = { not \hatW&lt;&#124;s&#124;&gt; and not \hatU&lt;&#124;s&#124;&gt; }">Ô₁⟨s⟩ = { not Ŵ⟨s⟩ and not Û⟨s⟩ }</code> | <code>\hatO_1&lt;&#124;s&#124;&gt; = { not \hatW&lt;&#124;s&#124;&gt; and not \hatU&lt;&#124;s&#124;&gt; }</code> |
| C12 | <code class="n3" data-n3-ascii="\hatS_2&lt;&#124;&#124;&gt; = 0">Ŝ₂⟨⟩ = 0</code> | <code>\hatS_2&lt;&#124;&#124;&gt; = 0</code> |
| C12 | <code class="n3" data-n3-ascii="\hatS_2&lt;&#124;s&#124;&gt; = { \hatS_2&#x27; + 1, if \hatC&lt;&#124;s&#124;&gt; == R; 0, else }">Ŝ₂⟨s⟩ = { Ŝ₂′ + 1, if Ĉ⟨s⟩ == R; 0, else }</code> | <code>\hatS_2&lt;&#124;s&#124;&gt; = { \hatS_2&#x27; + 1, if \hatC&lt;&#124;s&#124;&gt; == R; 0, else }</code> |
| C13 | <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt; =&gt; \top">Ô₁⟨s⟩ ⇒ ⊤</code> | <code>\hatO_1&lt;&#124;s&#124;&gt; =&gt; \top</code> |
| C13 | <code class="n3" data-n3-ascii="\hatO_1&lt;&#124;s&#124;&gt; =&gt; ?">Ô₁⟨s⟩ ⇒ ?</code> | <code>\hatO_1&lt;&#124;s&#124;&gt; =&gt; ?</code> |
| C14 | <code class="n3" data-n3-ascii="\eqv_1 : \all a, b \in \bbZ. a \spade_3 b == b \spade_3 a">≡₁ : ∀ a, b ∈ ℤ. a ♠₃ b == b ♠₃ a</code> | <code>\eqv_1 : \all a, b \in \bbZ. a \spade_3 b == b \spade_3 a</code> |
| C14 | <code class="n3" data-n3-ascii="(3 \spade_3 5) \eqv_1 (5 \spade_3 3)">(3 ♠₃ 5) ≡₁ (5 ♠₃ 3)</code> | <code>(3 \spade_3 5) \eqv_1 (5 \spade_3 3)</code> |
| C14 | <code class="n3" data-n3-ascii="((a \spade_3 b) \dia_6 c) \eqv_1 ((b \spade_3 a) \dia_6 c)">((a ♠₃ b) ♦₆ c) ≡₁ ((b ♠₃ a) ♦₆ c)</code> | <code>((a \spade_3 b) \dia_6 c) \eqv_1 ((b \spade_3 a) \dia_6 c)</code> |
| C15 | <code class="n3" data-n3-ascii="\squig_1 : \bbS_6 -&gt; \bbG_7 &#124;- \hatI_3&lt;&#124;\squig_1(m)&#124;&gt; == \hatJ_4&lt;&#124;m&#124;&gt;">↝₁ : 𝕊₆ → 𝔾₇ ⊢ Î₃⟨↝₁(m)⟩ == Ĵ₄⟨m⟩</code> | <code>\squig_1 : \bbS_6 -&gt; \bbG_7 &#124;- \hatI_3&lt;&#124;\squig_1(m)&#124;&gt; == \hatJ_4&lt;&#124;m&#124;&gt;</code> |
| C15 | <code class="n3" data-n3-ascii="\squig_1(m)">↝₁(m)</code> | <code>\squig_1(m)</code> |
| C16 | <code class="n3" data-n3-ascii="(\bbD_1(1, 2) \wlz_46 \bbD_1(1, 3)) \wlz_44 \bbD_1(3, 5) =&gt; ?">(𝔻₁(1, 2) ◇₄₆ 𝔻₁(1, 3)) ◇₄₄ 𝔻₁(3, 5) ⇒ ?</code> | <code>(\bbD_1(1, 2) \wlz_46 \bbD_1(1, 3)) \wlz_44 \bbD_1(3, 5) =&gt; ?</code> |
| C17 | <code class="n3" data-n3-ascii="\hatI_3&lt;&#124;\Psi_3&#91;\wclub_47&#93; \bbI_8((0, 0), (1, 0))&#124;&gt; =&gt; ?">Î₃⟨Ψ₃[♧₄₇] 𝕀₈((0, 0), (1, 0))⟩ ⇒ ?</code> | <code>\hatI_3&lt;&#124;\Psi_3&#91;\wclub_47&#93; \bbI_8((0, 0), (1, 0))&#124;&gt; =&gt; ?</code> |
| C18 | <code class="n3" data-n3-ascii="a ^1\spade_3 b = { 0, if b == 0; a + (a \spade_3 (b - 1)), else }">a ¹♠₃ b = { 0, if b == 0; a + (a ♠₃ (b - 1)), else }</code> | <code>a ^1\spade_3 b = { 0, if b == 0; a + (a \spade_3 (b - 1)), else }</code> |
| C18 | <code class="n3" data-n3-ascii="(+) : \bbZ \x \bbZ -&gt; \bbZ">(+) : ℤ × ℤ → ℤ</code> | <code>(+) : \bbZ \x \bbZ -&gt; \bbZ</code> |
| C19 | <code class="n3" data-n3-ascii="{ x, if a &lt; b and not (\wdia_12 c); y, else }">{ x, if a < b and not (♢₁₂ c); y, else }</code> | <code>{ x, if a &lt; b and not (\wdia_12 c); y, else }</code> |
| C20 | <code class="n3" data-n3-ascii="\hatH_5&lt;&#124;P1, s&#124;&gt;">Ĥ₅⟨P1, s⟩</code> | <code>\hatH_5&lt;&#124;P1, s&#124;&gt;</code> |
