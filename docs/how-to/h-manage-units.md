# How manage units

To deploy a single unit of PgBouncer using its default configuration:
```shell
juju deploy pgbouncer --channel 1/stable
```

## Scale units

PgBouncer is a subordinated charm, both scaling-up and scaling-down operations are performed via the principal charm using `juju add-unit`:

```shell
juju add-unit <principal_charm> -n <desired_num_of_units>
```

The subordinated charm will be scaled automatically, following the principal charm.