#!/usr/bin/env -S LD_LIBRARY_PATH=lib python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

import json
import logging
import math
import os
import platform
import pwd
import shutil
import subprocess
from configparser import ConfigParser
from typing import Dict, List, Literal, Optional, Union, get_args

from charms.data_platform_libs.v0.data_interfaces import DataPeer, DataPeerUnit
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v1 import systemd
from charms.operator_libs_linux.v2 import snap
from charms.postgresql_k8s.v0.postgresql_tls import PostgreSQLTLS
from jinja2 import Template
from ops import JujuVersion
from ops.charm import CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    WaitingStatus,
)

from constants import (
    APP_SCOPE,
    AUTH_FILE_DATABAG_KEY,
    AUTH_FILE_NAME,
    CFG_FILE_DATABAG_KEY,
    CLIENT_RELATION_NAME,
    EXTENSIONS_BLOCKING_MESSAGE,
    MONITORING_PASSWORD_KEY,
    PEER_RELATION_NAME,
    PG_USER,
    PGB,
    PGB_CONF_DIR,
    PGB_LOG_DIR,
    PGBOUNCER_EXECUTABLE,
    POSTGRESQL_SNAP_NAME,
    SECRET_DELETED_LABEL,
    SECRET_INTERNAL_LABEL,
    SECRET_KEY_OVERRIDES,
    SNAP_PACKAGES,
    SNAP_TMP_DIR,
    TLS_CA_FILE,
    TLS_CERT_FILE,
    TLS_KEY_FILE,
    UNIT_SCOPE,
)
from relations.backend_database import BackendDatabaseRequires
from relations.db import DbProvides
from relations.peers import Peers
from relations.pgbouncer_provider import PgBouncerProvider
from upgrade import PgbouncerUpgrade, get_pgbouncer_dependencies_model

logger = logging.getLogger(__name__)

Scopes = Literal[APP_SCOPE, UNIT_SCOPE]

INSTANCE_DIR = "instance_"


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    def __init__(self, *args):
        super().__init__(*args)

        self.peer_relation_app = DataPeer(
            self,
            relation_name=PEER_RELATION_NAME,
            additional_secret_fields=[
                self._translate_field_to_secret_key(AUTH_FILE_DATABAG_KEY),
                self._translate_field_to_secret_key(CFG_FILE_DATABAG_KEY),
                self._translate_field_to_secret_key(MONITORING_PASSWORD_KEY),
            ],
            secret_field_name=SECRET_INTERNAL_LABEL,
            deleted_label=SECRET_DELETED_LABEL,
        )
        self.peer_relation_unit = DataPeerUnit(
            self,
            relation_name=PEER_RELATION_NAME,
            additional_secret_fields=[
                "key",
                "csr",
                "cauth",
                "cert",
                "chain",
            ],
            secret_field_name=SECRET_INTERNAL_LABEL,
            deleted_label=SECRET_DELETED_LABEL,
        )

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        self.peers = Peers(self)
        self.backend = BackendDatabaseRequires(self)
        self.client_relation = PgBouncerProvider(self)
        self.legacy_db_relation = DbProvides(self, admin=False)
        self.legacy_db_admin_relation = DbProvides(self, admin=True)
        self.tls = PostgreSQLTLS(self, PEER_RELATION_NAME)

        self._cores = os.cpu_count()
        self.service_ids = list(range(self._cores))
        self.pgb_services = [
            f"{PGB}-{self.app.name}@{service_id}" for service_id in self.service_ids
        ]

        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": self.config["metrics_port"]},
            ],
            log_slots=[f"{POSTGRESQL_SNAP_NAME}:logs"],
            refresh_events=[self.on.config_changed],
        )

        self.upgrade = PgbouncerUpgrade(
            self,
            model=get_pgbouncer_dependencies_model(),
            relation_name="upgrade",
            substrate="vm",
        )

    # =======================
    #  Charm Lifecycle Hooks
    # =======================

    def render_utility_files(self):
        """Render charm utility services and configuration."""
        # Initialise pgbouncer.ini config files from defaults set in charm lib and current config.
        # We'll add basic configs for now even if this unit isn't a leader, so systemd doesn't
        # throw a fit.
        self.render_pgb_config()

        # Render pgbouncer service file and reload systemd
        with open("templates/pgbouncer.service.j2", "r") as file:
            template = Template(file.read())
        # Render the template file with the correct values.
        rendered = template.render(
            app_name=self.app.name, conf_dir=PGB_CONF_DIR, snap_tmp_dir=SNAP_TMP_DIR
        )

        self.render_file(
            f"/etc/systemd/system/{PGB}-{self.app.name}@.service", rendered, perms=0o644
        )
        systemd.daemon_reload()
        # Render the logrotate config
        with open("templates/logrotate.j2", "r") as file:
            template = Template(file.read())
        # Logrotate expects the file to be owned by root
        with open(f"/etc/logrotate.d/{PGB}-{self.app.name}", "w+") as file:
            file.write(
                template.render(
                    log_dir=PGB_LOG_DIR,
                    app_name=self.app.name,
                    service_ids=self.service_ids,
                    prefix=PGB,
                )
            )

    def _on_install(self, _) -> None:
        """On install hook.

        This initialises local config files necessary for pgbouncer to run.
        """
        self.unit.status = MaintenanceStatus("Installing and configuring PgBouncer")

        # Install the charmed PostgreSQL snap.
        try:
            self._install_snap_packages(packages=SNAP_PACKAGES)
        except snap.SnapError:
            self.unit.status = BlockedStatus("failed to install snap packages")
            return

        # Try to disable pgbackrest service
        try:
            cache = snap.SnapCache()
            selected_snap = cache["charmed-postgresql"]
            selected_snap.alias("psql")
            selected_snap.stop(services=["pgbackrest-service"], disable=True)
        except snap.SnapError as e:
            error_message = "Failed to stop and disable pgbackrest snap service"
            logger.exception(error_message, exc_info=e)

        pg_user = pwd.getpwnam(PG_USER)
        app_conf_dir = f"{PGB_CONF_DIR}/{self.app.name}"

        # Make a directory for each service to store configs.
        for service_id in self.service_ids:
            os.makedirs(f"{app_conf_dir}/{INSTANCE_DIR}{service_id}", 0o700, exist_ok=True)
            os.chown(f"{app_conf_dir}/{INSTANCE_DIR}{service_id}", pg_user.pw_uid, pg_user.pw_gid)

        self.render_utility_files()

        self.unit.status = WaitingStatus("Waiting to start PgBouncer")

    def remove_exporter_service(self) -> None:
        """Stops and removes the pgbouncer_exporter service if it exists."""
        prom_service = f"{PGB}-{self.app.name}-prometheus"
        try:
            systemd.service_stop(prom_service)
        except systemd.SystemdError:
            pass

        try:
            os.remove(f"/etc/systemd/system/{prom_service}.service")
        except FileNotFoundError:
            pass

    def _on_remove(self, _) -> None:
        """On Remove hook.

        Stops PGB and cleans up the host unit.
        """
        for service in self.pgb_services:
            systemd.service_stop(service)

        os.remove(f"/etc/systemd/system/{PGB}-{self.app.name}@.service")
        self.remove_exporter_service()
        os.remove(f"/etc/logrotate.d/{PGB}-{self.app.name}")

        shutil.rmtree(f"{PGB_CONF_DIR}/{self.app.name}")
        shutil.rmtree(f"{PGB_LOG_DIR}/{self.app.name}")
        shutil.rmtree(f"{SNAP_TMP_DIR}/{self.app.name}")

        systemd.daemon_reload()

    @property
    def version(self) -> str:
        """Returns the version Pgbouncer."""
        try:
            output = subprocess.check_output([PGBOUNCER_EXECUTABLE, "--version"])
            if output:
                return output.decode().split("\n")[0].split(" ")[1]
        except Exception:
            logger.exception("Unable to get Pgbouncer version")
            return ""

    def _normalize_secret_key(self, key: str) -> str:
        new_key = key.replace("_", "-")
        new_key = new_key.strip("-")

        return new_key

    def _scope_obj(self, scope: Scopes):
        if scope == APP_SCOPE:
            return self.app
        if scope == UNIT_SCOPE:
            return self.unit

    def peer_relation_data(self, scope: Scopes) -> DataPeer:
        """Returns the peer relation data per scope."""
        if scope == APP_SCOPE:
            return self.peer_relation_app
        elif scope == UNIT_SCOPE:
            return self.peer_relation_unit

    def _translate_field_to_secret_key(self, key: str) -> str:
        """Change 'key' to secrets-compatible key field."""
        if not JujuVersion.from_environ().has_secrets:
            return key
        key = SECRET_KEY_OVERRIDES.get(key, key)
        new_key = key.replace("_", "-")
        return new_key.strip("-")

    def get_secret(self, scope: Scopes, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        if scope not in get_args(Scopes):
            raise RuntimeError("Unknown secret scope.")

        peers = self.model.get_relation(PEER_RELATION_NAME)
        if not peers:
            return None
        secret_key = self._translate_field_to_secret_key(key)
        return self.peer_relation_data(scope).fetch_my_relation_field(peers.id, secret_key)

    def set_secret(self, scope: Scopes, key: str, value: Optional[str]) -> Optional[str]:
        """Set secret from the secret storage."""
        if scope not in get_args(Scopes):
            raise RuntimeError("Unknown secret scope.")

        if not value:
            return self.remove_secret(scope, key)

        peers = self.model.get_relation(PEER_RELATION_NAME)
        secret_key = self._translate_field_to_secret_key(key)
        self.peer_relation_data(scope).update_relation_data(peers.id, {secret_key: value})

    def remove_secret(self, scope: Scopes, key: str) -> None:
        """Removing a secret."""
        if scope not in get_args(Scopes):
            raise RuntimeError("Unknown secret scope.")

        peers = self.model.get_relation(PEER_RELATION_NAME)
        secret_key = self._translate_field_to_secret_key(key)
        self.peer_relation_data(scope).delete_relation_data(peers.id, [secret_key])

    def get_hostname_by_unit(self, _) -> str:
        """Create a DNS name for a Pgbouncer unit.

        Returns:
            A string representing the hostname of the Pgbouncer unit.
        """
        # For now, as there is no DNS hostnames on VMs, and it would also depend on
        # the underlying provider (LXD, MAAS, etc.), the unit IP is returned.
        return self.unit_ip

    def push_tls_files_to_workload(self, update_config: bool = True) -> bool:
        """Uploads TLS files to the workload container."""
        key, ca, cert = self.tls.get_tls_files()
        if key is not None:
            self.render_file(
                f"{PGB_CONF_DIR}/{self.app.name}/{TLS_KEY_FILE}",
                key,
                0o400,
            )
        if ca is not None:
            self.render_file(
                f"{PGB_CONF_DIR}/{self.app.name}/{TLS_CA_FILE}",
                ca,
                0o400,
            )
        if cert is not None:
            self.render_file(
                f"{PGB_CONF_DIR}/{self.app.name}/{TLS_CERT_FILE}",
                cert,
                0o400,
            )
        if update_config:
            return self.update_config()
        return True

    def _is_exposed(self) -> bool:
        # There should be only one client relation
        for relation in self.model.relations.get(CLIENT_RELATION_NAME, []):
            return bool(
                self.client_relation.database_provides.fetch_relation_field(
                    relation.id, "external-node-connectivity"
                )
            )

    def update_config(self) -> bool:
        """Updates PgBouncer config file based on the existence of the TLS files."""
        self.render_pgb_config(True)

        return True

    def _on_start(self, _) -> None:
        """On Start hook.

        Runs pgbouncer through systemd (configured in src/pgbouncer.service)
        """
        # Done first to instantiate the snap's private tmp
        self.unit.set_workload_version(self.version)

        if (
            (auth_file := self.get_secret(APP_SCOPE, AUTH_FILE_DATABAG_KEY))
            and self.backend.auth_user
            and self.backend.auth_user in auth_file
        ):
            self.render_auth_file(auth_file)

        if self.backend.postgres:
            self.render_prometheus_service()

        try:
            for service in self.pgb_services:
                logger.info(f"starting {service}")
                systemd.service_start(service)

            self.update_status()
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to start pgbouncer")
        prom_service = f"{PGB}-{self.app.name}-prometheus"
        if os.path.exists(f"/etc/systemd/system/{prom_service}.service"):
            try:
                systemd.service_start(prom_service)
            except systemd.SystemdError as e:
                logger.error(e)
                self.unit.status = BlockedStatus("failed to start pgbouncer exporter")

    def _on_leader_elected(self, _):
        self.peers.update_leader()

    def _on_update_status(self, _) -> None:
        """Update Status hook.

        Sets BlockedStatus if we have no backend database; if we can't connect to a backend, this
        charm serves no purpose.
        """
        self.update_status()

        self.peers.update_leader()

    def update_status(self):
        """Health check to update pgbouncer status based on charm state."""
        if self.unit.status.message == EXTENSIONS_BLOCKING_MESSAGE:
            return

        if self.backend.postgres is None:
            self.unit.status = BlockedStatus("waiting for backend database relation to initialise")
            return

        if not self.backend.ready:
            self.unit.status = BlockedStatus("backend database relation not ready")
            return

        if self.check_pgb_running():
            self.unit.status = ActiveStatus()

    def _on_config_changed(self, event) -> None:
        """Config changed handler.

        Reads charm config values, generates derivative values, writes new pgbouncer config, and
        restarts pgbouncer to apply changes.
        """
        old_port = self.peers.app_databag.get("current_port")
        if old_port != str(self.config["listen_port"]) and self._is_exposed():
            if self.unit.is_leader():
                self.peers.app_databag["current_port"] = str(self.config["listen_port"])
            # Open port
            try:
                if old_port:
                    self.unit.close_port("tcp", old_port)
                self.unit.open_port("tcp", self.config["listen_port"])
            except ModelError:
                logger.exception("failed to open port")

        # TODO hitting upgrade errors here due to secrets labels failing to set on non-leaders.
        # deferring until the leader manages to set the label
        try:
            self.render_pgb_config(reload_pgbouncer=True)
        except ModelError:
            logger.warning("Deferring on_config_changed: cannot set secret label")
            event.defer()
            return
        if self.backend.postgres:
            self.render_prometheus_service()

    def check_pgb_running(self):
        """Checks that pgbouncer service is running, and updates status accordingly."""
        prom_service = f"{PGB}-{self.app.name}-prometheus"
        services = [*self.pgb_services]

        if self.backend.ready:
            services.append(prom_service)

        try:
            for service in services:
                if not systemd.service_running(service):
                    pgb_not_running = f"PgBouncer service {service} not running"
                    logger.warning(pgb_not_running)
                    if self.unit.status.message != EXTENSIONS_BLOCKING_MESSAGE:
                        self.unit.status = BlockedStatus(pgb_not_running)
                    return False

        except systemd.SystemdError as e:
            logger.error(e)
            if self.unit.status.message != EXTENSIONS_BLOCKING_MESSAGE:
                self.unit.status = BlockedStatus("failed to get pgbouncer status")
            return False

        return True

    def reload_pgbouncer(self):
        """Restarts systemd pgbouncer service."""
        initial_status = self.unit.status
        self.unit.status = MaintenanceStatus("Reloading Pgbouncer")
        try:
            for service in self.pgb_services:
                systemd.service_restart(service)
            self.unit.status = initial_status
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("Failed to restart pgbouncer")

        self.check_pgb_running()

    # ==============================
    #  PgBouncer-Specific Utilities
    # ==============================

    def set_relation_databases(self, databases: Dict[int, Dict[str, Union[str, bool]]]) -> None:
        """Updates the relation databases."""
        self.peers.app_databag["pgb_dbs_config"] = json.dumps(databases)

    def get_relation_databases(self) -> Dict[str, Dict[str, Union[str, bool]]]:
        """Get relation databases."""
        if "pgb_dbs_config" in self.peers.app_databag:
            return json.loads(self.peers.app_databag["pgb_dbs_config"])
        # Nothing set in the config peer data trying to regenerate based on old data in case of update.
        elif not self.unit.is_leader():
            if cfg := self.get_secret(APP_SCOPE, CFG_FILE_DATABAG_KEY):
                try:
                    parser = ConfigParser()
                    parser.optionxform = str
                    parser.read_string(cfg)
                    old_cfg = dict(parser)
                    if databases := old_cfg.get("databases"):
                        databases.pop("DEFAULT", None)
                        result = {}
                        i = 1
                        for database in dict(databases):
                            if database.endswith("_standby") or database.endswith("_readonly"):
                                continue
                            result[str(i)] = {"name": database, "legacy": False}
                            i += 1
                        return result
                except Exception:
                    logger.exception("Unable to parse legacy config format")
        return {}

    def generate_relation_databases(self) -> Dict[str, Dict[str, Union[str, bool]]]:
        """Generates a mapping between relation and database and sets it in the app databag."""
        if not self.unit.is_leader():
            return {}
        if dbs := self.get_relation_databases():
            return dbs

        databases = {}
        for relation in self.model.relations.get("db", []):
            database = self.legacy_db_relation.get_databags(relation)[0].get("database")
            if database:
                databases[relation.id] = {
                    "name": database,
                    "legacy": True,
                }

        for relation in self.model.relations.get("db-admin", []):
            database = self.legacy_db_admin_relation.get_databags(relation)[0].get("database")
            if database:
                databases[relation.id] = {
                    "name": database,
                    "legacy": True,
                }

        for rel_id, data in self.client_relation.database_provides.fetch_relation_data(
            fields=["database"]
        ).items():
            database = data.get("database")
            if database:
                databases[rel_id] = {
                    "name": database,
                    "legacy": False,
                }
        self.set_relation_databases(databases)
        return databases

    def _get_relation_config(self) -> [Dict[str, Dict[str, Union[str, bool]]]]:
        """Generate pgb config for databases and admin users."""
        if not self.backend.relation or not (databases := self.get_relation_databases()):
            return {}

        # In postgres, "endpoints" will only ever have one value. Other databases using the library
        # can have more, but that's not planned for the postgres charm.
        if not (postgres_endpoint := self.backend.postgres_databag.get("endpoints")):
            return {}
        host, port = postgres_endpoint.split(":")

        read_only_endpoints = self.backend.get_read_only_endpoints()
        r_hosts = ",".join([r_host.split(":")[0] for r_host in read_only_endpoints])
        if r_hosts:
            for r_host in read_only_endpoints:
                r_port = r_host.split(":")[1]
                break

        pgb_dbs = {}

        for database in databases.values():
            name = database["name"]
            pgb_dbs[name] = {
                "host": host,
                "dbname": name,
                "port": port,
                "auth_user": self.backend.auth_user,
            }
            if r_hosts:
                pgb_dbs[f"{name}_readonly"] = {
                    "host": r_hosts,
                    "dbname": name,
                    "port": r_port,
                    "auth_user": self.backend.auth_user,
                }
        return pgb_dbs

    def render_pgb_config(self, reload_pgbouncer=False):
        """Derives config files for the number of required services from given config.

        This method takes a primary config and generates one unique config for each intended
        instance of pgbouncer, implemented as a templated systemd service.
        """
        initial_status = self.unit.status
        self.unit.status = MaintenanceStatus("updating PgBouncer config")

        # Render primary config. This config is the only copy that the charm reads from to create
        # PgbConfig objects, and is modified below to implement individual services.
        app_conf_dir = f"{PGB_CONF_DIR}/{self.app.name}"
        app_log_dir = f"{PGB_LOG_DIR}/{self.app.name}"
        app_temp_dir = f"/tmp/{self.app.name}"

        max_db_connections = self.config["max_db_connections"]
        if max_db_connections == 0:
            default_pool_size = 20
            min_pool_size = 10
            reserve_pool_size = 10
        else:
            effective_db_connections = max_db_connections / self._cores
            default_pool_size = math.ceil(effective_db_connections / 2)
            min_pool_size = math.ceil(effective_db_connections / 4)
            reserve_pool_size = math.ceil(effective_db_connections / 4)
        with open("templates/pgb_config.j2", "r") as file:
            template = Template(file.read())
            databases = self._get_relation_config()
            enable_tls = all(self.tls.get_tls_files()) and self._is_exposed
            if self._is_exposed:
                addr = "*"
            else:
                addr = "127.0.0.1"
            # Modify & render config files for each service instance
            for service_id in self.service_ids:
                self.unit.status = MaintenanceStatus("updating PgBouncer config")
                self.render_file(
                    f"{app_conf_dir}/{INSTANCE_DIR}{service_id}/pgbouncer.ini",
                    template.render(
                        databases=databases,
                        socket_dir=f"{app_temp_dir}/{INSTANCE_DIR}{service_id}",
                        log_file=f"{app_log_dir}/{INSTANCE_DIR}{service_id}/pgbouncer.log",
                        pid_file=f"{app_temp_dir}/{INSTANCE_DIR}{service_id}/pgbouncer.pid",
                        listen_addr=addr,
                        listen_port=self.config["listen_port"],
                        pool_mode=self.config["pool_mode"],
                        max_db_connections=max_db_connections,
                        default_pool_size=default_pool_size,
                        min_pool_size=min_pool_size,
                        reserve_pool_size=reserve_pool_size,
                        stats_user=self.backend.stats_user,
                        auth_query=self.backend.auth_query,
                        auth_file=f"{app_conf_dir}/{AUTH_FILE_NAME}",
                        enable_tls=enable_tls,
                        key_file=f"{app_conf_dir}/{TLS_KEY_FILE}",
                        ca_file=f"{app_conf_dir}/{TLS_CA_FILE}",
                        cert_file=f"{app_conf_dir}/{TLS_CERT_FILE}",
                    ),
                    0o700,
                )
        self.unit.status = initial_status

        if reload_pgbouncer:
            self.reload_pgbouncer()

    def render_prometheus_service(self):
        """Render a unit file for the prometheus exporter and restarts the service."""
        # Render prometheus exporter service file
        with open("templates/prometheus-exporter.service.j2", "r") as file:
            template = Template(file.read())
        # Render the template file with the correct values.
        rendered = template.render(
            stats_user=self.backend.stats_user,
            pgb_service=f"{PGB}-{self.app.name}",
            stats_password=self.get_secret(APP_SCOPE, MONITORING_PASSWORD_KEY),
            listen_port=self.config["listen_port"],
            metrics_port=self.config["metrics_port"],
        )

        service = f"{PGB}-{self.app.name}-prometheus"
        self.render_file(f"/etc/systemd/system/{service}.service", rendered, perms=0o644)

        systemd.daemon_reload()

        try:
            systemd.service_restart(service)
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("Failed to restart prometheus exporter")

    def render_auth_file(self, auth_file: str, reload_pgbouncer: bool = False):
        """Render user list (with encoded passwords) to pgbouncer.ini file.

        Args:
            auth_file: the auth file to be rendered
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        initial_status = self.unit.status
        self.unit.status = MaintenanceStatus("updating PgBouncer users")

        self.render_file(
            f"{PGB_CONF_DIR}/{self.app.name}/{AUTH_FILE_NAME}", auth_file, perms=0o700
        )
        self.unit.status = initial_status

        if reload_pgbouncer:
            self.reload_pgbouncer()

    # =================
    #  Charm Utilities
    # =================

    def _install_snap_packages(self, packages: List[str], refresh: bool = False) -> None:
        """Installs package(s) to container.

        Args:
            packages: list of packages to install.
            refresh: whether to refresh the snap if it's
                already present.
        """
        for snap_name, snap_version in packages:
            try:
                snap_cache = snap.SnapCache()
                snap_package = snap_cache[snap_name]

                if not snap_package.present or refresh:
                    if revision := snap_version.get("revision"):
                        try:
                            revision = revision[platform.machine()]
                        except Exception:
                            logger.error("Unavailable snap architecture %s", platform.machine())
                            raise
                        channel = snap_version.get("channel", "")
                        snap_package.ensure(
                            snap.SnapState.Latest, revision=revision, channel=channel
                        )
                        snap_package.hold()
                    else:
                        snap_package.ensure(snap.SnapState.Latest, channel=snap_version["channel"])

            except (snap.SnapError, snap.SnapNotFoundError) as e:
                logger.error(
                    "An exception occurred when installing %s. Reason: %s", snap_name, str(e)
                )
                raise

    def render_file(self, path: str, content: str, perms: int) -> None:
        """Write content rendered from a template to a file.

        Args:
            path: the path to the file.
            content: the data to be written to the file.
            perms: access permission mask applied to the file using chmod (e.g. 0o700).
        """
        with open(path, "w+") as file:
            file.write(content)
        # Ensure correct permissions are set on the file.
        os.chmod(path, perms)
        # Get the uid/gid for the postgres user.
        u = pwd.getpwnam(PG_USER)
        # Set the correct ownership for the file.
        os.chown(path, uid=u.pw_uid, gid=u.pw_gid)

    def delete_file(self, path: str):
        """Deletes file at the given path."""
        if os.path.exists(path):
            os.remove(path)

    @property
    def unit_ip(self) -> str:
        """Current unit IP."""
        return str(self.model.get_binding(PEER_RELATION_NAME).network.bind_address)

    # =====================
    #  Relation Utilities
    # =====================

    def update_client_connection_info(self, port: Optional[str] = None):
        """Update ports in backend relations to match updated pgbouncer port."""
        # Skip updates if backend.postgres doesn't exist yet.
        if not self.backend.postgres or not self.unit.is_leader():
            return

        if port is None:
            port = self.config["listen_port"]

        for relation in self.model.relations.get("db", []):
            self.legacy_db_relation.update_connection_info(relation, port)

        for relation in self.model.relations.get("db-admin", []):
            self.legacy_db_admin_relation.update_connection_info(relation, port)

        for relation in self.model.relations.get(CLIENT_RELATION_NAME, []):
            self.client_relation.update_connection_info(relation)

    @property
    def leader_ip(self) -> str:
        """Gets leader ip."""
        return self.peers.leader_ip


if __name__ == "__main__":
    main(PgBouncerCharm)
