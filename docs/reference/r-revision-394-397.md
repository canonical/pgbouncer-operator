>Reference > Release Notes > [All revisions] > Revision 394/395/396/397

# Revision 394/395/396/397
September 11, 2024

Dear community,

Canonical's newest Charmed PgBouncer operator has been published in the [1/stable channel].

Due to the newly added support for `arm64` architecture, the PgBouncer charm now releases multiple revisions simultaneously:
* Revision 396 is built for `amd64` on Ubuntu 22.04 LTS
* Revision 395 is built for `amd64` on Ubuntu 20.04 LTS
* Revision 397 is built for `arm64` on Ubuntu 22.04 LTS
* Revision 394 is built for `arm64` on Ubuntu 20.04 LTS 

To make sure you deploy for the right architecture, we recommend setting an [architecture constraint](https://juju.is/docs/juju/constraint#heading--arch) for your entire juju model.

Otherwise, it can be done at deploy time with the `--constraints` flag:
```shell
juju deploy pgbouncer --constraints arch=<arch> 
```
where `<arch>` can be `amd64` or `arm64`.

---

## Highlights 
* [Added HA cluster interface](https://charmhub.io/pgbouncer/integrations?channel=1/candidate#ha) ([PR #317](https://github.com/canonical/pgbouncer-operator/pull/317)) ([DPE-4066](https://warthogs.atlassian.net/browse/DPE-4066))
* Added URI to relation data (improves UX) ([PR #324](https://github.com/canonical/pgbouncer-operator/pull/324)) ([DPE-4683](https://warthogs.atlassian.net/browse/DPE-4683))
* Add Unix socket access for principal charm (including strict SNAPs) ([PR #337](https://github.com/canonical/pgbouncer-operator/pull/337)) ([DPE-4683](https://warthogs.atlassian.net/browse/DPE-4683))

## Bugfixes

* Use poetry package-mode=false ([PR #308](https://github.com/canonical/pgbouncer-operator/pull/308))
* Switched test app interface ([PR #310](https://github.com/canonical/pgbouncer-operator/pull/310))
* Bumped data_interface and tempo libs ([PR #318](https://github.com/canonical/pgbouncer-operator/pull/318))
* Removed no longer necessary locales dependency ([PR #328](https://github.com/canonical/pgbouncer-operator/pull/328))
* Moved scheduled tests ([PR #297](https://github.com/canonical/pgbouncer-operator/pull/297))
 * Shortened integration test job name ([PR #292](https://github.com/canonical/pgbouncer-operator/pull/292))

## Dependencies and automations
* Switched Jira issue sync from workflow to bot ([PR #327](https://github.com/canonical/pgbouncer-operator/pull/327))
* Updated canonical/charming-actions action to v2.6.2 ([PR #286](https://github.com/canonical/pgbouncer-operator/pull/286))
* Updated data-platform-workflows to v21.0.1 ([PR #348](https://github.com/canonical/pgbouncer-operator/pull/348))
* Updated dependency cryptography to v43 ([PR #295](https://github.com/canonical/pgbouncer-operator/pull/295))
* Updated dependency juju/juju to v2.9.50 ([PR #303](https://github.com/canonical/pgbouncer-operator/pull/303))
* Updated dependency juju/juju to v3.4.5 ([PR #306](https://github.com/canonical/pgbouncer-operator/pull/306))
* Updated dependency tenacity to v9 ([PR #311](https://github.com/canonical/pgbouncer-operator/pull/311))
* Updated charm libs ([PR #304](https://github.com/canonical/pgbouncer-operator/pull/304))

## Technical details
This section contains some technical details about the charm's contents and dependencies. 

If you are jumping over several stable revisions, check [previous release notes][All revisions] before upgrading.

### Requirements
See the [system requirements] page for more details about software and hardware prerequisites.

### Packaging


This charm is based on the CharmedPgBouncer [snap Revision 15/16] . It packages:
* [pgbouncer `v.1.21`]
* [prometheus-pgbouncer-exporter `v.0.7.0`]


### Libraries and interfaces
This charm revision imports the following libraries:

* **grafana_agent `v0`** for integration with Grafana 
    * Implements  `cos_agent` interface
* **rolling_ops `v0`** for rolling operations across units 
    * Implements `rolling_op` interface
* **tempo_k8s `v1`, `v2`** for integration with Tempo charm
    * Implements `tracing` interface
* **tls_certificates_interface `v2`** for integration with TLS charms
    * Implements `tls-certificates` interface

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

[snap Revision 15/16]: https://github.com/canonical/charmed-pgbouncer-snap/releases/tag/rev16
[rock image]: https://github.com/orgs/canonical/packages?repo_name=charmed-pgbouncer-rock

[pgbouncer `v.1.21`]: https://launchpad.net/~data-platform/+archive/ubuntu/pgbouncer
[prometheus-pgbouncer-exporter `v.0.7.0`]: https://launchpad.net/~data-platform/+archive/ubuntu/pgbouncer-exporter