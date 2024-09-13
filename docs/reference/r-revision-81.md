# PgBouncer revision 81
<sub>Thuesday, December 7, 2023</sub>

Dear community, this is to inform you that new PgBouncer is published in `1/stable` [charmhub](https://charmhub.io/pgbouncer?channel=1/stable) channel for IAAS/VM.

## The features you can start using today:

* PgBouncer is updated from 1.18 to 1.21 [[DPE-3040](https://warthogs.atlassian.net/browse/DPE-3040)]
* Updated Python library dependencies [[GH PR#158](https://github.com/canonical/pgbouncer-k8s-operator/pull/158)]

## Bugfixes included:
* Juju Secrets fixes provided by updated data Interfaces library (LIBPATCH 24)
* Ported K8s fix for [GitHub Issue #166](https://github.com/canonical/pgbouncer-k8s-operator/issues/166) to VM charm [[DPE-3113](https://warthogs.atlassian.net/browse/DPE-3113)]

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/pgbouncer-operator/issues) platforms.<br/>[GitHub Releases](https://github.com/canonical/pgbouncer-operator/releases) provide a detailed list of bugfixes/PRs/commits for each revision.


## What is inside the charms:

* Charmed PgBouncer ships the latest PgBouncer “1.21.0-0ubuntu0.22.04.1~ppa1”
* The Prometheus pgbouncer-exporter is "0.7.0-0ubuntu0.22.04.1~ppa1"
* VM charms based on [Charmed PostgreSQL](https://snapcraft.io/charmed-postgresql) SNAP (Ubuntu LTS “22.04” - ubuntu:22.04-based) ([updated](https://warthogs.atlassian.net/browse/DPE-3040) from the revision 85 to the revision 89)
* Principal charms support the latest LTS series “22.04” only
* Subordinate charms support LTS “22.04” and “20.04” only

## Technical notes:

* Upgrade (`juju refresh`) is possible from this revision 76+
* Please check [the external components requirements](/t/12307?channel=1/stable)
* Use this operator together with a modern operator "[Charmed PostgreSQL](https://charmhub.io/postgresql)"

## How to reach us:

If you would like to chat with us about your use-cases or ideas, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/data-platform) or [Discourse](https://discourse.charmhub.io/). Check all other contact details [here](/t/12305).

Consider [opening a GitHub issue](https://github.com/canonical/pgbouncer-operator/issues) if you want to open a bug report.<br/>[Contribute](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md) to the project!