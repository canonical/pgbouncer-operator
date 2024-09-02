# PgBouncer revision 77
<sub>Monday, October 23, 2023</sub>

Dear community, this is to inform you that new PgBouncer is published in `1/stable` [charmhub](https://charmhub.io/pgbouncer?channel=1/stable) channel for IAAS/VM.

## The features you can start using today:

* [Add Juju 3 support](/t/12307) (Juju 2 is still supported) [[DPE-1761](https://warthogs.atlassian.net/browse/DPE-1761)]
* Juju peer and relation secrets support [[DPE-1765](https://warthogs.atlassian.net/browse/DPE-1765)][[DPE-2299](https://warthogs.atlassian.net/browse/DPE-2299)] 
* Charm [minor upgrades](/t/12317) and [minor rollbacks](/t/12316) [[DPE-1770](https://warthogs.atlassian.net/browse/DPE-1771)]
* ["Charmed PostgreSQL" extensions support](https://charmhub.io/postgresql/docs/h-enable-plugins) [[DPE-2055](https://warthogs.atlassian.net/browse/DPE-2055)]
* [COS support](/t/12308) [[DPE-1778](https://warthogs.atlassian.net/browse/DPE-1778)]
* Logs rotation [[DPE-1757](https://warthogs.atlassian.net/browse/DPE-1757)]
* The "[data-integrator](https://charmhub.io/data-integrator)" support
* [Support](https://charmhub.io/pgbouncer/integrations?channel=1/stable) for modern `postgresql_client`, legacy `pgsql` and `tls-certificates` interfaces
* Workload updated to [PgBouncer 1.18](https://www.pgbouncer.org/changelog.html) (fixes for PostgreSQL 14)
* [Complete documentation on CharmHub](https://charmhub.io/pgbouncer?channel=1/stable)

## Bugfixes included:

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/pgbouncer-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/pgbouncer-operator/releases) provide a detailed list of bugfixes/PRs/Git commits for each revision.

## What is inside the charms:

* Charmed PgBouncer ships the latest PgBouncer “1.18.0-0ubuntu0.22.04.1”
* The Prometheus pgbouncer-exporter is "0.7.0-0ubuntu0.22.04.1~ppa1"
* VM charms based on [Charmed PostgreSQL](https://snapcraft.io/charmed-postgresql) SNAP (Ubuntu LTS “22.04” - ubuntu:22.04-based)
* Principal charms supports the latest LTS series “22.04” only.
* Subordinate charms support LTS “22.04” and “20.04” only.

## Technical notes:

* Upgrade (`juju refresh`) is possible from this revision 77+.
* Please check [the external components requirements](/t/12307?channel=1/stable)
* Use this operator together with a modern operator "[Charmed PostgreSQL](https://charmhub.io/postgresql)".

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/data-platform) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/TODO).

Consider [opening a GitHub issue](https://github.com/canonical/pgbouncer-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md) to the project!

## Footer:

It is the first stable release of the operator "PgBouncer" by Canonical Data.<br/>Well done, Team!