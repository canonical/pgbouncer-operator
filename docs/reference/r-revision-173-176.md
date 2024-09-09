>Reference > Release Notes > [All revisions](/t/12285) > Revision 173/174/175/176  
# Revisions 173/174/175/176

<sub>18 May, 2024</sub>

Dear community,

We'd like to announce that Canonical's newest Charmed PgBouncer operator has been published in the 1/stable [channel](https://charmhub.io/pgbouncer?channel=1/stable) :tada: 

|AMD64|ARM64|
|---|---|
| [174 (`jammy`) </br>175 (`focal`)](https://charmhub.io/pgbouncer/docs/r-releases-rev173?channel=1/stable) | [173 (`jammy`) </br> 176 (`focal`)](https://charmhub.io/pgbouncer/docs/r-releases-rev173?channel=1/stable) |

[note]
If you are jumping over several stable revisions, make sure to check [previous release notes](/t/12285?channel=1/stable) before upgrading to this revision.
[/note]  

## Features you can start using today

* [New ARM support!](https://charmhub.io/pgbouncer/docs/r-requirements?channel=1/stable) [[#196](https://github.com/canonical/pgbouncer-operator/pull/196)]
* Exposure of all endpoints via data-integrator [[#137](https://github.com/canonical/pgbouncer-operator/pull/137)][[DPE-3451](https://warthogs.atlassian.net/browse/DPE-3451)]
* Add TLS support [[#137](https://github.com/canonical/pgbouncer-operator/pull/137)][[DPE-3452](https://warthogs.atlassian.net/browse/DPE-3452)]
* All the functionality from [previous revisions](https://charmhub.io/pgbouncer/docs/r-releases)

## Bugfixes

* [[DPE-4221](https://warthogs.atlassian.net/browse/DPE-4221)] Recreate auth_query on backend rerelation in [#224](https://github.com/canonical/pgbouncer-operator/pull/224)
* [[DPE-4202](https://warthogs.atlassian.net/browse/DPE-4202)] data_platform_libs update in [#207](https://github.com/canonical/pgbouncer-operator/pull/207)
* [[DPE-3658](https://warthogs.atlassian.net/browse/DPE-3658)] Add subordinate charms test in [#195](https://github.com/canonical/pgbouncer-operator/pull/195)
* [[DPE-3050](https://warthogs.atlassian.net/browse/DPE-3050)] Template config in [#159](https://github.com/canonical/pgbouncer-operator/pull/159)
* [[DPE-3602](https://warthogs.atlassian.net/browse/DPE-3602)] Fixed charm restart in [#155](https://github.com/canonical/pgbouncer-operator/pull/155)
* [[DPE-3535](https://warthogs.atlassian.net/browse/DPE-3535)] Rerender config from secrets during upgrade in [#150](https://github.com/canonical/pgbouncer-operator/pull/150)
* [[DPE-3184](https://warthogs.atlassian.net/browse/DPE-3184)] Update secrets implementation in [#145](https://github.com/canonical/pgbouncer-operator/pull/145)
* [MISC] Fix secret keys in [#148](https://github.com/canonical/pgbouncer-operator/pull/148)
* [MISC] Update Charmed PostgreSQL SNAP in [#222](https://github.com/canonical/pgbouncer-operator/pull/222)

Canonical Data issues are now public on both [Jira](https://warthogs.atlassian.net/jira/software/c/projects/DPE/issues/) and [GitHub](https://github.com/canonical/pgbouncer-operator/issues) platforms.  
[GitHub Releases](https://github.com/canonical/pgbouncer-operator/releases) provide a detailed list of bugfixes, PRs, and commits for each revision.  

## Inside the charms

* Charmed PgBouncer ships the latest PgBouncer `1.21.0-0ubuntu0.22.04.1~ppa1`
* The Prometheus pgbouncer-exporter is “0.7.0-0ubuntu0.22.04.1~ppa1”
* VM charms based on [Charmed PostgreSQL](https://snapcraft.io/charmed-postgresql) SNAP (Ubuntu LTS `22.04.4`)  revision 113
* Subordinate charms support LTS `22.04` and `20.04` only  

## Technical notes

* Upgrade via `juju refresh` is possible from revision 81+.
* Please check [the external components requirements](https://charmhub.io/pgbouncer/docs/r-requirements?channel=1/stable)
* Note: [juju 3.1.6 doesn’t report](https://bugs.launchpad.net/juju/+bug/2037279) when `pre-upgrade-check` action fails. Therefore, it is recommended to redeploy pgbouncer charm on Juju 3.1.7+
* Use this operator together with the [Charmed PostgreSQL](https://charmhub.io/postgresql) operator  

## Contact us

Charmed PgBouncer is an open source project that warmly welcomes community contributions, suggestions, fixes, and constructive feedback.  
* Raise software issues or feature requests on [**GitHub**](https://github.com/canonical/pgbouncer-operator/issues)  
*  Report security issues through [**Launchpad**](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File)  
* Contact the Canonical Data Platform team through our [Matrix](https://matrix.to/#/#charmhub-data-platform:ubuntu.com) channel.