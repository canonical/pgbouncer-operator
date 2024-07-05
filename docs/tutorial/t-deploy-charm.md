# Get a PgBouncer up and running

This is part of the [PgBouncer Tutorial](/t/12288). Please refer to this page for more information and the overview of the content. The following document will deploy "PgBouncer" together with PostgreSQL server (coming from the separate charm "[Charmed PostgreSQL](https://charmhub.io/postgresql)"). 

## Deploy Charmed PostgreSQL + PgBouncer

To deploy Charmed PostgreSQL + PgBouncer, all you need to do is run the following commands:

```shell
juju deploy pgbouncer --channel 1/stable
juju deploy postgresql # --config profile=testing
```
> :tipping_hand_man: **Tip**: the option `--config profile=testing` will decrease [RAM requirements](https://charmhub.io/postgresql/docs/r-profiles).
 
Juju will now fetch charms from [Charmhub](https://charmhub.io/) and begin deploying it to the LXD VMs. This process can take several minutes depending on how provisioned (RAM, CPU, etc) your machine is. 

You can track the progress by running:
```shell
juju status --watch 1s
```

We recommend keeping a separate shell open running this command. That way, you will always have an easily accessible live update of the statuses for all applications deployed in the current juju model.

Wait until the application is ready - when it is ready, `juju status` will show:
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  lxd         localhost/localhost  3.1.6    unsupported  21:23:37+02:00

App         Version  Status   Scale  Charm       Channel    Rev  Exposed  Message
pgbouncer            unknown      0  pgbouncer   1/stable    76  no       
postgresql  14.9     active       1  postgresql  14/stable  336  no       Primary

Unit           Workload  Agent  Machine  Public address  Ports     Message
postgresql/0*  active    idle   0        10.3.217.79     5432/tcp  Primary

Machine  State    Address      Inst id        Base          AZ  Message
0        started  10.3.217.79  juju-ca0eed-0  ubuntu@22.04      Running
```
> :tipping_hand_man: **Tip**: To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`.
If you want to further inspect juju logs, can watch for logs with `juju debug-log`.
More info on logging at [juju logs](https://juju.is/docs/olm/juju-logs).

At this stage PgBouncer will stay in blocked state due to missing relation/integration with PostgreSQL DB, let's integrate them:
```shell
juju integrate postgresql pgbouncer
```
It will change nothing, as pgbouncer is a subordinated charm and it waits for a client to consume DB service, let's deploy [data-integrator](https://charmhub.io/data-integrator) and request access to database `test123`:
```shell
juju deploy data-integrator --config database-name=test123
juju integrate data-integrator pgbouncer
```
In couple of seconds, the status will be happy for entire model and pgbouncer will be running inside data-integrator:
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  lxd         localhost/localhost  3.1.6    unsupported  21:28:14+02:00

App              Version  Status  Scale  Charm            Channel    Rev  Exposed  Message
data-integrator           active      1  data-integrator  stable      13  no       
pgbouncer        1.18.0   active      1  pgbouncer        1/stable    76  no       
postgresql       14.9     active      1  postgresql       14/stable  336  no       Primary

Unit                Workload  Agent  Machine  Public address  Ports     Message
data-integrator/0*  active    idle   1        10.3.217.167              
  pgbouncer/0*      active    idle            10.3.217.167              
postgresql/0*       active    idle   0        10.3.217.79     5432/tcp  Primary

Machine  State    Address       Inst id        Base          AZ  Message
0        started  10.3.217.79   juju-ca0eed-0  ubuntu@22.04      Running
1        started  10.3.217.167  juju-ca0eed-1  ubuntu@22.04      Running
```

## Access database

The first action most users take after installing PostgreSQL is accessing it. The easiest way to do this is via the [PostgreSQL Command-Line Client](https://www.postgresql.org/docs/14/app-psql.html) `psql`. Connecting to the database requires that you know the values for `host`, `username` and `password`. To retrieve the necessary fields please run data-integrator action `get-credentials`:
```shell
juju run data-integrator/leader get-credentials
```
Running the command should output:
```yaml
postgresql:
  database: test123
  endpoints: localhost:6432
  password: 3tjXolB7VNKob2VnvMPXa6Y3
  username: relation_id_7
  version: "14.9"
```

To access the PostgreSQL database via PgBouncer go inside data-integrator charm and use the port 6432 on localhost:
```shell
juju ssh data-integrator/0 bash

charmed-postgresql.psql -h 127.0.0.1 -p 6432 -U relation_id_7 -W -d test123 
Password: 3tjXolB7VNKob2VnvMPXa6Y3
psql (14.9 (Ubuntu 14.9-0ubuntu0.22.04.1))
Type "help" for help.

test123=> 
```

Inside MySQL list DBs available on the host `show databases`:
```shell
Password for user relation_id_7:  VYm6tg2KkFOBj8mP3IW9O821
psql (14.9 (Ubuntu 14.9-0ubuntu0.22.04.1))
Type "help" for help.

test123=> \l
                                     List of databases
   Name    |     Owner     | Encoding | Collate |  Ctype  |        Access privileges        
-----------+---------------+----------+---------+---------+---------------------------------
...
 test123   | relation-5 | UTF8     | C.UTF-8 | C.UTF-8 | "relation-5"=CTc/"relation-5" +
           |            |          |         |         | relation_id_7=CTc/"relation-5"+
           |            |          |         |         | admin=CTc/"relation-5"
...
```
> :tipping_hand_man: **Tip**: if at any point you'd like to leave the PostgreSQL client, enter `Ctrl+d` or type `exit`.

You can now interact with PostgreSQL directly using any [SQL Queries](https://www.postgresql.org/docs/14/sql-syntax.html). For example entering `SELECT VERSION(), CURRENT_DATE;` should output something like:
```shell
test123=> SELECT VERSION(), CURRENT_DATE;
                                                               version                                                                | current_date 
--------------------------------------------------------------------------------------------------------------------------------------+--------------
 PostgreSQL 14.9 (Ubuntu 14.9-0ubuntu0.22.04.1) on x86_64-pc-linux-gnu, compiled by gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0, 64-bit | 2023-10-24
(1 row)
```

Feel free to test out any other PostgreSQL queries. When you’re ready to leave the psql shell you can just type `exit`. Now you will be in your original shell where you first started the tutorial; here you can interact with Juju and LXD.

### Remove the user

To remove the user, remove the relation. Removing the relation automatically removes the user that was created when the relation was created. Enter the following to remove the relation:
```shell
juju remove-relation pgbouncer data-integrator
```

Now try again to connect to the same PgBouncer you just used above:
```shell
charmed-postgresql.psql -h 127.0.0.1 -p 6432 -U relation_id_7 -W -d test123 
```

This will output an error message:
```shell
psql: error: connection to server at "127.0.0.1", port 6432 failed: FATAL:  password authentication failed
```
As this user no longer exists. This is expected as `juju remove-relation pgbouncer data-integrator` also removes the user.
Note: data stay remain on the server at this stage!

Relate the the two applications again if you wanted to recreate the user:
```shell
juju relate data-integrator pgbouncer
```
Re-relating generates a new user and password:
```shell
juju run data-integrator/leader get-credentials
```
You can connect to the database with this new credentials.
From here you will see all of your data is still present in the database.