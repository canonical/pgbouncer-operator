 # Tutorial

This section of our documentation contains a hands-on tutorial to help you learn how to deploy Charmed PgBouncer together with PostgreSQL on machines and become familiar with some of its operations.

## Prerequisites

While this tutorial intends to guide you as you deploy Charmed PgBouncer for the first time, it will be most beneficial if:
- You have some experience using a Linux-based CLI
- You are familiar with PgBouncer concepts such as load balancing and connection pooling.
- Your computer fulfils the [minimum system requirements](/t/12307)

## Tutorial contents
This Charmed PgBouncer tutorial has the following parts:

| Step | Details |
| ------- | ---------- |
| 1. [**Set up the environment**](/t/12289) | Set up a cloud environment for your deployment using [Multipass](https://multipass.run/) with [LXD](https://ubuntu.com/lxd) and [Juju](https://juju.is/).
| 2. [**Deploy PgBouncer**](/t/12290) | Learn to deploy Charmed PgBouncer with Juju
| 3. [**Manage your units**](/t/12291) | Learn how to scale PgBouncer units
| 4. [**Enable security with TLS**](/t/12292) |  Learn how to enable TLS encryption in PgBouncer traffic
| 5. [**Clean up the environment**](/t/12293) | Free up your machine's resources