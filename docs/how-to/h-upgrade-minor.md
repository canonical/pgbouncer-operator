# Minor Upgrade

We strongly recommend to **NOT** perform any other extraordinary operations on Charmed PostgreSQL cluster and/or PgBouncer, while upgrading. As an examples, these may be (but not limited to) the following:

1. Adding or removing units
2. Creating or destroying new relations
3. Changes in workload configuration
4. Upgrading other connected/related/integrated applications simultaneously

The concurrency with other operations is not supported, and it can lead the cluster into inconsistent states.

> **:warning: NOTE:** Make sure to have a [Charmed PostgreSQL backups](/t/9683) of your data when running any type of upgrades.

> **:warning: TIP:** The "PgBouncer" upgrade should follow first, before "Charmed PostgreSQL" upgrade!!!

## Minor upgrade steps

1. **Collect** all necessary pre-upgrade information. It will be necessary for the rollback (if requested). Do NOT skip this step, it is better safe the sorry!
2. (optional) **Scale-up**. The new `sacrificial` unit will be the first one to be updated, and it will simplify the rollback procedure a lot in case of the upgrade failure.
3. **Prepare** "Charmed PostgreSQL K8s" Juju application for the in-place upgrade. See the step description below for all technical details executed by charm here.
4. **Upgrade** (phase 1). Once started, only one unit in a cluster will be upgraded. In case of failure, the rollback is simple: remove newly added pod (in step 2).
5. **Resume** upgrade (phase 2). If the new pod is OK after the refresh, the upgrade can be resumed for all other units in the cluster. All units in a cluster will be executed sequentially: from biggest ordinal to the lowest one. Resume is available for Server charm only, the PgBouncer charm upgrades all units at once if no issues found for previous steps.
6. (optional) Consider to [**Rollback**](/t/12316) in case of disaster. Please inform and include us in your case scenario troubleshooting to trace the source of the issue and prevent it in the future. [Contact us](/t/12305)!
7. (optional) **Scale-back**. Remove no longer necessary sacrificial unit created in step 2 (if any).
8. Post-upgrade **Check**. Make sure all units are in the proper state and the cluster is healthy.

## Step 1: Collect

> **:information_source: NOTE:** The step is only valid when deploying from charmhub. If the [local charm](https://juju.is/docs/sdk/deploy-a-charm) deployed (revision is small, e.g. 0-10), make sure the proper/current local revision of the `.charm` file is available BEFORE going further. You might need it for rollback.

The first step is to record the revision of the running application, as a safety measure for a rollback action. You can find the revisions of the deployed Charmed PostgreSQL and PgBouncer applications with `juju status`.  Store them safely to use in case of rollback!
<!--
```shell
TODO
```

For this example, the current revision is `XX` for PostgreSQL and `TT` for PgBouncer.
-->
## Step 2: Scale-up (optional)

Optionally, it is recommended to scale the application up by one unit before starting the upgrade process.

The new unit will be the first one to be updated, and it will assert that the upgrade is possible. In case of failure, having the extra unit will ease the rollback procedure, without disrupting service. More on the [Minor rollback](/t/12316) tutorial.

```shell
juju add-unit postgresql -n 1
juju add-unit pgbouncer -n 1
```

Wait for the new unit up and ready.

## Step 3: Prepare

After the application has settled, it’s necessary to run the `pre-upgrade-check` action against the leader unit:

```shell
juju run postgresql/leader pre-upgrade-check
juju run pgbouncer/leader pre-upgrade-check
```

The action will configure the charms to minimize the amount of primary switchover, among other preparations for the upgrade process. After successful execution, charms are ready to be upgraded.

## Step 4: Upgrade

Use the [`juju refresh`](https://juju.is/docs/juju/juju-refresh) command to trigger the charm upgrade process. If using juju version 3 or higher, it is necessary to add the `--trust` option.

```shell
juju refresh pgbouncer --channel 1/edge

# example with specific revision selection
juju refresh pgbouncer --revision=89
```

After the PgBouncer upgrade is completed, upgrade PostgreSQL:
```shell
juju refresh postgresql --channel 8.0/edge

juju refresh postgresql --revision=89
```
[note type="caution"]
Important notes:
* The PostgreSQL upgrade will execute only on the **highest ordinal unit**. 
* It is expected to have some status changes during the process: `waiting`, `maintenance`, `active`. **Do not trigger `rollback` procedure during the running `upgrade` procedure.** Make sure `upgrade` has failed or stopped and cannot be fixed/continued before triggering a rollback!
* The unit should recover shortly after, but the time can vary depending on the amount of data written to the cluster while the unit was not part of the cluster. **Large installations might take some extra time to recover.**
[/note]

## Step 5: Resume

After the unit is upgraded, the charm will set the unit upgrade state as completed. If deemed necessary the user can further assert the success of the upgrade. Being the unit healthy within the cluster, the next step is to resume the upgrade process, by running:

```shell
juju run pgbouncer/leader resume-upgrade
juju run postgresql/leader resume-upgrade
```

The `resume-upgrade` will rollout the Server upgrade for the following unit, always from highest from lowest, and for each successful upgraded unit, the process will rollout the next automatically.

<!--
```shell
TODO
```
-->

## Step 6: Rollback (optional)

The step must be skipped if the upgrade went well! 

Although the underlying PostgreSQL Cluster and PgBouncer continue to work, it’s important to rollback the charm to previous revision so an update can be later attempted after a further inspection of the failure. Please switch to the dedicated [minor rollback](/t/12316) tutorial if necessary.

## Step 7: Scale-back

Case the application scale was changed for the upgrade procedure, it is now safe to scale it back to the desired unit count:

```shell
juju remove-unit pgbouncer/<biggest_ordinal>
juju remove-unit postgresql/<biggest_ordinal>
```

## Step 8: Check

Future [improvements are planned](https://warthogs.atlassian.net/browse/DPE-2620) to check the state on pod/cluster on a low level. At the moment check `juju status` to make sure the cluster [state](/t/12303) is OK.