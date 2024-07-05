# PgBouncer revision 89

<sub>February 21, 2024</sub>

Dear community, we are excited to announce that the new Charmed PgBouncer operator is published in the `1/stable` [charmhub](https://charmhub.io/pgbouncer?channel=1/stable) channel for IAAS/VM.

## New features

* Juju 3.1.7 support (changes to Juju secrets)
* Charmed PostgreSQL snap updated from revision 89 to the revision 98
* Updated Python library dependencies ([#128](https://github.com/canonical/pgbouncer-operator/pull/128))

## Bugfixes

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/pgbouncer-operator/issues) platforms. [GitHub Releases](https://github.com/canonical/pgbouncer-operator/releases) provide a detailed list of bugfixes/PRs/commits for each revision.

### Highlights for the current revision

* Removed binary python dependencies and build psycopg from source ([#128](https://github.com/canonical/pgbouncer-operator/pull/128))
* GH Action migrated to [data platform shared workflows](https://github.com/canonical/data-platform-workflows/)
* Juju Secrets fixes provided by updated data Interfaces library (LIBPATCH 25)

## Inside the charms

* Charmed PgBouncer ships the latest PgBouncer `1.21.0-0ubuntu0.22.04.1~ppa1`
* The Prometheus pgbouncer-exporter is "0.7.0-0ubuntu0.22.04.1~ppa1"
* VM charms based on [Charmed PostgreSQL](https://snapcraft.io/charmed-postgresql) SNAP (Ubuntu LTS `22.04` - ubuntu:22.04-based) ([updated](https://warthogs.atlassian.net/browse/DPE-3040) from revision 89 to 98)
* Principal charms support the latest LTS series `22.04` only
* Subordinate charms support LTS `22.04` and `20.04` only

## Technical notes

* Upgrade via `juju refresh` is possible from revision 81+.
* Please check [the external components requirements](/t/12307?channel=1/stable)
* Note: [juju 3.1.6 doesn't report](https://bugs.launchpad.net/juju/+bug/2037279) when `pre-upgrade-check` action fails. Therefore, it is recommended to redeploy pgbouncer charm on Juju 3.1.7+
* Use this operator together with the [Charmed PostgreSQL](https://charmhub.io/postgresql) operator

## Contact

[Open a GitHub issue](https://github.com/canonical/pgbouncer-operator/issues) if you want to submit a bug report, or [contribute](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md) to the project!

Check our [Contacts](/t/12305) page for more ways to reach us.