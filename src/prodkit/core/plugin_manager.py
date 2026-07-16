"""Plugin collection, validation, and dependency-ordered activation."""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter

from prodkit.contracts.plugin import Plugin
from prodkit.core.exceptions import PluginDependencyError, PluginError


class PluginManager:
    """Validates plugins and produces a deterministic activation order via
    topological sort of their ``requires`` declarations."""

    def __init__(self, plugins: list[Plugin]) -> None:
        self._validate(plugins)
        self.plugins = self._sort(plugins)

    @staticmethod
    def _validate(plugins: list[Plugin]) -> None:
        seen: set[str] = set()
        for plugin in plugins:
            if not isinstance(plugin, Plugin):
                raise PluginError(f"{plugin!r} does not implement the ProdKit Plugin contract")
            if not plugin.name:
                raise PluginError(f"{type(plugin).__name__} has no 'name' set")
            if plugin.name in seen:
                raise PluginError(f"Duplicate plugin name: {plugin.name!r}")
            seen.add(plugin.name)

    @staticmethod
    def _sort(plugins: list[Plugin]) -> list[Plugin]:
        by_name = {plugin.name: plugin for plugin in plugins}
        graph: dict[str, set[str]] = {}
        for plugin in plugins:
            missing = [dep for dep in plugin.requires if dep not in by_name]
            if missing:
                raise PluginDependencyError(
                    f"Plugin {plugin.name!r} requires missing plugin(s): "
                    + ", ".join(repr(m) for m in missing)
                )
            graph[plugin.name] = set(plugin.requires)

        # static_order is deterministic for a fixed insertion order, which we
        # have (built-ins first, then user plugins in the order given).
        try:
            order = list(TopologicalSorter(graph).static_order())
        except CycleError as exc:
            raise PluginDependencyError(
                f"Plugin dependency cycle detected: {exc.args[1]}"
            ) from exc
        return [by_name[name] for name in order]
