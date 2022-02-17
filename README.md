# PgBouncer Operator

## Description

The PgBouncer Operator deploys and operates the [PgBouncer](https://www.pgbouncer.org) lightweight connection pooler for PostgreSQL.

## Usage

As this charm is not yet published, you need to follow the build and deploy instructions from [CONTRIBUTING.md](https://github.com/canonical/pgbouncer-operator/CONTRIBUTING.md).

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