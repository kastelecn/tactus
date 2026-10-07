"""Optional components that can be plugged into extension points of a suite.

Suite families call :func:`add_components` at the extension points listed in
:class:`ExtensionPoint`. Every component registered for that extension point,
whose ``is_active(config)`` returns True, then adds its nodes to the suite.

Components are registered with the :func:`register_component` class decorator,
typically by a plugin in a module of its ``suites`` package, which tactus
imports when discovering suites.

Example:
    A plugin adding a task after all members of each cycle::

        from tactus.suites.suite_extensions import (
            ExtensionPoint,
            TaskComponent,
            register_component,
        )

        @register_component
        class MyTaskComponent(TaskComponent):
            name = "MyTask"
            extension_point = ExtensionPoint.END_OF_CYCLE

            def is_active(self, config):
                return config.get("my_section.active", False)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from ..logs import logger
from ..submission import TaskSettings
from .base import EcflowNode, EcflowSuiteTask


class ExtensionPoint(str, Enum):
    """Places in the suite where components can be added.

    Attributes:
        FORECAST_ARCHIVING: In the Forecast family, after ArchiveFDB. The trigger
            is the node the archiving tasks should trigger on.
        END_OF_CYCLE: In the time family of each cycle, after all members have
            been added. The trigger is the list of member Cycle families.
    """

    FORECAST_ARCHIVING = "forecast.archiving"
    END_OF_CYCLE = "time.end_of_cycle"


@dataclass
class ComponentContext:
    """What a component needs to add its nodes at an extension point."""

    config: Any
    task_settings: TaskSettings
    input_template: str
    ecf_files: str
    trigger: Any = None
    ecf_files_remotely: Optional[str] = None


class SuiteComponent:
    """Base class for optional suite components.

    Subclasses set ``name`` and ``extension_point`` and implement ``add_nodes``.
    """

    name: str = ""
    extension_point: Optional[ExtensionPoint] = None

    def is_active(self, config) -> bool:  # ruff:ignore[unused-method-argument]
        """Return whether the component should be added for this config.

        Args:
            config: Experiment config.
        """
        return True

    def add_nodes(self, parent: EcflowNode, ctx: ComponentContext):
        """Add the nodes of the component to ``parent``.

        Args:
            parent: Node to add the component nodes to.
            ctx: Context of the extension point.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError


class TaskComponent(SuiteComponent):
    """Component adding a single task named ``name``.

    The task is triggered on the trigger of the extension point.
    """

    def add_nodes(self, parent: EcflowNode, ctx: ComponentContext):
        """Add the task to ``parent``.

        Args:
            parent: Node to add the task to.
            ctx: Context of the extension point.

        Returns:
            EcflowSuiteTask: The added task.
        """
        return EcflowSuiteTask(
            self.name,
            parent,
            ctx.config,
            ctx.task_settings,
            ctx.ecf_files,
            input_template=ctx.input_template,
            trigger=ctx.trigger,
            ecf_files_remotely=ctx.ecf_files_remotely,
        )


_components: Dict[ExtensionPoint, Dict[str, SuiteComponent]] = {}


def register_component(cls):
    """Class decorator registering a suite component.

    Registering a component with the same name and extension point again
    replaces the earlier one.

    Args:
        cls (type): SuiteComponent subclass to register.

    Returns:
        type: The unchanged class.

    Raises:
        ValueError: If name is not set, or extension_point is not an
            ExtensionPoint.
    """
    component = cls()
    if not component.name:
        raise ValueError(f"{cls.__name__} must set name")
    try:
        extension_point = ExtensionPoint(component.extension_point)
    except ValueError as error:
        known = ", ".join(point.name for point in ExtensionPoint)
        raise ValueError(
            f"{cls.__name__} has unknown extension_point "
            f"{component.extension_point!r}, use one of ExtensionPoint: {known}"
        ) from error
    _components.setdefault(extension_point, {})[component.name] = component
    return cls


def get_components(extension_point: ExtensionPoint) -> List[SuiteComponent]:
    """Return the components registered for an extension point.

    Args:
        extension_point: The extension point.

    Returns:
        List of components, in registration order.
    """
    return list(_components.get(ExtensionPoint(extension_point), {}).values())


def add_components(
    extension_point: ExtensionPoint, parent: EcflowNode, ctx: ComponentContext
):
    """Add the active components of an extension point to ``parent``.

    Args:
        extension_point: The extension point.
        parent: Node to add the component nodes to.
        ctx: Context of the extension point.

    Returns:
        list: The values returned by ``add_nodes`` of the added components.
    """
    added = []
    for component in get_components(extension_point):
        if component.is_active(ctx.config):
            logger.debug(
                "Adding suite component {} at {}",
                component.name,
                ExtensionPoint(extension_point).value,
            )
            added.append(component.add_nodes(parent, ctx))
    return added
