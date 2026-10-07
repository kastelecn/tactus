# Plug-ins
Tactus has the capability to add plug-ins. Internally tactus itself is also treated as a plug-in, which is always enabled.

## Plugin capablilities
In tactus suites and tasks are handled as plugins. The namespaces suites and tasks are searched for possible suites and tasks.

## Running your own suite
The configuration setting below allows you to use an alternative suite defintion.

```
[general.suite_control]
suite_definition = "MySuite"
```

This should pick up the suite definition MySuite if it's implementing the SuiteDefinition class from tactus.

## Enable your own plug-in
The config file has a plugin_registry key inside the general part. The loaded plug-ins are defined inside the `plugins` key in the registry. The loaded plugins are stored as a dictionary, which uses namespaces as keys and paths as values.

An example could be to add the plugin with namespace "example" in location /tmp would be to add:

```
[general.plugin_registry.plugins]
"example": "/tmp"
```

In this case it is expected that the namespace "example" is located in `/tmp/example`. Suites in `/tmp/example/suites` and tasks in `/tmp/example/`tasks will be picked up.

## Add optional components to the tactus suite
Instead of writing a whole suite, a plug-in can add tasks or families to the tactus suite at extension points. A component is a class registered with `register_component` from `tactus.suites.suite_extensions`. It is added at its extension point if its `is_active(config)` returns True.

The extension points are listed in `ExtensionPoint`:

| Extension point | Where | Trigger given to the component |
|---|---|---|
| `ExtensionPoint.FORECAST_ARCHIVING` | Forecast family, after ArchiveFDB | The node archiving tasks should trigger on |
| `ExtensionPoint.END_OF_CYCLE` | Time family of each cycle, after all members | The Cycle families of all members |

For a single task, subclass `TaskComponent`; the task gets the trigger of the extension point:

```python
from tactus.suites.suite_extensions import ExtensionPoint, TaskComponent, register_component


@register_component
class MyTaskComponent(TaskComponent):
    name = "MyTask"  # Name of the task
    extension_point = ExtensionPoint.END_OF_CYCLE

    def is_active(self, config):
        return config.get("my_section.active", False)
```

For anything else, subclass `SuiteComponent` and implement `add_nodes(parent, ctx)`, where `ctx` holds the config, task settings, templates and trigger.

Put the component in a module of the plug-in's `suites` package: those modules are imported when tactus discovers suites, which registers the component. Registering a component with an unknown extension point raises a `ValueError`.

A new extension point is added by adding it to `ExtensionPoint` and calling `add_components(ExtensionPoint.<NAME>, <parent node>, ComponentContext(...))` in the suite family where the components should be inserted.
