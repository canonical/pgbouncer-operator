# How to enable monitoring

Enable monitoring requires that you:
* [Have a PgBouncer deployed](/t/12290)
* [Deploy `cos-lite` bundle in a Kubernetes environment](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s)
* [COS configured for Charmed PostgreSQL](https://charmhub.io/postgresql/docs/h-enable-monitoring)

Switch to COS K8s environment and offer COS interfaces to be cross-model related with PgBouncer model:
```shell
# Switch to Kubernetes controller, for the cos model.
juju switch <k8s_cos_controller>:<cos_model_name>

juju offer grafana:grafana-dashboard grafana
juju offer loki:logging loki
juju offer prometheus:receive-remote-write prometheus
```

Switch to PgBouncer model, find offers and consume them:
```shell
# We are on the Kubernetes controller, for the cos model. Switch to postgresql model
juju switch <vm_controller>:<postgresql_model_name>

juju find-offers <k8s_cos_controller>:   # Do not miss ':' here!
```

A similar output should appear, if `k8s` is the k8s controller name and `cos` the model where `cos-lite` has been deployed:
```shell
Store  URL                    Access  Interfaces
k8s    admin/cos:grafana      admin   grafana:grafana-dashboard
k8s    admin/cos.loki         admin   loki:logging
k8s    admin/cos.prometheus   admin   prometheus:receive-remote-write
...
```

Consume offers to be reachable in the current model:
```shell
juju consume <k8s_cos_controller>:admin/cos.grafana
juju consume <k8s_cos_controller>:admin/cos.loki
juju consume <k8s_cos_controller>:admin/cos.prometheus
```

Now, deploy '[grafana-agent](https://charmhub.io/grafana-agent)' (as `pgbouncer-cos-agent`) and integrate (relate) it with PgBouncer, later integrate (relate) `pgbouncer-cos-agent` with consumed COS offers:
```shell
juju deploy grafana-agent pgbouncer-cos-agent

juju relate pgbouncer-cos-agent grafana
juju relate pgbouncer-cos-agent loki
juju relate pgbouncer-cos-agent prometheus

juju relate pgbouncer-cos-agent pgbouncer:cos-agent
juju relate pgbouncer-cos-agent data-integrator:juju-info
```

>**Note**: use different grafana-agent deployments (juju applications) for pgbouncer and postgresql charms (due to the subordinate nature of grafana-agent operator).

After this is complete, Grafana will show the new dashboards: `PgBouncer Exporter` and allows access for PgBouncer logs on Loki.

The example of `juju status` for Charmed PostgreSQL + PgBouncer model:
```shell
Model     Controller  Cloud/Region         Version  SLA          Timestamp
tutorial  lxd         localhost/localhost  3.1.8    unsupported  01:24:48+02:00

SAAS        Status  Store  URL
grafana     active  mk8s   admin/cos.grafana
loki        active  mk8s   admin/cos.loki
prometheus  active  mk8s   admin/cos.prometheus

App                  Version  Status  Scale  Charm            Channel        Rev  Exposed  Message
data-integrator               active      1  data-integrator  latest/stable   27  no       
pgbouncer            1.21.0   active      1  pgbouncer        1/stable        88  no       
pgbouncer-cos-agent           active      1  grafana-agent    latest/stable   65  no       
postgresql           14.10    active      1  postgresql       14/stable      363  no       Primary

Unit                      Workload  Agent  Machine  Public address  Ports     Message
data-integrator/0*        active    idle   1        10.184.219.188            
  pgbouncer-cos-agent/0*  active    idle            10.184.219.188            
  pgbouncer/0*            active    idle            10.184.219.188            
postgresql/0*             active    idle   0        10.184.219.86   5432/tcp  Primary

Machine  State    Address         Inst id        Base          AZ  Message
0        started  10.184.219.86   juju-801057-0  ubuntu@22.04      Running
1        started  10.184.219.188  juju-801057-1  ubuntu@22.04      Running
```

The example of `juju status` on COS K8s model:
```shell
Model  Controller  Cloud/Region        Version  SLA          Timestamp
cos    mk8s        microk8s/localhost  3.1.6    unsupported  01:23:57+02:00

App           Version  Status  Scale  Charm             Channel      Rev  Address         Exposed  Message
alertmanager  0.27.0   active      1  alertmanager-k8s  latest/edge  112  10.152.183.130  no       
catalogue              active      1  catalogue-k8s     latest/edge   39  10.152.183.96   no       
grafana       9.5.3    active      1  grafana-k8s       latest/edge  112  10.152.183.208  no       
loki          2.9.5    active      1  loki-k8s          latest/edge  144  10.152.183.153  no       
prometheus    2.50.1   active      1  prometheus-k8s    latest/edge  186  10.152.183.116  no       
traefik       v2.11.0  active      1  traefik-k8s       latest/edge  189  10.76.203.38    no       

Unit             Workload  Agent  Address       Ports  Message
alertmanager/0*  active    idle   10.1.204.230         
catalogue/0*     active    idle   10.1.204.201         
grafana/0*       active    idle   10.1.204.227         
loki/0*          active    idle   10.1.204.239         
prometheus/0*    active    idle   10.1.204.222         
traefik/0*       active    idle   10.1.204.223         

Offer       Application  Charm           Rev  Connected  Endpoint              Interface                Role
grafana     grafana      grafana-k8s     112  1/1        grafana-dashboard     grafana_dashboard        requirer
loki        loki         loki-k8s        144  1/1        logging               loki_push_api            provider
prometheus  prometheus   prometheus-k8s  186  1/1        receive-remote-write  prometheus_remote_write  provider
```

To connect Grafana WEB interface, follow the COS section "[Browse dashboards](https://charmhub.io/topics/canonical-observability-stack/tutorials/install-microk8s)":
```shell
juju run grafana/leader get-admin-password --model <k8s_cos_controller>:<cos_model_name>
```

![image|690x438](upload://4h71nAnPzEiAJDOBdifh43ZUi2Y.png)