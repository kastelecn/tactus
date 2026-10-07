"""Optional components that can be plugged into extension points of a suite."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from ..logs import logger
from ..submission import TaskSettings
from .base import EcflowNode, EcflowSuiteTask


class ExtensionPoint(str, Enum):
    """Places in the suite where components can be added.

    Nodes added at an extension point are waited for by the nodes that follow
    it, unless noted otherwise.

    Attributes:
        STATIC_DATA: Where static data is produced, once for all members or
            per member. Components are triggered when the static data is
            available.
        INPUT_DATA: Where the input data of a cycle is prepared. Components are
            triggered when the cycle is prepared.
        PRE_FORECAST: Before the forecast of a member. Components are triggered
            when the forecast could start.
        FORECAST_ARCHIVING: Where the forecast output of a member is archived.
            Components are triggered when that output is available. Nothing
            waits for them within the forecast.
        POST_FORECAST: After the forecast of a member. Components are triggered
            when the forecast output is available.
        POST_CYCLE: After a member has completed the cycle, before its cycle
            files are cleaned. Components start when the post-cycle work starts.
        END_OF_CYCLE: After all members of a cycle. Components are triggered
            when every member has completed the cycle. Nothing waits for them.
        END_OF_SUITE: After all other work of the suite, before the final
            checks and cleaning. Components are triggered when that work is
            done.
    """

    STATIC_DATA = "static_data.end"
    INPUT_DATA = "input_data.end"
    PRE_FORECAST = "cycle.pre_forecast"
    FORECAST_ARCHIVING = "forecast.archiving"
    POST_FORECAST = "forecast.end"
    POST_CYCLE = "post_cycle.end"
    END_OF_CYCLE = "time.end_of_cycle"
    END_OF_SUITE = "suite.end"


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

        Returns:
            The node, or list of nodes, that later nodes should wait for, or
            None if they should not wait for the component.

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


def extend_trigger(trigger, added: list):
    """Return ``trigger`` extended with the nodes added by components.

    Args:
        trigger: Trigger to extend, a node, a list of nodes or None.
        added: Values returned by :func:`add_components`.

    Returns:
        ``trigger`` if no nodes were added, else a list of the trigger nodes
        followed by the added nodes.
    """
    nodes = []
    for value in added:
        values = value if isinstance(value, list) else [value]
        nodes.extend(node for node in values if isinstance(node, EcflowNode))
    if not nodes:
        return trigger
    if trigger is None:
        return nodes
    if isinstance(trigger, list):
        return [*trigger, *nodes]
    return [trigger, *nodes]
