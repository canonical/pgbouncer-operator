# Scale your PgBouncer

This is part of the [PgBouncer Tutorial](/t/12288). Please refer to this page for more information and the overview of the content.

## Adding and Removing units

Please check the explanation of scaling Charmed PostgreSQL operator [here](https://charmhub.io/postgresql/docs/t-managing-units).

### Add more pgbouncer instances

PgBouncer is a subordinated charm, it is enough to keep it as a single instance for each principal charm. To scale the principal charm use `juju add-unit` command (for a tutorial purpose let's scale data-integrator):
```shell
juju add-unit data-integrator -n 2
```

You can now watch the scaling process in live using: `juju status --watch 1s`. It usually takes several minutes for new cluster members to be added. You’ll know that all three nodes are in sync when `juju status` reports `Workload=active` and `Agent=idle`:
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  lxd         localhost/localhost  3.1.6    unsupported  22:26:56+02:00

App              Version  Status  Scale  Charm            Channel    Rev  Exposed  Message
data-integrator           active      3  data-integrator  stable      13  no       
pgbouncer        1.18.0   active      3  pgbouncer        1/stable    76  no       
postgresql       14.9     active      1  postgresql       14/stable  336  no       Primary

Unit                Workload  Agent  Machine  Public address  Ports     Message
data-integrator/1*  active    idle   2        10.3.217.158              
  pgbouncer/1*      active    idle            10.3.217.158              
data-integrator/2   active    idle   3        10.3.217.83               
  pgbouncer/3       active    idle            10.3.217.83               
data-integrator/3   active    idle   4        10.3.217.35               
  pgbouncer/2       active    idle            10.3.217.35               
postgresql/0*       active    idle   0        10.3.217.79     5432/tcp  Primary

Machine  State    Address       Inst id        Base          AZ  Message
0        started  10.3.217.79   juju-ca0eed-0  ubuntu@22.04      Running
2        started  10.3.217.158  juju-ca0eed-2  ubuntu@22.04      Running
3        started  10.3.217.83   juju-ca0eed-3  ubuntu@22.04      Running
4        started  10.3.217.35   juju-ca0eed-4  ubuntu@22.04      Running
```

The same way you can scale Charmed PostgreSQL:
```shell
juju add-unit postgresql -n 2
```
Make sure all units are active (using `juju status`):
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  lxd         localhost/localhost  3.1.6    unsupported  22:55:52+02:00

App              Version  Status  Scale  Charm            Channel    Rev  Exposed  Message
data-integrator           active      3  data-integrator  stable      13  no       
pgbouncer        1.18.0   active      3  pgbouncer        1/stable    76  no       
postgresql       14.9     active      3  postgresql       14/stable  336  no       

Unit                Workload  Agent  Machine  Public address  Ports     Message
data-integrator/1*  active    idle   2        10.3.217.158              
  pgbouncer/1*      active    idle            10.3.217.158              
data-integrator/2   active    idle   3        10.3.217.83               
  pgbouncer/3       active    idle            10.3.217.83               
data-integrator/3   active    idle   4        10.3.217.35               
  pgbouncer/2       active    idle            10.3.217.35               
postgresql/0*       active    idle   0        10.3.217.79     5432/tcp  Primary
postgresql/1        active    idle   5        10.3.217.147    5432/tcp  
postgresql/2        active    idle   6        10.3.217.114    5432/tcp  

Machine  State    Address       Inst id        Base          AZ  Message
0        started  10.3.217.79   juju-ca0eed-0  ubuntu@22.04      Running
2        started  10.3.217.158  juju-ca0eed-2  ubuntu@22.04      Running
3        started  10.3.217.83   juju-ca0eed-3  ubuntu@22.04      Running
4        started  10.3.217.35   juju-ca0eed-4  ubuntu@22.04      Running
5        started  10.3.217.147  juju-ca0eed-5  ubuntu@22.04      Running
6        started  10.3.217.114  juju-ca0eed-6  ubuntu@22.04      Running
```

### Remove extra members
Removing a unit from the application, scales the replicas down.
```shell
juju remove-unit data-integrator/2
juju remove-unit data-integrator/1
juju remove-unit postgresql/1
juju remove-unit postgresql/2
```

You’ll know that the replica was successfully removed when `juju status --watch 1s` reports:
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  lxd         localhost/localhost  3.1.6    unsupported  22:56:23+02:00

App              Version  Status  Scale  Charm            Channel    Rev  Exposed  Message
data-integrator           active      1  data-integrator  stable      13  no       
pgbouncer        1.18.0   active      1  pgbouncer        1/stable    76  no       
postgresql       14.9     active      1  postgresql       14/stable  336  no       

Unit                Workload  Agent  Machine  Public address  Ports     Message
data-integrator/3*  active    idle   4        10.3.217.35               
  pgbouncer/2*      active    idle            10.3.217.35               
postgresql/0*       active    idle   0        10.3.217.79     5432/tcp  

Machine  State    Address      Inst id        Base          AZ  Message
0        started  10.3.217.79  juju-ca0eed-0  ubuntu@22.04      Running
4        started  10.3.217.35  juju-ca0eed-4  ubuntu@22.04      Running
```