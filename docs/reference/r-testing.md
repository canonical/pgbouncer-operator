# Charm Testing reference

There are [a lot of test types](https://en.wikipedia.org/wiki/Software_testing) available and most of them are well applicable for PgBouncer. Here is a list prepared by Canonical:

* Smoke test
* Unit tests
* Integration tests
* System test
* Performance test

**:information_source: Note:** below examples are written for Juju 3.x, but Juju 2.9 is [supported](/t/12263) as well.<br/>Please adopt the `juju run ...` commands as `juju run-action ... --wait` for Juju 2.9.

## Smoke test

[u]Complexity[/u]: trivial<br/>
[u]Speed[/u]: fast<br/>
[u]Goal[/u]: ensure basic functionality works over short amount of time.

[Setup an Juju 3.x environment](/t/12252), deploy DB with test application and start "continuous write" test:
```shell
juju add-model smoke-test

juju deploy postgresql --channel 14/stable --config profile=testing
juju deploy pgbouncer --channel 1/stable
juju relate postgresql pgbouncer

juju add-unit postgresql -n 2 # (optional)

juju deploy postgresql-test-app -n 3 --channel latest/stable
juju relate pgbouncer postgresql-test-app:first-database

# Make sure random data inserted into DB by test application:
juju run postgresql-test-app/leader get-inserted-data

# Start "continuous write" test:
juju run postgresql-test-app/leader start-continuous-writes
export password=$(juju run postgresql/leader get-password username=operator | yq '.. | select(. | has("password")).password')
watch -n1 -x juju ssh postgresql-test-app/leader "charmed-postgresql.psql -h 127.0.0.1 -p 6432 -U operator -W -d postgresql_test_app_first_database \"select count(*) from continuous_writes\""

# Watch the counter is growing!
```
[u]Expected results[/u]:

* postgresql-test-app continuously inserts records in database `postgresql_test_app_first_database` table `continuous_writes`.
* the counters (amount of records in table) are growing on all cluster members

[u]Hints[/u]:
```shell
# Stop "continuous write" test
juju run postgresql-test-app/leader stop-continuous-writes

# Truncate "continuous write" table (delete all records from DB)
juju run postgresql-test-app/leader clear-continuous-writes
```

## Unit tests

Please check the "[Contributing](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md#testing)" guide and follow `tox run -e unit` examples there.

## Integration tests

Please check the "[Contributing](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md#testing)" guide and follow `tox run -e integration` examples there.

## System test

Please check/deploy the charm [postgresql-bundle](https://charmhub.io/pgbouncer-bundle) ([Git](https://github.com/canonical/pgbouncer-bundle)). It deploy and test all the necessary parts at once.

## Performance test

Please use the separate [Charmed PostgreSQL performance testing document](https://charmhub.io/postgresql/docs/r-testing) but deploy Charmed PostgreSQL behind PgBouncer.