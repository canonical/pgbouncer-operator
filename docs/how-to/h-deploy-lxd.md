# Deploy PgBouncer

Please follow the [Tutorial](/t/12288) to deploy the charm on LXD.

Short story for your Ubuntu 22.04 LTS:
```shell
sudo snap install multipass
multipass launch --cpus 4 --memory 8G --disk 30G --name my-vm charm-dev # tune CPU/RAM/HDD accordingly to your needs
multipass shell my-vm

juju add-model postgresql
juju deploy postgresql --channel 14/stable
juju deploy pgbouncer --channel 1/stable
juju integrate postgresql pgbouncer
juju status --watch 1s
```

The expected result:
```shell
Model        Controller  Cloud/Region         Version  SLA          Timestamp
welcome-lxd  lxd         localhost/localhost  3.1.6    unsupported  21:12:27+02:00

App         Version  Status   Scale  Charm       Channel    Rev  Exposed  Message
pgbouncer            unknown      0  pgbouncer   1/stable    76  no       
postgresql  14.9     active       1  postgresql  14/stable  336  no       

Unit            Workload  Agent  Machine  Public address  Ports     Message
postgresql/18*  active    idle   25       10.3.217.224    5432/tcp  

Machine  State    Address       Inst id         Base          AZ  Message
25       started  10.3.217.224  juju-d483b7-25  ubuntu@22.04      Running
```

Check the [Testing](/t/12306) reference to test your deployment.