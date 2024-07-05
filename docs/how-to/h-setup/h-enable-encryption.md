# How to enable encryption

PgBouncer is a [subordinate charm](https://juju.is/docs/sdk/charm-taxonomy#heading--subordinate-charms). When integrated to a host application (principal charm), it serves on localhost, so TLS encryption is not necessary.

If you are using `data-integrator`, PgBouncer will open a port to listen to TCP traffic. In this case, because PgBouncer is exposed, **TLS encryption is recommended.**



## Enable TLS

First, deploy the TLS charm:
```shell
juju deploy self-signed-certificates --config ca-common-name="Tutorial CA"
```

To enable TLS, integrate the two applications:
```shell
juju integrate self-signed-certificates pgbouncer
```

[note]
To enable TLS on PostgreSQL, refer to [ Charmed PostgreSQL | How to enable security](https://charmhub.io/postgresql/docs/t-enable-security).
[/note]