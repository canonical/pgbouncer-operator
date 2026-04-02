# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import Mock, patch, sentinel

from utils import _remove_stale_otel_sdk_packages


@patch("utils.distributions")
@patch("utils.shutil")
@patch("utils.os.getenv", return_value=None)
def test_remove_stale_otel_sdk_packages(_getenv, _shutil, _distributions):
    other_dist = Mock()
    other_dist._normalized_name = "test"
    otel_dist = Mock()
    otel_dist._normalized_name = "opentelemetry_test"
    stale_otel_dist = Mock()
    stale_otel_dist._normalized_name = "opentelemetry_test"
    stale_otel_dist.files = []
    stale_otel_dist._path = sentinel.path

    # Not called if not upgrade hook
    _remove_stale_otel_sdk_packages()

    _distributions.assert_not_called()
    _shutil.rmtree.assert_not_called()
    _distributions.reset_mock()
    _shutil.rmtree.reset_mock()

    # don't execute on Juju 3
    _getenv.side_effect = ["3.0.0", "hooks/upgrade-charm"]
    _remove_stale_otel_sdk_packages()

    _distributions.assert_not_called()
    _shutil.rmtree.assert_not_called()
    _distributions.reset_mock()
    _shutil.rmtree.reset_mock()

    # Upgrade hook, nothing to remove
    _getenv.side_effect = ["2.9.53", "hooks/upgrade-charm"]
    _distributions.return_value = [other_dist, otel_dist]

    _remove_stale_otel_sdk_packages()

    _distributions.assert_called_once_with()
    _shutil.rmtree.assert_not_called()
    _distributions.reset_mock()
    _shutil.rmtree.reset_mock()

    # Upgrade hook, duplicate otel packages
    _getenv.side_effect = ["2.9.53", "hooks/upgrade-charm"]
    _distributions.return_value = [other_dist, otel_dist, stale_otel_dist]
    _remove_stale_otel_sdk_packages()

    _distributions.assert_called_once_with()
    _shutil.rmtree.assert_called_once_with(sentinel.path)
    _distributions.reset_mock()
    _shutil.rmtree.reset_mock()
