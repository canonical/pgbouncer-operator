# PgBouncer Operator

## Description

The PgBouncer Operator deploys and operates the [PgBouncer](https://www.pgbouncer.org) lightweight connection pooler for PostgreSQL.

## Usage

As this charm is not yet published, you need to follow the build and deploy instructions from [CONTRIBUTING.md](https://github.com/canonical/pgbouncer-operator/CONTRIBUTING.md). This charm creates one pgbouncer application instance per CPU core on each machine it is deployed.

### Config Options

Set these using the command `juju config <option>=<value>`.

- `pool_mode`:
  - default: `session`
  - Specifies when a server connection can be reused by other clients.
  - Can be one of the following values:
    - **session**
      - Server is released back to pool after client disconnects.
    - **transaction**
      - Server is released back to pool after transaction finishes.
    - **statement**
      - Server is released back to pool after query finishes. Transactions spanning multiple statements are disallowed in this mode.

- `max_db_connections`:
  - default: `0`
  - Do not allow more than this many server connections per database (regardless of user). This considers the PgBouncer database that the client has connected to, not the PostgreSQL database of the outgoing connection.
  - Note that when you hit the limit, closing a client connection to one pool will not immediately allow a server connection to be established for another pool, because the server connection for the first pool is still open. Once the server connection closes (due to idle timeout), a new server connection will immediately be opened for the waiting pool.
  - 0 = unlimited

From these values and the current deployment, the following pgbouncer.ini config values are calculated proportional to `max_db_connections`:

- `effective_db_connections = max_db_connections / number of pgbouncer instances running in a unit`
  - Number of pgbouncer instances is equal to number of cpu cores on unit.
- `default_pool_size = effective_db_connections / 2`
  - A larger `default_pool_size` means each new unit will have plenty of spare space when it comes online, allowing the cluster to be more stable when more traffic is needed.
- `min_pool_size = effective_db_connections / 4`
  - Larger `min_pool_size` and `reserve_pool_size` (relative to pgbouncer defaults) means that if a unit goes down for whatever reason, the other units in the cluster should be able to easily handle its workload.
- `reserve_pool_size = effective_db_connections / 4`

NB: These values will be set to zero if `max_db_connections` is zero. This behaviour is untested.

The following config values are set as constants in the charm:

- `max_client_conn = 10000`
- `ignore_startup_parameters = extra_float_digits`
  - `extra_float_digits` is a [parameter in postgres](https://postgresqlco.nf/doc/en/param/extra_float_digits/)

## Relations

### Planned

- `db:[pgsql](https://github.com/canonical/ops-lib-pgsql/)`
- `db-admin:[pgsql](https://github.com/canonical/ops-lib-pgsql/)`
- `backend-db-admin:[pgsql](https://github.com/canonical/ops-lib-pgsql/)`
  - Provides a relaton to the corresponding [postgresql-operator charm](https://github.com/canonical/postgresql-operator).

The following relations provide support for the [LMA charm bundle](https://juju.is/docs/lma2), our expected observability stack.

- `prometheus:prometheus_scrape`
- `loki:loki_push_api`
- `grafana:grafana_dashboards`

## License

The Charmed PgBouncer Operator is free software, distributed under the Apache Software License, version 2.0. See [LICENSE](https://github.com/canonical/pgbouncer-operator/blob/main/LICENSE) for more information.

## Security

Security issues in the Charmed PgBouncer Operator can be reported through [LaunchPad](https://wiki.ubuntu.com/DebuggingSecurity#How%20to%20File). Please do not file GitHub issues about security issues.

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines
on enhancements to this charm following best practice guidelines, and
[CONTRIBUTING.md](https://github.com/canonical/pgbouncer-operator/CONTRIBUTING.md) for developer guidance.
