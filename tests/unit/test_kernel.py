"""Unit tests for the plugin manager, registry, and event bus."""

from __future__ import annotations

import pytest

from prodkit.contracts.plugin import Plugin
from prodkit.core.event_bus import EventBus
from prodkit.core.exceptions import (
    PluginDependencyError,
    PluginError,
    ProdKitError,
    ServiceNotFoundError,
)
from prodkit.core.plugin_manager import PluginManager
from prodkit.core.registry import Registry


def make_plugin(plugin_name: str, deps: tuple[str, ...] = ()) -> Plugin:
    return type(f"P_{plugin_name}", (Plugin,), {"name": plugin_name, "requires": deps})()


class TestPluginManager:
    def test_dependency_order(self):
        manager = PluginManager(
            [make_plugin("c", deps=("b",)), make_plugin("b", deps=("a",)), make_plugin("a")]
        )
        names = [p.name for p in manager.plugins]
        assert names.index("a") < names.index("b") < names.index("c")

    def test_missing_dependency_fails_at_boot(self):
        with pytest.raises(PluginDependencyError, match="requires missing plugin"):
            PluginManager([make_plugin("a", deps=("nonexistent",))])

    def test_cycle_detected(self):
        with pytest.raises(PluginDependencyError, match="cycle"):
            PluginManager([make_plugin("a", deps=("b",)), make_plugin("b", deps=("a",))])

    def test_duplicate_names_rejected(self):
        with pytest.raises(PluginError, match="Duplicate plugin name"):
            PluginManager([make_plugin("a"), make_plugin("a")])

    def test_unnamed_plugin_rejected(self):
        class Nameless(Plugin):
            pass

        with pytest.raises(PluginError, match="no 'name'"):
            PluginManager([Nameless()])

    def test_non_plugin_rejected(self):
        with pytest.raises(PluginError, match="does not implement"):
            PluginManager([object()])  # type: ignore[list-item]


class TestRegistry:
    def test_provide_and_get(self):
        registry = Registry()
        registry.provide("cache", {"backend": "memory"})
        assert registry.get("cache") == {"backend": "memory"}
        assert registry.has("cache")
        assert registry.names() == ["cache"]

    def test_duplicate_name_is_error(self):
        registry = Registry()
        registry.provide("cache", 1)
        with pytest.raises(ProdKitError, match="already registered"):
            registry.provide("cache", 2)

    def test_missing_service_lists_available(self):
        registry = Registry()
        registry.provide("logger", 1)
        with pytest.raises(ServiceNotFoundError, match="available: logger"):
            registry.get("cache")


class TestEventBus:
    def test_emit_calls_handlers_with_payload(self):
        bus = EventBus()
        received = []
        bus.subscribe("request.completed", lambda **kw: received.append(kw))
        bus.emit("request.completed", status=200)
        assert received == [{"status": 200}]

    def test_failing_handler_does_not_break_others(self):
        bus = EventBus()
        received = []

        def bad(**kw):
            raise RuntimeError("boom")

        bus.subscribe("event", bad)
        bus.subscribe("event", lambda **kw: received.append(kw))
        bus.emit("event", x=1)
        assert received == [{"x": 1}]

    def test_async_handler_rejected_in_sync_emit(self):
        bus = EventBus()

        async def handler(**kw):
            pass

        bus.subscribe("event", handler)
        with pytest.raises(TypeError, match="use emit_async"):
            bus.emit("event")

    @pytest.mark.anyio
    async def test_emit_async_awaits_handlers(self):
        bus = EventBus()
        received = []

        async def handler(**kw):
            received.append(kw)

        bus.subscribe("event", handler)
        await bus.emit_async("event", y=2)
        assert received == [{"y": 2}]
