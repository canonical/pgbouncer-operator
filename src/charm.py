#!/usr/bin/env -S LD_LIBRARY_PATH=lib python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charmed PgBouncer connection pooler, to run on machine charms."""

import logging
import os
import pwd
import shutil
import subprocess
from copy import deepcopy
from typing import List, Optional, Union

from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from charms.operator_libs_linux.v1 import systemd
from charms.operator_libs_linux.v2 import snap
from charms.pgbouncer_k8s.v0 import pgb
from charms.postgresql_k8s.v0.postgresql_tls import PostgreSQLTLS
from jinja2 import Template
from ops import JujuVersion
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    SecretNotFoundError,
    WaitingStatus,
)

from constants import (
    APP_SCOPE,
    AUTH_FILE_NAME,
    CLIENT_RELATION_NAME,
    EXTENSIONS_BLOCKING_MESSAGE,
    INI_NAME,
    MONITORING_PASSWORD_KEY,
    PEER_RELATION_NAME,
    PG_USER,
    PGB,
    PGB_CONF_DIR,
    PGB_LOG_DIR,
    PGBOUNCER_EXECUTABLE,
    POSTGRESQL_SNAP_NAME,
    SECRET_CACHE_LABEL,
    SECRET_DELETED_LABEL,
    SECRET_INTERNAL_LABEL,
    SECRET_KEY_OVERRIDES,
    SECRET_LABEL,
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

INSTANCE_DIR = "instance_"


class PgBouncerCharm(CharmBase):
    """A class implementing charmed PgBouncer."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self.secrets = {APP_SCOPE: {}, UNIT_SCOPE: {}}

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
        cfg = pgb.PgbConfig(pgb.DEFAULT_CONFIG)
        cfg["pgbouncer"]["listen_addr"] = "127.0.0.1"
        cfg["pgbouncer"]["user"] = "snap_daemon"
        self.render_pgb_config(cfg)

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

    def _scope_obj(self, scope: str):
        if scope == APP_SCOPE:
            return self.framework.model.app
        if scope == UNIT_SCOPE:
            return self.framework.model.unit

    def _juju_secrets_get(self, scope: str) -> Optional[bool]:
        """Helper function to get Juju secret."""
        if scope == UNIT_SCOPE:
            peer_data = self.peers.unit_databag
        else:
            peer_data = self.peers.app_databag

        if not peer_data.get(SECRET_INTERNAL_LABEL):
            return

        if SECRET_CACHE_LABEL not in self.secrets[scope]:
            try:
                # NOTE: Secret contents are not yet available!
                secret = self.model.get_secret(id=peer_data[SECRET_INTERNAL_LABEL])
            except SecretNotFoundError as e:
                logging.debug(f"No secret found for ID {peer_data[SECRET_INTERNAL_LABEL]}, {e}")
                return

            logging.debug(f"Secret {peer_data[SECRET_INTERNAL_LABEL]} downloaded")

            # We keep the secret object around -- needed when applying modifications
            self.secrets[scope][SECRET_LABEL] = secret

            # We retrieve and cache actual secret data for the lifetime of the event scope
            try:
                self.secrets[scope][SECRET_CACHE_LABEL] = secret.get_content(refresh=True)
            except (ValueError, ModelError) as err:
                # https://bugs.launchpad.net/juju/+bug/2042596
                # Only triggered when 'refresh' is set
                known_model_errors = [
                    "ERROR either URI or label should be used for getting an owned secret but not both",
                    "ERROR secret owner cannot use --refresh",
                ]
                if isinstance(err, ModelError) and not any(
                    msg in str(err) for msg in known_model_errors
                ):
                    raise
                # Due to: ValueError: Secret owner cannot use refresh=True
                self.secrets[scope][SECRET_CACHE_LABEL] = secret.get_content()

        return bool(self.secrets[scope].get(SECRET_CACHE_LABEL))

    def _juju_secret_get_key(self, scope: str, key: str) -> Optional[str]:
        if not key:
            return

        key = SECRET_KEY_OVERRIDES.get(key, self._normalize_secret_key(key))

        if self._juju_secrets_get(scope):
            secret_cache = self.secrets[scope].get(SECRET_CACHE_LABEL)
            if secret_cache:
                secret_data = secret_cache.get(key)
                if secret_data and secret_data != SECRET_DELETED_LABEL:
                    logging.debug(f"Getting secret {scope}:{key}")
                    return secret_data
        logging.debug(f"No value found for secret {scope}:{key}")

    def get_secret(self, scope: str, key: str) -> Optional[str]:
        """Get secret from the secret storage."""
        if scope not in [APP_SCOPE, UNIT_SCOPE]:
            raise RuntimeError("Unknown secret scope.")

        if scope == UNIT_SCOPE:
            result = self.peers.unit_databag.get(key, None)
        else:
            result = self.peers.app_databag.get(key, None)

        # TODO change upgrade to switch to secrets once minor version upgrades is done
        if result:
            return result

        juju_version = JujuVersion.from_environ()
        if juju_version.has_secrets:
            return self._juju_secret_get_key(scope, key)

    def _juju_secret_set(self, scope: str, key: str, value: str) -> Optional[str]:
        """Helper function setting Juju secret."""
        if scope == UNIT_SCOPE:
            peer_data = self.peers.unit_databag
        else:
            peer_data = self.peers.app_databag
        self._juju_secrets_get(scope)

        key = SECRET_KEY_OVERRIDES.get(key, self._normalize_secret_key(key))

        secret = self.secrets[scope].get(SECRET_LABEL)

        # It's not the first secret for the scope, we can reuse the existing one
        # that was fetched in the previous call
        if secret:
            secret_cache = self.secrets[scope][SECRET_CACHE_LABEL]

            if secret_cache.get(key) == value:
                logging.debug(f"Key {scope}:{key} has this value defined already")
            else:
                secret_cache[key] = value
                try:
                    secret.set_content(secret_cache)
                except OSError as error:
                    logging.error(
                        f"Error in attempt to set {scope}:{key}. "
                        f"Existing keys were: {list(secret_cache.keys())}. {error}"
                    )
                    return
                logging.debug(f"Secret {scope}:{key} was {key} set")

        # We need to create a brand-new secret for this scope
        else:
            scope_obj = self._scope_obj(scope)

            secret = scope_obj.add_secret({key: value})
            if not secret:
                raise RuntimeError(f"Couldn't set secret {scope}:{key}")

            self.secrets[scope][SECRET_LABEL] = secret
            self.secrets[scope][SECRET_CACHE_LABEL] = {key: value}
            logging.debug(f"Secret {scope}:{key} published (as first). ID: {secret.id}")
            peer_data.update({SECRET_INTERNAL_LABEL: secret.id})

        return self.secrets[scope][SECRET_LABEL].id

    def set_secret(self, scope: str, key: str, value: Optional[str]) -> Optional[str]:
        """Set secret from the secret storage."""
        if scope not in [APP_SCOPE, UNIT_SCOPE]:
            raise RuntimeError("Unknown secret scope.")

        if not value:
            return self.remove_secret(scope, key)

        juju_version = JujuVersion.from_environ()

        if juju_version.has_secrets:
            self._juju_secret_set(scope, key, value)
            return
        if scope == UNIT_SCOPE:
            self.peers.unit_databag.update({key: value})
        else:
            self.peers.app_databag.update({key: value})

    def _juju_secret_remove(self, scope: str, key: str) -> None:
        """Remove a Juju 3.x secret."""
        self._juju_secrets_get(scope)

        key = SECRET_KEY_OVERRIDES.get(key, self._normalize_secret_key(key))

        secret = self.secrets[scope].get(SECRET_LABEL)
        if not secret:
            logging.error(f"Secret {scope}:{key} wasn't deleted: no secrets are available")
            return

        secret_cache = self.secrets[scope].get(SECRET_CACHE_LABEL)
        if not secret_cache or key not in secret_cache:
            logging.error(f"No secret {scope}:{key}")
            return

        secret_cache[key] = SECRET_DELETED_LABEL
        secret.set_content(secret_cache)
        logging.debug(f"Secret {scope}:{key}")

    def remove_secret(self, scope: str, key: str) -> None:
        """Removing a secret."""
        if scope not in [APP_SCOPE, UNIT_SCOPE]:
            raise RuntimeError("Unknown secret scope.")

        juju_version = JujuVersion.from_environ()
        if juju_version.has_secrets:
            return self._juju_secret_remove(scope, key)
        if scope == UNIT_SCOPE:
            del self.peers.unit_databag[key]
        else:
            del self.peers.app_databag[key]

    def get_hostname_by_unit(self, _) -> str:
        """Create a DNS name for a Pgbouncer unit.

        Returns:
            A string representing the hostname of the Pgbouncer unit.
        """
        # For now, as there is no DNS hostnames on VMs, and it would also depend on
        # the underlying provider (LXD, MAAS, etc.), the unit IP is returned.
        return self.unit_ip

    def push_tls_files_to_workload(self, update_config: bool = True) -> None:
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
            self.update_config()

    def update_config(self) -> None:
        """Updates PgBouncer config file based on the existence of the TLS files."""
        try:
            config = self.read_pgb_config()
        except FileNotFoundError as err:
            logger.warning(f"update_config: Unable to read config, error: {err}")
            return False

        if all(self.tls.get_tls_files()) and self.config["expose"]:
            config["pgbouncer"][
                "client_tls_key_file"
            ] = f"{PGB_CONF_DIR}/{self.app.name}/{TLS_KEY_FILE}"
            config["pgbouncer"][
                "client_tls_ca_file"
            ] = f"{PGB_CONF_DIR}/{self.app.name}/{TLS_CA_FILE}"
            config["pgbouncer"][
                "client_tls_cert_file"
            ] = f"{PGB_CONF_DIR}/{self.app.name}/{TLS_CERT_FILE}"
            config["pgbouncer"]["client_tls_sslmode"] = "prefer"
        else:
            # cleanup tls keys if present
            config["pgbouncer"].pop("client_tls_key_file", None)
            config["pgbouncer"].pop("client_tls_cert_file", None)
            config["pgbouncer"].pop("client_tls_ca_file", None)
            config["pgbouncer"].pop("client_tls_sslmode", None)
        self.render_pgb_config(config, True)

        return True

    def _on_start(self, _) -> None:
        """On Start hook.

        Runs pgbouncer through systemd (configured in src/pgbouncer.service)
        """
        # Done first to instantiate the snap's private tmp
        self.unit.set_workload_version(self.version)

        try:
            for service in self.pgb_services:
                logger.info(f"starting {service}")
                systemd.service_start(service)

            if self.backend.postgres:
                self.unit.status = self.check_status()
            else:
                # Wait for backend relation relation if it doesn't exist
                self.unit.status = BlockedStatus("waiting for backend database relation")
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("failed to start pgbouncer")
        prom_service = f"{PGB}-{self.app.name}-prometheus"
        if os.path.exists(f"/etc/systemd/system/{prom_service}.service"):
            try:
                systemd.service_start(service)
            except systemd.SystemdError as e:
                logger.error(e)
                self.unit.status = BlockedStatus("failed to start pgbouncer exporter")

    def _on_leader_elected(self, _):
        self.peers.update_connection()

    def _on_update_status(self, _) -> None:
        """Update Status hook."""
        self.unit.status = self.check_status()

    def _on_config_changed(self, _) -> None:
        """Config changed handler.

        Reads charm config values, generates derivative values, writes new pgbouncer config, and
        restarts pgbouncer to apply changes.
        """
        if not self.unit.is_leader():
            return

        cfg = self.read_pgb_config()
        cfg["pgbouncer"]["pool_mode"] = self.config["pool_mode"]

        cfg.set_max_db_connection_derivatives(
            self.config["max_db_connections"],
            self._cores,
        )

        if cfg["pgbouncer"]["listen_port"] != self.config["listen_port"]:
            # This emits relation-changed events to every client relation, so only do it when
            # necessary
            self.update_client_connection_info(self.config["listen_port"])
            cfg["pgbouncer"]["listen_port"] = self.config["listen_port"]

        self.render_pgb_config(cfg, reload_pgbouncer=True)
        if self.backend.postgres:
            self.render_prometheus_service()

    def check_status(self) -> Union[ActiveStatus, BlockedStatus, WaitingStatus]:
        """Checks status of PgBouncer application.

        Checks whether pgb config is available, backend is ready, and pgbouncer systemd service is
        running.

        Returns:
            Recommended unit status. Can be active, blocked, or waiting.
        """
        try:
            self.read_pgb_config()
        except FileNotFoundError:
            wait_str = "waiting for pgbouncer to start"
            logger.warning(wait_str)
            return WaitingStatus(wait_str)

        if not self.backend.ready:
            # We can't relate an app to the backend database without a backend postgres relation
            backend_wait_msg = "waiting for backend database relation to connect"
            logger.warning(backend_wait_msg)
            return BlockedStatus(backend_wait_msg)

        if self.unit.status.message == EXTENSIONS_BLOCKING_MESSAGE:
            return BlockedStatus(EXTENSIONS_BLOCKING_MESSAGE)

        prom_service = f"{PGB}-{self.app.name}-prometheus"
        services = [*self.pgb_services]

        if self.backend.postgres:
            services.append(prom_service)

        try:
            for service in services:
                if not systemd.service_running(service):
                    return BlockedStatus(f"{service} is not running")

        except systemd.SystemdError as e:
            logger.error(e)
            return BlockedStatus("failed to get pgbouncer status")

        return ActiveStatus()

    def reload_pgbouncer(self):
        """Restarts systemd pgbouncer service."""
        self.unit.status = MaintenanceStatus("Reloading Pgbouncer")
        try:
            for service in self.pgb_services:
                systemd.service_restart(service)
        except systemd.SystemdError as e:
            logger.error(e)
            self.unit.status = BlockedStatus("Failed to restart pgbouncer")

        self.unit.status = self.check_status()

    # ==============================
    #  PgBouncer-Specific Utilities
    # ==============================

    def read_pgb_config(self) -> pgb.PgbConfig:
        """Get config object from pgbouncer.ini file.

        Returns:
            PgbConfig object containing pgbouncer config.
        """
        with open(f"{PGB_CONF_DIR}/{self.app.name}/{INI_NAME}", "r") as file:
            config = pgb.PgbConfig(file.read())
        return config

    def render_pgb_config(self, config: pgb.PgbConfig, reload_pgbouncer=False):
        """Derives config files for the number of required services from given config.

        This method takes a primary config and generates one unique config for each intended
        instance of pgbouncer, implemented as a templated systemd service.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer config")

        self.peers.update_cfg(config)

        # create a copy of the config so the original reference is unchanged.
        primary_config = deepcopy(config)

        # Render primary config. This config is the only copy that the charm reads from to create
        # PgbConfig objects, and is modified below to implement individual services.
        app_conf_dir = f"{PGB_CONF_DIR}/{self.app.name}"
        app_log_dir = f"{PGB_LOG_DIR}/{self.app.name}"
        app_temp_dir = f"/tmp/{self.app.name}"
        self._render_pgb_config(
            pgb.PgbConfig(primary_config), config_path=f"{app_conf_dir}/{INI_NAME}"
        )

        # Modify & render config files for each service instance
        for service_id in self.service_ids:
            primary_config[PGB]["unix_socket_dir"] = f"{app_temp_dir}/{INSTANCE_DIR}{service_id}"
            primary_config[PGB][
                "logfile"
            ] = f"{app_log_dir}/{INSTANCE_DIR}{service_id}/pgbouncer.log"
            primary_config[PGB][
                "pidfile"
            ] = f"{app_temp_dir}/{INSTANCE_DIR}{service_id}/pgbouncer.pid"

            self._render_pgb_config(
                primary_config,
                config_path=f"{app_conf_dir}/{INSTANCE_DIR}{service_id}/pgbouncer.ini",
            )

        if reload_pgbouncer:
            self.reload_pgbouncer()

    def _render_pgb_config(
        self,
        pgbouncer_ini: pgb.PgbConfig,
        reload_pgbouncer: bool = False,
        config_path: str = None,
    ) -> None:
        """Render config object to pgbouncer.ini file.

        Args:
            pgbouncer_ini: PgbConfig object containing pgbouncer config.
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
            config_path: intended location for the config.
        """
        if config_path is None:
            config_path = f"{PGB_CONF_DIR}/{self.app.name}/{INI_NAME}"
        self.unit.status = MaintenanceStatus("updating PgBouncer config")
        self.render_file(config_path, pgbouncer_ini.render(), 0o700)

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

    def read_auth_file(self) -> str:
        """Gets the auth file from the pgbouncer container filesystem."""
        with open(f"{PGB_CONF_DIR}/{self.app.name}/{AUTH_FILE_NAME}", "r") as fd:
            return fd.read()

    def render_auth_file(self, auth_file: str, reload_pgbouncer: bool = False):
        """Render user list (with encoded passwords) to pgbouncer.ini file.

        Args:
            auth_file: the auth file to be rendered
            reload_pgbouncer: A boolean defining whether or not to reload the pgbouncer
                application. When config files are updated, pgbouncer must be restarted for the
                changes to take effect. However, these config updates can be done in batches,
                minimising the amount of necessary restarts.
        """
        self.unit.status = MaintenanceStatus("updating PgBouncer users")

        self.peers.update_auth_file(auth_file)
        self.render_file(
            f"{PGB_CONF_DIR}/{self.app.name}/{AUTH_FILE_NAME}", auth_file, perms=0o700
        )

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
                    if snap_version.get("revision"):
                        snap_package.ensure(
                            snap.SnapState.Latest, revision=snap_version["revision"]
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
        if not self.backend.postgres:
            return

        if port is None:
            port = self.config["listen_port"]

        for relation in self.model.relations.get("db", []):
            self.legacy_db_relation.update_connection_info(relation, port)

        for relation in self.model.relations.get("db-admin", []):
            self.legacy_db_admin_relation.update_connection_info(relation, port)

        for relation in self.model.relations.get(CLIENT_RELATION_NAME, []):
            self.client_relation.update_connection_info(relation)

    def update_postgres_endpoints(self, reload_pgbouncer):
        """Update postgres endpoints in relation config values."""
        # Skip updates if backend.postgres doesn't exist yet.
        if not self.backend.postgres or not self.unit.is_leader():
            return

        self.unit.status = MaintenanceStatus("Model changed - updating postgres endpoints")

        for relation in self.model.relations.get("db", []):
            self.legacy_db_relation.update_postgres_endpoints(relation, reload_pgbouncer=False)

        for relation in self.model.relations.get("db-admin", []):
            self.legacy_db_admin_relation.update_postgres_endpoints(
                relation, reload_pgbouncer=False
            )

        for relation in self.model.relations.get(CLIENT_RELATION_NAME, []):
            self.client_relation.update_postgres_endpoints(relation, reload_pgbouncer=False)

        if reload_pgbouncer:
            self.reload_pgbouncer()

    @property
    def leader_ip(self) -> str:
        """Gets leader ip."""
        return self.peers.leader_ip


if __name__ == "__main__":
    main(PgBouncerCharm)
