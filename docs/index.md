# PgBouncer Documentation

The PgBouncer Operator delivers automated operations management from day 0 to day 2 on the [PgBouncer](http://www.pgbouncer.org/) - the  lightweight connection pooler for PostgreSQL. It is an open source, end-to-end, production-ready data platform on top of [Juju](https://juju.is/).

![image|690x423](upload://fqMd5JlHeegw0PlUjhWKRu858Nc.png)

PostgreSQL is a powerful, open source object-relational database system that uses and extends the SQL language combined with many features that safely store and scale the most complicated data workloads. Consider to use [Charmed PostgreSQL](https://charmhub.io/postgresql).

The PgBouncer operator comes in two flavours to deploy and operate PostgreSQL on [physical/virtual machines](https://github.com/canonical/pgbouncer-operator) and [Kubernetes](https://github.com/canonical/pgbouncer-operator). Both offer identical features and simplifies deployment, scaling, configuration and management of PgBouncer in production at scale in a reliable way.

## Project and community

This PgBouncer charm is an official distribution of PgBouncer. It’s an open-source project that welcomes community contributions, suggestions, fixes and constructive feedback.
- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/pgbouncer)
- [Contribute](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md) and report [issues](https://github.com/canonical/pgbouncer-operator/issues/new/choose)
- Explore [Canonical Data Fabric solutions](https://canonical.com/data)
-  [Contacts us]() for all further questions

## In this documentation

| | |
|--|--|
|  [Tutorials]()</br>  Get started - a hands-on introduction to using PgBouncer operator for new users </br> |  [How-to guides]() </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/pgbouncer/actions) </br> Technical information - specifications, APIs, architecture | [Explanation]() </br> Concepts - discussion and clarification of key topics  |

# Contents

1. [Tutorial](tutorial)
  1. [1. Introduction](tutorial/t-overview.md)
  1. [2. Set up the environment](tutorial/t-setup-environment.md)
  1. [3. Deploy PgBouncer](tutorial/t-deploy-charm.md)
  1. [4. Manage units](tutorial/t-managing-units.md)
  1. [5. Enable security](tutorial/t-enable-security.md)
  1. [6. Cleanup environment](tutorial/t-cleanup-environment.md)
1. [How To](how-to)
  1. [Setup](how-to/h-setup)
    1. [Deploy on LXD](how-to/h-setup/h-deploy-lxd.md)
    1. [Manage units](how-to/h-setup/h-manage-units.md)
    1. [Enable encryption](how-to/h-setup/h-enable-encryption.md)
    1. [Manage applications](how-to/h-setup/h-manage-app.md)
  1. [Upgrade](how-to/h-upgrade)
    1. [Intro](how-to/h-upgrade/h-upgrade-intro.md)
    1. [Major upgrade](how-to/h-upgrade/h-upgrade-major.md)
    1. [Major rollback](how-to/h-upgrade/h-rollback-major.md)
    1. [Minor upgrade](how-to/h-upgrade/h-upgrade-minor.md)
    1. [Minor rollback](how-to/h-upgrade/h-rollback-minor.md)
  1. [Monitor (COS)](how-to/h-enable-monitoring.md)
1. [Reference](reference)
  1. [Release Notes](reference/r-releases-group)
    1. [All releases](reference/r-releases-group/r-releases.md)
    1. [Revision 173-176](reference/r-releases-group/r-releases-rev173.md)
    1. [Revision 89](reference/r-releases-group/r-releases-rev89.md)
    1. [Revision 81](reference/r-releases-group/r-releases-rev81.md)
    1. [Revision 77](reference/r-releases-group/r-releases-rev77.md)
  1. [Requirements](reference/r-requirements.md)
  1. [Contributing](https://github.com/canonical/pgbouncer-operator/blob/main/CONTRIBUTING.md)
  1. [Testing](reference/r-testing.md)
  1. [Contacts](reference/r-contacts.md)
1. [Explanation](explanation)
  1. [Interfaces/endpoints](explanation/e-interfaces.md)
  1. [Statuses](explanation/e-statuses.md)
  1. [Juju](explanation/e-juju-details.md)
  1. [Legacy charm](explanation/e-legacy-charm.md)