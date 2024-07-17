>Reference > Release Notes > [All revisions](/t/12285) > Revisions 254/255/256/257

# Revisions 254/255/256/257
<sub>Jul 16, 2024</sub>

Dear community,

We'd like to announce that Canonical's newest Charmed PgBouncer operator has been published in the 1/stable [channel](https://charmhub.io/pgbouncer?channel=1/stable) :tada: :

<!--TODO: different revisions for focal/jammy? amd/arm?-->

|AMD64|ARM64|
|---|---|
 255 (focal) </br> 256 (jammy)  | 254 (focal) </br> 257 (jammy) |

[note]
If you are jumping over several stable revisions, make sure to check [previous release notes](/t/12285?channel=1/stable) before upgrading to this revision.
[/note]  

## Features you can start using today

<!--TODO: add notable features-->

* [PR #210](https://github.com/canonical/pgbouncer-operator/pull/210) - Added support for multiple databases
* [PR #238](https://github.com/canonical/pgbouncer-operator/pull/238) - Added support for tracing through `tempo-k8s`

## Bugfixes and improvements

* [PR #227](https://github.com/canonical/pgbouncer-operator/pull/227) - Fixed PGB permissions issue when dropping tables after re-relating
* [PR #254](https://github.com/canonical/pgbouncer-operator/pull/254) - Fixed failure when collecting readonly dbs
* [PR #257](https://github.com/canonical/pgbouncer-operator/pull/257) - Fixed desync issue with PGB reporting the endpoint and credential of the database before being able to serve.
* [PR #268](https://github.com/canonical/pgbouncer-operator/pull/268) - Fixed upgrade bugs when switching charms

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/pgbouncer-operator/issues) platforms.  
[GitHub Releases](https://github.com/canonical/pgbouncer-operator/releases) provide a detailed list of bugfixes, PRs, and commits for each revision.  

## Inside the charms

<!--TODO: check that the ppa and snap versions in this section are up to date-->

* Charmed PgBouncer ships the latest PgBouncer `1.21.0-0ubuntu0.22.04.1~ppa1`
* The Prometheus pgbouncer-exporter is “`0.7.0-0ubuntu0.22.04.1~ppa1`”
* VM charms based on the [Charmed PgBouncer snap](https://snapcraft.io/charmed-pgbouncer) revisions 3 (`amd64`) and 4 (`arm64`).
[note]
**Note**: This release of the PgBouncer charm uses the new [`charmed-pgbouncer` snap](https://snapcraft.io/charmed-pgbouncer). In [previous releases](/t/12285?channel=1/stable), it was based on the `charmed-postgresql` snap. 

Upgrading will automatically switch the snaps.
[/note]

* Subordinate charms support LTS `22.04`(jammy) and `20.04`(focal) only  

## Technical notes

* Check PgBouncer's [system requirements](https://charmhub.io/pgbouncer/docs/r-requirements?channel=1/stable)
* **Note**: [juju 3.1.6 doesn’t report](https://bugs.launchpad.net/juju/+bug/2037279) when `pre-upgrade-check` action fails. Therefore, it is recommended to redeploy pgbouncer charm on Juju 3.1.7+
* Use this operator together with the [Charmed PostgreSQL](https://charmhub.io/postgresql) operator  

## Contact us

Charmed PgBouncer is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/pgbouncer-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.