# Copyright 2017 Hynek Schlawack

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function

import codecs
import logging
import sys

import attr

from ._environ_config import CNF_KEY, RAISE, _ConfigEntry
from .exceptions import MissingSecretError


try:
    from configparser import RawConfigParser, NoOptionError
except ImportError:
    from ConfigParser import RawConfigParser, NoOptionError


log = logging.getLogger(__name__)


@attr.s
class INISecrets(object):
    section = attr.ib()
    _cfg = attr.ib(default=None)
    _env_name = attr.ib(default=None)
    _env_default = attr.ib(default=None)

    @classmethod
    def from_path(cls, path, section="secrets"):
        return cls(section, _load_ini(path), None, None)

    @classmethod
    def from_path_in_env(cls, env_name, default=None, section="secrets"):
        """
        Get and load path only when actually loading config.  Useful in tests
        for setting up an environment.
        """
        return cls(section, None, env_name, default)

    def secret(
        self, default=RAISE, converter=None, name=None, section=None, help=None
    ):
        if section is None:
            section = self.section

        return attr.ib(
            default=default,
            metadata={
                CNF_KEY: _ConfigEntry(name, default, None, self._get, help),
                CNF_INI_SECRET_KEY: _INIConfig(section),
            },
            converter=converter,
        )

    def _get(self, environ, metadata, prefix, name):
        # Delayed loading.
        if self._cfg is None and self._env_name is not None:
            log.debug("looking for env var '%s'." % (self._env_name,))
            self._cfg = _load_ini(
                environ.get(self._env_name, self._env_default)
            )

        ce = metadata[CNF_KEY]
        ic = metadata[CNF_INI_SECRET_KEY]
        section = ic.section

        if ce.name is not None:
            var = ce.name
        else:
            var = "_".join((prefix + (name,)))
        try:
            log.debug("looking for '%s' in section '%s'." % (var, section))
            return _SecretStr(self._cfg.get(section, var))
        except NoOptionError:
            if ce.default is not RAISE:
                return ce.default
            raise MissingSecretError(var)


@attr.s
class VaultEnvSecrets(object):
    """
    Almost identical to regular env vars except that it has its own prefix.
    """

    vault_prefix = attr.ib()

    def secret(self, default=RAISE, converter=None, name=None, help=None):
        return attr.ib(
            default=default,
            metadata={
                CNF_KEY: _ConfigEntry(name, default, None, self._get, help)
            },
            converter=converter,
        )

    def _get(self, environ, metadata, prefix, name):
        ce = metadata[CNF_KEY]

        if ce.name is not None:
            var = ce.name
        else:
            if callable(self.vault_prefix):
                vp = self.vault_prefix(environ)
            else:
                vp = self.vault_prefix
            var = "_".join(((vp,) + prefix + (name,))).upper()

        log.debug("looking for env var '%s'." % (var,))
        val = environ.get(var, ce.default)
        if val is RAISE:
            raise MissingSecretError(var)
        return _SecretStr(val)


class _SecretStr(str):
    """
    String that censors its __repr__ if called from an attrs repr.
    """

    def __repr__(self):
        # The frame numbers varies across attrs versions. Use this convoluted
        # form to make the call lazy.
        if (
            sys._getframe(1).f_code.co_name == "__repr__"
            or sys._getframe(2).f_code.co_name == "__repr__"
        ):
            return "<SECRET>"
        else:
            return str.__repr__(self)


CNF_INI_SECRET_KEY = CNF_KEY + "_ini_secret"


@attr.s
class _INIConfig(object):
    section = attr.ib()


def _load_ini(path):
    """
    Load an INI file from *path*.
    """
    cfg = RawConfigParser()
    with codecs.open(path, mode="r", encoding="utf-8") as f:
        try:
            cfg.read_file(f)
        except AttributeError:
            cfg.readfp(f)

    return cfg
