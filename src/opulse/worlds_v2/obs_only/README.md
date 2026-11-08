# obs_only

The blind 64-cell corridor opens **observation** inventions only. Fixed public
operations provide exact rational arithmetic and generic list operations; public
prior, protocol and history readings are granted probes. No fixed host calculates
posterior, credible sets, or risk decisions; the referee's sealed position and
private draws never enter a learner observation. Ten observations are written, checked, made
callable, verified against the independent reference, and promoted in story order.

`worlds/decl/v2/obs_only@1.json` declares the world; the binding design is in
`worlds/catalogue/depth/obs_only.json`. Generate the checked docs asset with
`python -m opulse.worlds_v2.obs_only.declgen` followed by
`python -m opulse.worlds_v2.obs_only.export` and
`python -m opulse.worlds_v2.index`. Run the regression suite with
`pytest tests/worlds_v2/obs_only`.

The tasks declaration keeps `State` as the observation truth sort so invented
observations cannot accept sealed state as a public input. Probe metadata uses
that common truth sort as required by tasks validation, while the hosts still
accept only their original public `Trace` or `PublicConfig` arguments; no
private draws enter the export.
