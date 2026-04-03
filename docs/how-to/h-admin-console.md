# How to access the PgBouncer admin console

This guide demonstrates how to access the [PgBouncer admin console](https://www.pgbouncer.org/usage.html#admin-console) when integrated with PostgreSQL and the data-integrator charm.

## Reveal the admin user credentials

Find the Juju secret ID:

```
$ SECRET_ID=$(juju secrets --format=json | jq -r 'to_entries[] | select(.value.label == "pgb-peers.pgbouncer.app") | .key')
```

Reveal the password:

```
$ juju show-secret --reveal $SECRET_ID --format=json | jq -r '.[].content.Data["admin-password"]'
```

## Connect to the internal PgBouncer database

Connect using `psql` with the following URI format:

```
psql postgresql://pgbouncer_admin_<app_name>:<password>@<unit_ip>:<port>/pgbouncer
``` 

Note that The PgBouncer database will always be called `pgbouncer` and the admin username will follow the pattern of `pgbouncer_admin_{pgbouncer app name}`

Example:
```
$ juju status
Model          Controller           Cloud/Region         Version  SLA          Timestamp
admin-console  localhost-localhost  localhost/localhost  3.6.14   unsupported  14:41:41+02:00

App              Version  Status  Scale  Charm            Channel       Rev  Exposed  Message
data-integrator           active      1  data-integrator  latest/edge   368  no       
pgbouncer                 active      1  pgbouncer        1/edge        900  no       
postgresql       16.11    active      1  postgresql       16/edge      1031  no       

Unit                Workload  Agent  Machine  Public address  Ports     Message
data-integrator/0*  active    idle   1        10.7.41.82                
  pgbouncer/0*      active    idle            10.7.41.82      6432/tcp  
postgresql/0*       active    idle   0        10.7.41.101     5432/tcp  Primary
```
```
$ psql postgresql://pgbouncer_admin_pgbouncer:XHDgj1d3ZRn9egRWoCS9QH7N@10.7.41.82:6432/pgbouncer
psql (18.2, server 1.21.0/bouncer)
WARNING: psql major version 18, server major version 1.21.
         Some psql features might not work.
Type "help" for help.

pgbouncer=# show stats;
 database  | total_xact_count | total_query_count | total_received | total_sent | total_xact_time | total_
query_time | total_wait_time | avg_xact_count | avg_query_count | avg_recv | avg_sent | avg_xact_time | av
g_query_time | avg_wait_time 
-----------+------------------+-------------------+----------------+------------+-----------------+-------
-----------+-----------------+----------------+-----------------+----------+----------+---------------+---
-------------+---------------
 pgbouncer |                3 |                 3 |              0 |          0 |               0 |       
         0 |               0 |              0 |               0 |        0 |        0 |             0 |   
           0 |             0
 testdb1   |                0 |                 0 |              0 |        419 |               0 |       
         0 |           64884 |              0 |               0 |        0 |        0 |             0 |   
           0 |             0
(2 rows)
```