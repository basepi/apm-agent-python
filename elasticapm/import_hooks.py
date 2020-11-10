#  BSD 3-Clause License
#
#  Copyright (c) 2019, Elasticsearch BV
#  All rights reserved.
#
#  Redistribution and use in source and binary forms, with or without
#  modification, are permitted provided that the following conditions are met:
#
#  * Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
#  * Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
#  * Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from
#    this software without specific prior written permission.
#
#  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
#  AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
#  IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
#  DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
#  FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
#  DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
#  SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
#  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
#  OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#  OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import importlib.abc
import sys
from importlib.util import find_spec as find_spec_original  # find_spec is new in py3.4

instrument_lists = {}


class ElasticMetaPathFinder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self._in_progress = {}

    def find_module(self, name, import_path):
        """
        Note: find_module is deprecated starting py3.4 (but is still used if
        the new find_spec is not found). We use it here so we don't have
        to worry about creating a whole spec, just a loader.
        """
        # Track that we're in the process of importing a module so that we
        # don't end up in an infinite loop when we actually import it
        if self._in_progress.get(name):
            return None
        self._in_progress[name] = True

        try:
            spec = find_spec_original(name)
            loader = getattr(spec, "loader", None)

            if loader:
                return ImportHookLoader(loader)

        finally:
            del self._in_progress[name]


class ImportHookLoader(object):
    """
    Small wrapper around a loader object we find with importlib.util.find_spec
    """

    def __init__(self, loader):
        self.loader = loader

    def load_module(self, name):
        module = self.loader.load_module(name)

        # Instrument the module
        _instrument(name)

        return module


def _instrument(name):
    global instrument_lists

    for cls in instrument_lists.get(name, []):
        # Because a single instrument() call normally handles a series of
        # entries in the instrument_list this could be called
        # extra times. Luckily it short-circuits quickly if it's a repeat call.
        from elasticapm.instrumentation import register

        obj = register.get_instrumentation_singleton(name, cls)
        if obj:
            obj.instrument()


def add_instrumentation(registration):
    """
    Takes an instrumentation object (inheriting from AbstractInstrumentedModule)
    and add to the list of instrumentations to apply when the module is imported.

    If the module is already imported, apply those instrumentations now and
    track that fact.

    TODO Ideally we would hold the global import lock here, but
    instrumentations can import things (the only way this would happen is if
    one piece of the instrumentation were already imported, but the other
    were not) and that would result in a deadlock. Eventually we would make
    the `instrument()` call more modular and targeted.
    """
    from elasticapm.instrumentation import register

    global instrument_lists
    module, cls = registration
    already_imported = set()

    if module in sys.modules:
        # Already imported, apply the instrumentation now
        already_imported.add(module)

        obj = register.get_instrumentation_singleton(module, cls)
        if obj:
            obj.instrument()
    else:
        instrument_lists.setdefault(module, [])
        instrument_lists[module].append(cls)


sys.meta_path.insert(0, ElasticMetaPathFinder())
