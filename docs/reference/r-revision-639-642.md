>Reference > Release Notes > [All revisions] > Revision 639-642

# Revision 639/640/641/642
February 4, 2025

Dear community,

Canonical's newest Charmed PgBouncer operator has been published in the [1/stable channel]:
* Revision 639 is built for `amd64` on Ubuntu 22.04 LTS
* Revision 640 is built for `amd64` on Ubuntu 20.04 LTS
* Revision 642 is built for `arm64` on Ubuntu 22.04 LTS
* Revision 641 is built for `arm64` on Ubuntu 20.04 LTS 

If you are jumping over several stable revisions, check [previous release notes][All revisions] before upgrading.

---

## Highlights 

* Updated juju 2 version to `v2.9.51` ([PR #375](https://github.com/canonical/pgbouncer-operator/pull/375))
* Updated juju 3 version to `v3.6.1+` ([PR#449](https://github.com/canonical/pgbouncer-operator/pull/449)), ([PR #377](https://github.com/canonical/pgbouncer-operator/pull/377)) 

## Features and improvements

* Retrieve charm tracing libs from `tempo_coordinator_k8s`  ([PR #386](https://github.com/canonical/pgbouncer-operator/pull/386))
* Relay traces traffic through `grafana-agent` and test integration with Tempo HA ([PR #397](https://github.com/canonical/pgbouncer-operator/pull/397))
* Enable round-robin connections to read-only backend nodes ([PR #393](https://github.com/canonical/pgbouncer-operator/pull/393)) ([DPE-5613](https://warthogs.atlassian.net/browse/DPE-5613))

## Bugfixes and maintenance

* General secrets resetting fix for Juju 3.6+ ([PR#449](https://github.com/canonical/pgbouncer-operator/pull/449))[[DPE-6320](https://warthogs.atlassian.net/browse/DPE-6320)][[DPE-6325](https://warthogs.atlassian.net/browse/DPE-6325)] 
* PgBouncer COS dashboard bugfixes ([PR#438](https://github.com/canonical/pgbouncer-operator/pull/438))
* Make tox commands resilient to whitespace paths ([PR #413](https://github.com/canonical/pgbouncer-operator/pull/413)) ([DPE-6042](https://warthogs.atlassian.net/browse/DPE-6042))
* Fixed missing IP errors ([PR #353](https://github.com/canonical/pgbouncer-operator/pull/353))
* Don't set secrets until db is set ([PR #373](https://github.com/canonical/pgbouncer-operator/pull/373)) ([DPE-5564](https://warthogs.atlassian.net/browse/DPE-5564))
* Increased ruff rules ([PR #390](https://github.com/canonical/pgbouncer-operator/pull/390))
* Disabled conflicting build ([PR #371](https://github.com/canonical/pgbouncer-operator/pull/371))
* Stopped tracking channel for held snaps ([PR #384](https://github.com/canonical/pgbouncer-operator/pull/384))
* Handle secret permission error ([PR #358](https://github.com/canonical/pgbouncer-operator/pull/358))

[details=Libraries, testing, and CI]

* Migrate to charmcraft 3 poetry plugin ([PR#448](https://github.com/canonical/pgbouncer-operator/pull/448))
* Attempt to run tests on juju 3.6/candidate on a nightly schedule ([PR #402](https://github.com/canonical/pgbouncer-operator/pull/402)) ([DPE-5622](https://warthogs.atlassian.net/browse/DPE-5622))
* Re-enable cached builds ([PR #406](https://github.com/canonical/pgbouncer-operator/pull/406))
* Use the same build job in release and ci workflows ([PR #403](https://github.com/canonical/pgbouncer-operator/pull/403))
* Switch to team reviewer ([PR #351](https://github.com/canonical/pgbouncer-operator/pull/351))
* Disable cached builds ([PR #369](https://github.com/canonical/pgbouncer-operator/pull/369))
* Run juju 3.6 nightly tests against 3.6/stable ([PR #417](https://github.com/canonical/pgbouncer-operator/pull/417))
* Lock file maintenance Python dependencies ([PR #423](https://github.com/canonical/pgbouncer-operator/pull/423))
* Migrate config .github/renovate.json5 ([PR #407](https://github.com/canonical/pgbouncer-operator/pull/407))
* Switch from tox build wrapper to charmcraft.yaml overrides ([PR #370](https://github.com/canonical/pgbouncer-operator/pull/370))
* Update canonical/charming-actions action to v2.6.3 ([PR #354](https://github.com/canonical/pgbouncer-operator/pull/354))
* Update codecov/codecov-action action to v5 ([PR #408](https://github.com/canonical/pgbouncer-operator/pull/408))
* Update data-platform-workflows to v23.1.0 ([PR #418](https://github.com/canonical/pgbouncer-operator/pull/418))
* Split python dependency for cryptography v44 compatibility ([PR #421](https://github.com/canonical/pgbouncer-operator/pull/421))
[/details]

<!-- Did not include these
* Disabled self hosted packing and integration tests ([PR #414](https://github.com/canonical/pgbouncer-operator/pull/414))
* Use self-hosted runners when packing the charm ([PR #396](https://github.com/canonical/pgbouncer-operator/pull/396)) ([DPE-5642](https://warthogs.atlassian.net/browse/DPE-5642))
* Use self-hosted runners for integration tests ([PR #412](https://github.com/canonical/pgbouncer-operator/pull/412))
-->

## Requirements and compatibility
<!--TODO: workload, juju, or other important version changes -->

See the [system requirements] for more details about Juju versions and other software and hardware prerequisites.

### Packaging

This charm is based on the Charmed PgBouncer [snap] . It packages:
* [pgbouncer] `v.1.21`
* [prometheus-pgbouncer-exporter] `v.0.7.0`

See the [`/lib/charms` directory on GitHub] for more details about all supported libraries.

See the [`metadata.yaml` file on GitHub] for a full list of supported interfaces.


<!-- Topics -->
[All revisions]: /t/12285
[system requirements]: /t/12307

<!-- GitHub -->
[`/lib/charms` directory on GitHub]: https://github.com/canonical/pgbouncer-operator/tree/main/lib/charms
[`metadata.yaml` file on GitHub]: https://github.com/canonical/pgbouncer-operator/blob/main/metadata.yaml

<!-- Charmhub -->
[1/stable channel]: https://charmhub.io/pgbouncer?channel=1/stable

<!-- Snap/Rock -->
[`charmed-pgbouncer` packaging]: https://github.com/canonical/charmed-pgbouncer-snap

[snap]: https://github.com/canonical/charmed-pgbouncer-snap/
[rock image]: https://github.com/orgs/canonical/packages?repo_name=charmed-pgbouncer-rock

[pgbouncer]: https://launchpad.net/~data-platform/+archive/ubuntu/pgbouncer
[prometheus-pgbouncer-exporter]: https://launchpad.net/~data-platform/+archive/ubuntu/pgbouncer-exporter


<!-- Badges -->
[juju-2_amd64]: https://img.shields.io/badge/Juju_2.9.51-amd64-darkgreen?labelColor=ea7d56 
[juju-3_amd64]: https://img.shields.io/badge/Juju_3.4.6-amd64-darkgreen?labelColor=E95420 
[juju-3_arm64]: https://img.shields.io/badge/Juju_3.4.6-arm64-blue?labelColor=E95420