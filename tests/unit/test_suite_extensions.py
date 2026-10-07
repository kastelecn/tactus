#!/usr/bin/env python3
"""Unit tests for ``tactus.suites.suite_extensions``."""

import os
from contextlib import suppress

import pytest

from tactus.derived_variables import set_times
from tactus.submission import TaskSettings
from tactus.suites import suite_extensions
from tactus.suites.base import EcflowNode
from tactus.suites.suite_extensions import (
    ComponentContext,
    ExtensionPoint,
    SuiteComponent,
    TaskComponent,
    add_components,
    extend_trigger,
    get_components,
    register_component,
)
from tactus.suites.tactus import TactusSuiteDefinition


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    """Let each test register components without affecting other tests."""
    monkeypatch.setattr(suite_extensions, "_components", {})


def _ctx(trigger=None):
    return ComponentContext(
        {}, task_settings=None, input_template="", ecf_files="", trigger=trigger
    )


class _Recorder(SuiteComponent):
    """Component recording its calls instead of adding nodes."""

    extension_point = ExtensionPoint.END_OF_CYCLE
    active = True
    calls = []

    def is_active(self, config):  # ruff:ignore[unused-method-argument]
        return self.active

    def add_nodes(self, parent, ctx):
        self.calls.append((self.name, parent, ctx.trigger))
        return self.name


class TestRegistry:
    def test_register_requires_name(self):
        class NoName(SuiteComponent):
            extension_point = ExtensionPoint.END_OF_CYCLE

        with pytest.raises(ValueError, match="must set name"):
            register_component(NoName)

    @pytest.mark.parametrize("extension_point", [None, "time.end_of_cylce"])
    def test_register_rejects_unknown_extension_point(self, extension_point):
        class BadPoint(SuiteComponent):
            name = "BadPoint"

        BadPoint.extension_point = extension_point
        with pytest.raises(ValueError, match="unknown extension_point"):
            register_component(BadPoint)

    def test_register_accepts_extension_point_value(self):
        @register_component
        class ByValue(_Recorder):
            name = "ByValue"
            extension_point = "time.end_of_cycle"

        assert [c.name for c in get_components(ExtensionPoint.END_OF_CYCLE)] == [
            "ByValue"
        ]

    def test_register_returns_class(self):
        class Comp(_Recorder):
            name = "Comp"

        assert register_component(Comp) is Comp
        assert [c.name for c in get_components(ExtensionPoint.END_OF_CYCLE)] == ["Comp"]

    def test_reregister_replaces(self):
        @register_component
        class First(_Recorder):
            name = "Same"

        @register_component
        class Second(_Recorder):
            name = "Same"

        components = get_components(ExtensionPoint.END_OF_CYCLE)
        assert len(components) == 1
        assert isinstance(components[0], Second)

    def test_no_components_registered(self):
        assert get_components(ExtensionPoint.FORECAST_ARCHIVING) == []


class TestAddComponents:
    def test_only_active_components_in_registration_order(self):
        _Recorder.calls = []

        @register_component
        class A(_Recorder):
            name = "A"

        @register_component
        class Inactive(_Recorder):
            name = "Inactive"
            active = False

        @register_component
        class B(_Recorder):
            name = "B"

        @register_component
        class OtherPoint(_Recorder):
            name = "OtherPoint"
            extension_point = ExtensionPoint.FORECAST_ARCHIVING

        added = add_components(ExtensionPoint.END_OF_CYCLE, "parent", _ctx("trig"))

        assert added == ["A", "B"]
        assert _Recorder.calls == [("A", "parent", "trig"), ("B", "parent", "trig")]

    def test_no_components(self):
        assert add_components(ExtensionPoint.END_OF_CYCLE, "parent", _ctx()) == []

    def test_base_add_nodes_not_implemented(self):
        with pytest.raises(NotImplementedError):
            SuiteComponent().add_nodes("parent", _ctx())


class _Node(EcflowNode):
    """Stand-in node, not added to any suite."""

    def __init__(self, name):
        self.name = name


class TestExtendTrigger:
    def test_nothing_added(self):
        trigger = _Node("t")
        assert extend_trigger(trigger, []) is trigger
        assert extend_trigger(trigger, [None, "not a node"]) is trigger

    def test_no_trigger(self):
        added = _Node("a")
        assert extend_trigger(None, [added]) == [added]

    def test_node_trigger(self):
        trigger, added = _Node("t"), _Node("a")
        assert extend_trigger(trigger, [added]) == [trigger, added]

    def test_list_trigger_and_list_added(self):
        trigger = [_Node("t")]
        added = [[_Node("a"), _Node("b")], None, _Node("c")]
        result = extend_trigger(trigger, added)
        assert [n.name for n in result] == ["t", "a", "b", "c"]
        assert [n.name for n in trigger] == ["t"]


@pytest.fixture
def _no_parse_job_errors(monkeypatch):
    original = TaskSettings.parse_job

    def parse_job(self, **kwargs):
        with suppress(RuntimeError):
            original(self, **kwargs)

    monkeypatch.setattr(TaskSettings, "parse_job", parse_job)


@pytest.mark.usefixtures("_no_parse_job_errors")
def test_components_in_suite(default_config, tmp_directory, monkeypatch):
    """Registered task components are added at their extension points."""
    created = []
    original_add_nodes = TaskComponent.add_nodes

    def add_nodes(self, parent, ctx):
        trigger = ctx.trigger if isinstance(ctx.trigger, list) else [ctx.trigger]
        created.append((
            self.extension_point,
            parent.name,
            sorted(n.name for n in trigger if n is not None),
        ))
        return original_add_nodes(self, parent, ctx)

    monkeypatch.setattr(TaskComponent, "add_nodes", add_nodes)

    triggers = {}
    original_node_init = EcflowNode.__init__

    def node_init(self, name, *args, trigger=None, **kwargs):
        nodes = trigger if isinstance(trigger, list) else [trigger]
        triggers.setdefault(name, []).append({
            n.name for n in nodes if isinstance(n, EcflowNode)
        })
        original_node_init(self, name, *args, trigger=trigger, **kwargs)

    monkeypatch.setattr(EcflowNode, "__init__", node_init)

    for point in ExtensionPoint:
        register_component(
            type(
                f"{point.name}Task",
                (TaskComponent,),
                {"name": f"{point.name}Task", "extension_point": point},
            )
        )

    @register_component
    class InactiveTask(TaskComponent):
        name = "InactiveTask"
        extension_point = ExtensionPoint.FORECAST_ARCHIVING

        def is_active(self, config):  # ruff:ignore[unused-method-argument]
            return False

    config = default_config.copy(
        update={
            "general": {
                "case": "test_suite",
                "times": {
                    "start": "2022-05-02T00:00:00Z",
                    "end": "2022-05-02T03:00:00Z",
                },
            },
            "scheduler": {
                "ecfvars": {
                    "ecf_files": f"{tmp_directory}/ecf_files",
                    "ecf_jobout": f"{tmp_directory}/jobout",
                }
            },
            "platform": {
                "tactus_home": f"{os.path.dirname(__file__)}/../..",
                "unix_group": "",
            },
            "eps": {"general": {"members": [0, 1]}},
        }
    )
    config = config.copy(update=set_times(config))
    TactusSuiteDefinition(config, dry_run=True)

    def placed(point):
        return [(parent, trigger) for p, parent, trigger in created if p == point]

    # Two cycles with two members each
    assert placed(ExtensionPoint.STATIC_DATA) == [
        ("StaticData", ["E923Monthly", "PgdUpdate"])
    ]
    assert placed(ExtensionPoint.INPUT_DATA) == [("InputData", ["PrepareCycle"])] * 2
    assert (
        placed(ExtensionPoint.PRE_FORECAST)
        == [("Cycle", ["Interpolation"])] * 2
        + [("Cycle", ["Cycle", "Interpolation"])] * 2
    )
    for point in (ExtensionPoint.FORECAST_ARCHIVING, ExtensionPoint.POST_FORECAST):
        assert placed(point) == [("Forecasting", ["AddCalculatedFieldsTasks"])] * 4
    assert placed(ExtensionPoint.POST_CYCLE) == [("PostCycle", [])] * 4
    assert placed(ExtensionPoint.END_OF_CYCLE) == [
        ("0000", ["Cycle", "Cycle"]),
        ("0300", ["Cycle", "Cycle"]),
    ]
    assert placed(ExtensionPoint.END_OF_SUITE) == [
        ("test_suite", ["0300", "CollectLogsStatic", "PrepRun"])
    ]
    assert "InactiveTask" not in triggers

    # The nodes following an extension point wait for its components
    assert all("PRE_FORECASTTask" in t for t in triggers["Forecasting"])
    for name in ("CycleCleaning", "CollectLogsHour"):
        assert all("POST_CYCLETask" in t for t in triggers[name])
    assert all("END_OF_SUITETask" in t for t in triggers["PostMortem"])
