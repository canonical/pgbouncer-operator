# Cleanup and extra info

This is part of the [PgBouncer Tutorial](/t/12288). Please refer to this page for more information and the overview of the content.

## Remove and cleanup environment

If you're done with testing and would like to free up resources on your machine, just remove Multipass VM.
*Warning: when you remove VM as shown below you will lose all the data in PostgreSQL and any other applications inside Multipass VM!*
```shell
multipass delete --purge my-vm
```

## Next Steps
In this tutorial we've successfully deployed PgBouncer, added/removed cluster members, added/removed users to/from the database, and even enabled and disabled TLS. You may now keep your deployment running and write to the database or remove it entirely. If you're looking for what to do next you can:
- Run [Charmed PostgreSQL K8s](https://charmhub.io/postgresql-k8s) + [PgBouncer K8s](https://charmhub.io/pgbouncer-k8s) on MicroK8s.
- Check out our Charmed offerings of [MySQL](https://charmhub.io/mysql) and [Kafka](https://charmhub.io/kafka?channel=edge).
- Read about [High Availability Best Practices](https://canonical.com/blog/database-high-availability)
- [Report](https://github.com/canonical/pgbouncer-operator/issues) any problems you encountered.
- [Give us your feedback](https://chat.charmhub.io/charmhub/channels/data-platform).
- [Contribute to the code base](https://github.com/canonical/pgbouncer-operator)