# PgBouncer tutorial

The PgBouncer K8s Operator delivers automated operations management from day 0 to day 2 on the [PgBouncer](http://www.pgbouncer.org/) - the lightweight connection pooler for PostgreSQL. It is an open source, end-to-end, production-ready data platform on top of [Juju](https://juju.is/). As a first step this tutorial shows you how to get PgBouncer up and running, but the tutorial does not stop there. Through this tutorial you will learn a variety of operations, everything from adding replicas to advanced operations such as enabling Transport Layer Security (TLS). In this tutorial we will walk through how to:
- Set up an environment using [Multipass](https://multipass.run/) with [LXD](https://ubuntu.com/lxd) and [Juju](https://juju.is/).
- Deploy PgBouncer using a single command.
- Configure TLS certificate in one command.

While this tutorial intends to guide and teach you as you deploy PgBouncer, it will be most beneficial if you already have a familiarity with:
- Basic terminal commands.
- PostgreSQL and PgBouncer concepts.
- [Charmed PostgreSQL operator](https://charmhub.io/postgresql)

## Step-by-step guide

Here’s an overview of the steps required with links to our separate tutorials that deal with each individual step:
* [Set up the environment](/t/12289)
* [Deploy PgBouncer](/t/12290)
* [Managing your units](/t/12291)
* [Enable security](/t/12292)
* [Cleanup your environment](/t/12293)