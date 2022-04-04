# PgBouncer Operator

## Description

The PgBouncer Operator deploys and operates the [PgBouncer](https://www.pgbouncer.org) lightweight connection pooler for PostgreSQL.

## Usage

As this charm is not yet published, you need to follow the build and deploy instructions from [CONTRIBUTING.md](https://github.com/canonical/pgbouncer-operator/CONTRIBUTING.md).

### Config Options

Set these using the command `juju config <option>=<value>`>

- pool_mode:
  - default: session
  - description: |
    - Specifies when a server connection can be reused by other clients.
    - Can be one of the following values:

      - session
        - Server is released back to pool after client disconnects. Default.

      - transaction
        - Server is released back to pool after transaction finishes.

      - statement
        - Server is released back to pool after query finishes. Transactions spanning multiple statements are disallowed in this mode.

- max_db_connections:
  - default: 0
  - Do not allow more than this many server connections per database (regardless of user). This considers the PgBouncer database that the client has connected to, not the PostgreSQL database of the outgoing connection.
  - Note that when you hit the limit, closing a client connection to one pool will not immediately allow a server connection to be established for another pool, because the server connection for the first pool is still open. Once the server connection closes (due to idle timeout), a new server connection will immediately be opened for the waiting pool.
  - 0 = unlimited

## Relations

#### Planned
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