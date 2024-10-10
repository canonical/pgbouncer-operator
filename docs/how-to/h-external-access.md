# Optimal PgBouncer Setup

For optimal performance, it is recommended that [PgBouncer](https://www.pgbouncer.org/) is run alongside your application. Co-locating PgBouncer with your application results in increased network performance since an additional network hop from your application to PgBouncer is avoided. Furthermore, it can also lead increased security since traffic is not routed externally through potentially untrusted machines. 

When your application implements the modern (preferred) interface in  [PgBouncer's supported interfaces](https://discourse.charmhub.io/t/pgbouncer-how-to-manage-app/12311) , the PgBouncer charm is deployed as a subordinate of your application charm and your application.

## Accessing PgBouncer outside of Juju

A known limitation of relating with PgBouncer (a subordinate charm) is that your application would need to be deployed as a Juju application. However, if your application exists outside of the Juju ecosystem, you can access PgBouncer externally with the [Data Integrator](https://charmhub.io/data-integrator) charm.

### Example setup
The steps below show you how to deploy and set up PostgreSQL, PgBouncer, and Data Integrator for access outside of Juju.

First, deploy all the charms:
```shell
juju deploy pgbouncer --channel 14/edge --trust
juju deploy data-integrator --config database-name=test_database
juju deploy pgbouncer --channel 1/edge
```
> Feel free to change `test_database` to your name of choice

Integrate:
* `postgresql` with `pgbouncer`
* `data-integrator` with `pgbouncer`, since in this case we want to generate the credentials to access PgBouncer

```shell
juju integrate postgresql pgbouncer
juju integrate data-integrator pgbouncer
```

The following is a sample output of the `get-credentials` action run on a `data-integrator` unit:
```shell
juju run data-integrator/leader get-credentials
```

```shell
ok: "True"
postgresql:
  data: '{"database": "test_database", "external-node-connectivity": "true", "requested-secrets":
    "[\"username\", \"password\", \"tls\", \"tls-ca\", \"uris\"]"}'
  database: test_database
  endpoints: 10.205.193.65:6432
  password: mysupersecuredatabasepassword
  subordinated: "true"
  uris: postgresql://relation_id_7:mysupersecuredatabasepassword@10.205.193.65:6432/test_database
  username: relation_id_7
  version: "14.13"
```

You can then connect to PgBouncer with the provided `uris` from your application that resides outside of Juju.

## Using a Virtual IP to connect to PgBouncer

If the PgBouncer charm is related to the Data Integrator charm, it is possible for a user to configure PgBouncer to use a certain Virtual IP. This assumes that the user has somehow ensured that the Virtual IP resolves to the node on which the PgBouncer charm is deployed.

To configure the PgBouncer charm with a virtual IP, run
```shell
juju config pgbouncer/0 vip=<your_virtual_ip>
```

### Integrate with HACluster

Alternatively, you can integrate with the [HACluster charm](https://charmhub.io/hacluster) if you would like a Virtual IP that is generated and maintained for you.

HACluster is a collection of solutions by [ClusterLabs](https://clusterlabs.org/) designed to create and manage resources. The creation of resources like Virtual IPs is handled by [Pacemaker](https://clusterlabs.org/pacemaker/), whereas the management of these resources is handled by [Corosync](https://clusterlabs.org/corosync.html). 

Pacemaker will create and attach a Virtual IP to one of your Data Integrator nodes (that is related to PgBouncer), while Corosync will ensure automatic failover if the node with the Virtual IP faces connectivity or other issues. **This setup requires at least 3 Data Integrator nodes, each related to both PgBouncer and HACluster.**

[note type="warning"]
**Warning**: The Virtual IP supplied to PgBouncer should be in the same subnet as the nodes on which the PgBouncer charm is running. Else, you may encounter unexpected behavior from the HACluster charm when it tries to create the Virtual IP.
[/note]

#### Example setup
The steps below show you how to deploy and set up PostgreSQL, PgBouncer, Data Integrator, and HACluster.

First, deploy all the charms
```shell
juju deploy postgresql --channel 14/edge --trust
juju deploy -n 3 data-integrator --config database-name=test_database
juju deploy pgbouncer --channel dpe/edge
juju deploy hacluster
```
> Note that the `data-integrator` requires a minimum of 3 nodes for this HACluster setup to work

Configure the VIP on `pgbouncer`. Please ensure that the VIP is in an accessible subnet:
```shell
juju config pgbouncer vip=10.205.193.35
```

Then, integrate:
* `pgbouncer` with `postgresql`
* `pgbouncer` and `hacluster` with `data-integrator`
* `pgbouncer` with `hacluster`

```
juju integrate pgbouncer postgresql

juju integrate data-integrator pgbouncer
juju integrate data-integrator:juju-info hacluster:juju-info

juju integrate pgbouncer hacluster
```

The following is a sample output of the `get-credentials` action run on a `data-integrator` unit:
```shell
juju run data-integrator/leader get-credentials
```
```shell
Running operation 3 with 1 task
  - task 4 on unit-data-integrator-0

Waiting for task 4...
ok: "True"
postgresql:
  data: '{"database": "test_database", "external-node-connectivity": "true", "requested-secrets":
    "[\"username\", \"password\", \"tls\", \"tls-ca\", \"uris\"]"}'
  database: test_database
  endpoints: 10.205.193.35:6432
  password: mysupersecuredatabasepassword
  read-only-endpoints: 10.205.193.80:6432,10.205.193.98:6432
  subordinated: "true"
  uris: postgresql://relation_id_7:mysupersecuredatabasepassword@10.205.193.35:6432/test_database
  username: relation_id_7
  version: "14.13"
```