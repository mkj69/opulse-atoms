# Contributing to Opulse

This file has the technical steps for working on Opulse.

Small contributions are welcome: a fixed typo, a clearer sentence or a failing command reported
with its seed all count.

## Where to ask

* Questions, experiment ideas and results: [GitHub Discussions](https://github.com/mkj69/opulse-atoms/discussions).
* Bugs, wrong answers, wrong derivation steps and documentation errors:
  [GitHub Issues](https://github.com/mkj69/opulse-atoms/issues).

If you are unsure where something belongs, open a discussion. Every message is read.

## Development setup

Use Python 3.10. The committed evidence records hash the bytecode of the world
implementations, which differs between Python versions, so the evidence checks and the test
suite pass only on Python 3.10; CI runs Python 3.10 only.

```bash
git clone https://github.com/mkj69/opulse-atoms.git && cd opulse-atoms
python3.10 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,site]"       # opulse, z3-solver, sympy, numpy, pyyaml, pytest, hypothesis, ruff, mkdocs
```

Opulse runs from a source checkout. The worlds, their declarations and the site data live in
the repository next to `src/`, and the library reads them from there, so always install it in
editable mode (`-e`) from the clone. A plain `pip install .` copies only the Python package and
the world files will not be found. The `site` extra adds MkDocs and the packages the site tests
import; CI installs exactly `.[dev,site]`. A few tests run JavaScript and need Node.js 18 or
newer on `PATH` (or set `OPULSE_NODE` to the `node` binary).

## Tests

```bash
python -m pytest -q                # the full test suite
python tools/sweep.py --quick      # the pipeline under 11 settings, under a minute
python tools/sweep.py              # all 298 configurations, before a change to generation or semantics
```

A pull request should keep both green. A change to the semantics, the interpreter, generation,
the step checker or the solvers should come with a test that fails without it.

## Code style

Opulse uses [ruff](https://docs.astral.sh/ruff/) for linting. Run it on the files you change:

```bash
ruff check path/to/changed_file.py
```

Some older files still have findings; please do not mix unrelated lint fixes into a functional
change. Keep functions small, name things after what they compute, and write docstrings for
public functions.

## Adding a world

Keep source declarations and exported definitions in the ASCII machine notation. The site
generates notation v3 display formulas from those definitions and a per-world legend;
copying a displayed formula uses the separate v3-ASCII spelling. See
[notation v3](docs/reference/notation-v3.md) for its symbol table and examples.

A world is a declaration in `worlds/decl/v2/`. It lists layer 0 (the given objects, operations,
combinators and observations) and the kinds that are open for invention.
[Create a world](https://mkj69.github.io/opulse-atoms/build/world/) shows how to write one, and
the [world catalog](https://mkj69.github.io/opulse-atoms/worlds/) shows the worlds that exist.
Please include a test that loads the declaration and runs its definitions on checked inputs.

The older operation only workflow (Legacy-v1) registers atoms with `register_primitive` and
loads them with `--plugin`.

## Documentation

The site lives in `docs/` and is built with MkDocs Material. Build it before you open a pull
request; `--strict` turns warnings, including broken links between pages, into errors:

```bash
python -m mkdocs build --strict -f mkdocs.yml    # writes site/; CI runs the same build
```

`./tools/build_site.sh` runs the same build after refreshing the Python files of the playground
page. The site is English only.

The published site is served by GitHub Pages from the `gh-pages` branch. That branch holds only
the output of `mkdocs build --strict` (the `site/` folder with a `.nojekyll` file), built from a
commit whose full test suite passed. There is no Pages workflow: the maintainer builds the site,
checks it, and pushes the `site/` folder as the single commit of `gh-pages`. Pull requests change
`docs/` and never `gh-pages`.

Style rules for every page:

* No dashes of any kind in prose: no em dash, en dash or hyphen joining words. Rewrite the
  sentence instead. Code, commands and flags are exempt.
* State facts with evidence: a number, a command, a link to a check. Leave out hype, filler and
  words that only sound impressive.
* No progress or roadmap wording. Describe what the code does now. The experiment ideas say
  plainly that none has been run yet; keep it that way until a result exists.

## Releases

Opulse is used from a source checkout. PyPI publishing is not set up: a wheel would not contain
the world files, so no `v*` tag is created and `release.yml` does not run.

## Commits and pull requests

1. Fork the repository and create a branch from `main`.
2. Keep each commit to one change. Write the subject as `area: what changed`, for example
   `bench: score the first wrong rewrite` or `docs: clarify recursion bounds`.
3. Run the tests, the quick sweep, ruff on your files, and the docs builds if you touched docs.
4. Open a pull request that says what changed, why, and how you checked it. Link the issue or
   discussion it comes from.

Review happens in the pull request. A request for changes is part of the work, not a judgement
of you.

## Licences

By contributing, you agree that your code is released under the Apache License 2.0, and that
your documentation and data are released under the Creative Commons Attribution 4.0 International
licence (CC BY 4.0), the same terms as the rest of the project.

## Contributors

See the [GitHub contributors page](https://github.com/mkj69/opulse-atoms/graphs/contributors) for contributors; people whose ideas lead to experiments are credited by name in those experiments.

## Code of conduct

Everyone who takes part follows the [code of conduct](CODE_OF_CONDUCT.md).
