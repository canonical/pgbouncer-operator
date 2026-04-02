# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""A collection of utility functions that are used in the charm."""

import logging
import os
import shutil
from collections import defaultdict

from importlib_metadata import distributions


def _remove_stale_otel_sdk_packages():
    """Hack to remove stale opentelemetry sdk packages from the charm's python venv.

    See https://github.com/canonical/grafana-agent-operator/issues/146 and
    https://bugs.launchpad.net/juju/+bug/2058335 for more context. This patch can be removed after
    this juju issue is resolved and sufficient time has passed to expect most users of this library
    have migrated to the patched version of juju.  When this patch is removed, un-ignore rule E402 for this file in the pyproject.toml (see setting
    [tool.ruff.lint.per-file-ignores] in pyproject.toml).

    This only has an effect if executed on an upgrade-charm event.
    """
    # all imports are local to keep this function standalone, side-effect-free, and easy to revert later

    major_version = int(juju_ver.split(".")[0]) if (juju_ver := os.getenv("JUJU_VERSION")) else 3
    if os.getenv("JUJU_DISPATCH_PATH") != "hooks/upgrade-charm" or major_version > 2:
        return

    otel_logger = logging.getLogger("charm_tracing_otel_patcher")
    otel_logger.debug("Applying _remove_stale_otel_sdk_packages patch on charm upgrade")
    # group by name all distributions starting with "opentelemetry_"
    otel_distributions = defaultdict(list)
    for distribution in distributions():
        name = distribution._normalized_name
        if name.startswith("opentelemetry_"):
            otel_distributions[name].append(distribution)

    otel_logger.debug(f"Found {len(otel_distributions)} opentelemetry distributions")

    # If we have multiple distributions with the same name, remove any that have 0 associated files
    for name, distributions_ in otel_distributions.items():
        if len(distributions_) <= 1:
            continue

        otel_logger.debug(f"Package {name} has multiple ({len(distributions_)}) distributions.")
        for distribution in distributions_:
            if not distribution.files:  # Not None or empty list
                path = distribution._path
                otel_logger.info(f"Removing empty distribution of {name} at {path}.")
                shutil.rmtree(path)

    otel_logger.debug("Successfully applied _remove_stale_otel_sdk_packages patch.")
