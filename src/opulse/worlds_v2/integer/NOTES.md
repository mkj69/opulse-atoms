# Integer depth world (version 2)

Layer zero has finite signed integers, counted successor, addition, negation, gcd, and the granted `value` probe. Generic strict arithmetic, pair, and list primitives provide storage and measures. The given `@sequence` has a public kernel body. `is_cf_data` checks whether a value is strict list storage; it does not compute coefficients. No numerical upper bound is imposed; insufficient execution fuel yields `Unknown(fuel)`.

| Design layer | Kind | Invention | Bounded evidence scope | Example atom steps |
| --- | --- | --- | --- | ---: |
| 1 | object | nonnegative Nat | 61 integers -20..40 | 6 |
| 2 | combinator | counted unary repeat | 50 seed/count pairs (-2..2, 0..9) x 2 slots (succ, neg) = 100 checks | 79 |
| 3 | operation | signed repeated-addition mul | 169 signed pairs -6..6 | 191 |
| 4 | object | canonical sealed Frac | 169 integer pairs -6..6 | 112 |
| 5 | observation | whole-fraction decision | 65 distinct canonical fractions (numerator -6..6, denominator 1..8) | 14 |
| 6 | operation | normalized rational addition | 100 pairs from 10 canonical fractions | 732 |
| 7 | operation | normalized rational multiplication | 100 pairs from 10 canonical fractions | 576 |
| 8 | combinator | left fraction fold | all 85 lists length 0..3 from 4 fractions, seed 0/1, x 2 slots (qadd, qmul) = 170 checks | 1305 |
| 9 | operation | Euclidean floor quotient and remainder | 151 signed/positive pairs incl zero divisor | 99 |
| 10 | object | finite canonical CF expansion | 44 fractions -5..5 over 1..4 and five invalid digit lists | 144 |
| 11 | combinator | all prefix convergents | 65 distinct rational expansions x 2 slots (cf_step, pair) = 130 checks | 966 |
| 12 | observation | last convergent within denominator bound | 65 distinct rational expansions, bounds cycling 0..4 | 1001 |

All three showcase answers are kernel-checked, including an exhaustive inversion over 128 candidates. `cf_step` is a separately verified lower-level helper on nine initial-state/digit inputs. The convergents `pair` slot is an intentionally non-convergent operation: nonempty expansions fail with `Bottom(type)` and are checked against the independent slot oracle. The export retains design layer numbers and records actual computed dependency depths as `def_layer`. All twelve published examples are checked against the independent depth reference; the failure example produces `Bottom(no_convergent)`.

Core refinements now use `nat.make`, `frac.make`, and `cf.make`; invented object names are not callable. `Frac` stores a normalized pair inside the core's `val` wrapper, and `CF` stores its digit list there. The core checks objects and verifies canon totality, idempotence, and validity preservation. Domain rejection by these constructors is `Bottom(invalid)` rather than the old constructor-specific errors. Operation slots use JSON-compatible `FnRef` literals. `@repeat` remains unary; multiplication unfolds it to obtain the count before recursing through addition. The generic exact quotient only divides known gcd multiples; `cf_divmod` still invents Euclidean quotient/remainder.

`Frac` remains sealed: downstream arithmetic uses the layer-zero `numerator` and `denominator` projections instead of the private `frac.base`, which cannot satisfy `respects_canon` on distinct pre-normalization representations. `CF` remains sealed and exposes only its constructor and base accessor. Core combinator verification now omits empty `fixed_ops` without an adapter.

Polish: `CF` rejects empty and noncanonical list expansions using a measured kernel-level digit check; layer-zero hosts no longer mint `frac`, `cf`, or `nat` cards. All twelve original tower values remain unchanged. On the current core, refined entry and accessor checks change measured example steps as recorded above. Five arithmetic laws pass the core law pipeline on bounded integer tuples; a promoted `#mul_comm` performs one verified rewrite with layer-zero replay and refuses out-of-scope operands. The sort-typed `Quot[T, canon]` template verifies `Pair<Int, Int>` via `reduce_ratio` and `Int` via `mod12`, producing independently verified `QuotFrac` and `Hour`. The original tower `Frac` remains separate; `QuotFrac` is its template-built counterpart.

Remaining adapters: `check_local` handles only five definitions with polymorphic signatures or direct arithmetic observations; all other definitions use core checking. `IntegerLibrary._params` and `IntegerLibrary.verify` bridge direct observations that the core's truth-state probe model rejects; their evidence binds the exact checked domain. `IntegerLibrary.write` includes template object valid/canon references missing from core instantiation dependencies. Objects, combinators, laws, templates and operations use core verification. `CF` declares its actual list storage base so refined accessors reject forged cards. The full export comparison is marked slow; all finite checks and showcases still run in the normal suite.

The displayed design layer is a teaching order, while `def_layer` is the computed dependency depth. Card `frac` uses gcd/quotient, not preceding `mul`; `whole` uses the fraction denominator, not `frac.make`; `qadd` uses `mul`, not preceding `whole`; `qmul` uses `mul`, not preceding `qadd`; `fold_frac` calls its supplied slot, not the preceding `qmul` by name; `cf_divmod` uses layer-zero arithmetic, not `fold_frac`; `convergents` calls its supplied step, not `cf_step` by name. Full fresh export takes over 60 seconds and runs with `OPULSE_RUN_SLOW=1`; default tests freshly build every promoted definition and independently build the first three cards without a cache.

ASCII export: a story declaration is published only when the core printer emits a declaration whose parsed body matches the real stored definition. The original design text stays in `design_decl`/`design_text`. Core `parse_expr` treats `Frac<...>`, `CF<...>`, `Hour<...>`, and `QuotFrac<...>` as literal cards, not the constructor calls evaluated by this world's legacy expression parser. Example values, steps, traces, and evidence are unchanged.
nat: printer unavailable — invalid declaration name.
repeat: printer unavailable — invalid ASCII identifier.
mul: printer unavailable — invalid ASCII identifier.
frac: printer unavailable — invalid declaration name.
qadd: printer unavailable — invalid ASCII identifier.
qmul: printer unavailable — invalid ASCII identifier.
cf_divmod: printer unavailable — operation metadata has no compact ASCII declaration.
cf: printer unavailable — invalid declaration name.
convergents: printer unavailable — invalid ASCII identifier.
bounded_convergent: printer unavailable — invalid ASCII identifier.
add_comm: printer unavailable — printed definition does not re-parse to stored body.
mul_distrib: printer unavailable — printed definition does not re-parse to stored body.
Quot: printer unavailable — unsupported template metadata.
quot_frac: printer unavailable — invalid declaration name.
hour: printer unavailable — invalid declaration name.
