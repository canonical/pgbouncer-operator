# Legacy charms
This page contains explanations regarding the legacy version of this charm. This includes clarification about Charmhub tracks, supported endpoints and interfaces, config options, and other important information.

## Summary
* [Charm types: "legacy" vs. "modern"](#heading--charm-types)
* [Default track `latest/` vs. track `1/`](#heading--default-track)
* [How to migrate to the modern charm](#heading--how-to-migrate)
* [How to deploy the legacy charm](#heading--how-to-deploy-legacy)
* [Features supported by the modern charm](#heading--features-supported-by-modern)
  * [Config options](#heading--config-options)
  * [Extensions](#heading--extensions)
  * [Roles](#heading--roles)
  * [PostgreSQL versions](#heading--postgresql-versions)
  * [Architectures](#heading--architectures)
* [Contact us](#heading--contact-us)

--- 

<a href="#heading--charm-types"><h2 id="heading--charm-types"> Charm types: "legacy" vs. "modern" </h2></a>

There are [two types of charms](https://juju.is/docs/sdk/charm-taxonomy#heading--charm-types-by-generation) stored under the same charm name `pgbouncer`:

1. [Reactive](https://juju.is/docs/sdk/charm-taxonomy#heading--reactive)  charm in the channel `latest/stable` (called `legacy`)
2. [Ops-based](https://juju.is/docs/sdk/ops) charm in the channel `1/stable` (called `modern`)

The legacy charm was a [**principal charm**](https://juju.is/docs/sdk/charm-taxonomy#heading--principal-charms), while the modern charm is [**subordinated**](https://juju.is/docs/sdk/charm-taxonomy#heading--subordinate-charms).

The legacy charm provided SQL endpoints `db` and `db-admin` (for the interface `pgsql`). The modern charm provides those old endpoints and a new endpoint `database` (for the interface `postgresql_client`). Read more details about the available endpoints and interfaces [here](https://charmhub.io/pgbouncer/docs/e-interfaces?channel=1/stable).

Non-SQL legacy charm interfaces (e.g. `hacluster`, `pgbouncer-extra-config`, `nrpe-external-master`) are currently NOT supported by the modern charm. [Contact us](/t/12307) with your use cases for those interfaces!

**Note**: Please choose one endpoint to use. No need to relate all of them simultaneously!


<a href="#heading--default-track"><h2 id="heading--default-track"> Default track `latest/` vs. track `1/` </h2></a>

The [default track](https://docs.openstack.org/charm-guide/yoga/project/charm-delivery.html) will be switched from the `latest` to `1` soon. This is to ensure all new deployments use a modern codebase. We strongly advise against using the latest track, since a future charm upgrade may result in a PgBouncer version incompatible with an integrated application. Track `1/` guarantees a PgBouncer major version 1 deployment only. The track `latest/` will be closed after all applications migrated from reactive to the ops-based charm.


<a href="#heading--how-to-migrate"><h2 id="heading--how-to-migrate"> How to migrate to the modern charm </h2></a>

The modern charm provides temporary support for the legacy interfaces:

**Quick try**: relate the current application with new charm using endpoint `db` (set the channel to `1/stable`). No extra changes necessary:

```
  pgbouncer:
    charm: pgbouncer
    channel: 1/stable
```

**Proper migration**: migrate the application to the new interface [`postgresql_client`](https://github.com/canonical/charm-relation-interfaces). The application will connect PgBouncer using the [data_interfaces](https://charmhub.io/data-platform-libs/libraries/data_interfaces) library from [data-platform-libs](https://github.com/canonical/data-platform-libs/) via the endpoint `database`.

**Warning**: In-place upgrades are NOT possible! The reactive charm cannot be upgraded to the operator-framework-based one. The second/modern charm application must be launched nearby and relations should be switched from the legacy application to the modern one.


<a href="#heading--how-to-deploy-legacy"><h2 id="heading--how-to-deploy-legacy"> How to deploy the legacy charm </h2></a>

Deploy the charm using the channel `latest/stable`:

```
  pgbouncer:
    charm: pgbouncer
    channel: latest/stable
```

**Note**: remove Charm store prefix `cs:` from the bundle. Otherwise the modern charm will be chosen by Juju (due to the default track will be pointing to `1/stable` and not `latest/stable`). The common error message is: `cannot deploy application "postgresql": unknown option "..."`.

<a href="#heading--features-supported-by-modern"><h2 id="heading--features-supported-by-modern"> Features supported by the modern charm </h2></a>
This section goes over the key differences in feature support and functionality between the legacy and modern charm.

<a href="#heading--config-options"><h3 id="heading--config-options"> Config options </h3></a>

The legacy charm config options were not moved to the modern charm, since the modern charm applies the best possible configuration automatically. Feel free to [contact us](/t/12305) about the PgBouncer config options.


<a href="#heading--extensions"><h3 id="heading--extensions"> Extensions </h3></a>

The legacy charm provided plugins/extensions through the relation (interface `pgsql`). This is NOT supported by the modern charm  - neither through `pgsql` nor the `postgresql_client` interface. 

To enable extensions on modern PgBouncer, enable them on PostgreSQL charm using the appropriate `plugin_*_enable` [config option](https://charmhub.io/postgresql/configure) of the modern charm. The modern charm will then provide plugins support for both `pgsql` and `postgresql_client` interfaces.


<a href="#heading--roles"><h3 id="heading--roles"> Roles </h3></a>

In the legacy charm, the user could request roles by setting the `roles` field to a comma separated list of desired roles. This is NOT supported by the modern charm implementation of the legacy `pgsql` interface. 

The same functionality is provided via the modern `postgresql_client` using "extra-user-roles".


<a href="#heading--postgresql-versions"><h3 id="heading--postgresql-versions"> PostgreSQL versions </h3></a>

At the moment, the modern PgBouncer charms support relation to the modern Charmed PostgreSQL 14 (based on Jammy/22.04 series) only.
Please [contact us](/t/12305) if you need different versions/series.


<a href="#heading--architectures"><h3 id="heading--architectures"> Architectures </h3></a>

Currently, the charm supports architecture `amd64` and arm64 only. For more technical details, see the [Supported architectures](/t/12307?channel=1/stable) reference.


<a href="#heading--contact-us"><h2 id="heading--contact-us"> Report issues </h2></a>

The "legacy charm" (from `latest/stable`) is stored on [Launchpad](https://git.launchpad.net/pgbouncer-charm/). Report legacy charm issues [here](https://bugs.launchpad.net/pgbouncer-charm).

The "modern charm" (from `1/stable`) is stored on [GitHub](https://github.com/canonical/pgbouncer-operator). Report modern charm issues [here](https://github.com/canonical/pgbouncer-operator/issues/new/choose).

Do you have questions? [Reach out](/t/12307) to us!