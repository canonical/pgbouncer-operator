# How to manage related applications

## Modern `postgresql_client` interface:

Relations to new applications are supported via the "[postgresql_client](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/postgresql_client/v0/README.md)" interface. To create a relation:

```shell
juju integrate pgbouncer application
```

To remove a relation:

```shell
juju remove-relation pgbouncer application
```

All listed on CharmHub applications are available [here](https://charmhub.io/pgbouncer/integrations), e.g. [postgresql-test-app](https://charmhub.io/postgresql-test-app).

## Legacy `pgsql` interface:

This charm also supports the legacy relation via the `pgsql` interface. Please note that these interface is deprecated.

 ```shell
juju relate pgbouncer:db myapplication
```

Also extended permissions can be requested using `db-admin` endpoint:
```shell
juju relate pgbouncer:db-admin myapplication
```

## Internal operator user

To rotate the internal router passwords, the relation with backend-database should be removed and related again. That process will generate a new user and password for the application, while retaining the requested database and data.

```shell
juju remove-relation postgresql pgbouncer

juju integrate postgresql pgbouncer
```