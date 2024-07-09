# How to deploy and manage units

## Basic Usage

To deploy a single unit of PgBouncer using its default configuration:
```shell
juju deploy pgbouncer --channel 1/stable
```

## Scaling

PgBouncer is a subordinated charm, both scaling-up and scaling-down operations are performed via principal application using `juju add-unit`:
```shell
juju add-unit application -n <desired_num_of_units>
```

The subordinated application will be scaled automatically, following the principal application.