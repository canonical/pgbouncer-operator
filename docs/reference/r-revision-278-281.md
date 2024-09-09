>Reference > Release Notes > [All revisions](/t/12285) > Revisions 278/279/281/281

# Revisions 278/279/281/281
<sub>July 30, 2024</sub>

Dear community,

We'd like to announce that Canonical's newest Charmed PgBouncer operator has been published in the 1/stable [channel](https://charmhub.io/pgbouncer?channel=1/stable) :tada: :

|AMD64|ARM64|
|---|---|
 279 (focal) </br> 278 (jammy)  | 281 (focal) </br> 280 (jammy) |

[note]
If you are jumping over several stable revisions, make sure to check [previous release notes](/t/12285?channel=1/stable) before upgrading to this revision.
[/note]  

## Features you can start using today

* No new features, bugfixes release only.

## Bugfixes and improvements

* [[DPE-4772](https://warthogs.atlassian.net/browse/DPE-4772)] Scaled up client should join the DB only when the subordinate is ready in [#274](https://github.com/canonical/pgbouncer-operator/pull/274)
* [[DPE-4811](https://warthogs.atlassian.net/browse/DPE-4811)] Run CI on 3.4.4 in [#283](https://github.com/canonical/pgbouncer-operator/pull/283)
* [[DPE-4816](https://warthogs.atlassian.net/browse/DPE-4816)] Add jinja2 as a dependency in [#276](https://github.com/canonical/pgbouncer-operator/pull/276)
* [MISC] Suppress alias creation error in [#284](https://github.com/canonical/pgbouncer-operator/pull/284)
* Test and CI stabilization fixes
* Python dependencies updates

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/pgbouncer-operator/issues) platforms.  
[GitHub Releases](https://github.com/canonical/pgbouncer-operator/releases) provide a detailed list of bugfixes, PRs, and commits for each revision.  

## Inside the charms

* Charmed PgBouncer ships the latest PgBouncer `1.21.0-0ubuntu0.22.04.1~ppa1`
* The Prometheus pgbouncer-exporter is “`0.7.0-0ubuntu0.22.04.1~ppa1`”
* VM charms based on the [Charmed PgBouncer snap](https://snapcraft.io/charmed-pgbouncer) revisions 3 (`amd64`) and 4 (`arm64`).

  **Note**: This release of the PgBouncer charm uses the new [`charmed-pgbouncer` snap](https://snapcraft.io/charmed-pgbouncer). In [previous releases](/t/12285?channel=1/stable), it was based on the `charmed-postgresql` snap.  Upgrading will automatically switch the snaps.

* Subordinate charms support LTS `22.04`(jammy) and `20.04`(focal) only  

## Technical notes

* Check PgBouncer's [system requirements](https://charmhub.io/pgbouncer/docs/r-requirements?channel=1/stable)
* Use this operator together with the [Charmed PostgreSQL](https://charmhub.io/postgresql) operator  

## Contact us

Charmed PgBouncer is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/pgbouncer-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.