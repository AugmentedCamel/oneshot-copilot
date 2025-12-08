import logging
from typing import Dict, Any, Type
from app.domain.interfaces import ModelPlugin
from app.domain.entities import Frame

logger = logging.getLogger(__name__)

class ModelRuntime:
    def __init__(self):
        self._plugins: Dict[str, ModelPlugin] = {}
        self._registry: Dict[str, Type[ModelPlugin]] = {}

    def register_plugin_class(self, name: str, plugin_cls: Type[ModelPlugin]):
        self._registry[name] = plugin_cls
        logger.info(f"Registered model plugin class: {name}")

    def load_model(self, instance_name: str, plugin_name: str, config: Dict[str, Any]):
        if plugin_name not in self._registry:
            raise ValueError(f"Unknown model plugin: {plugin_name}")
        
        plugin_cls = self._registry[plugin_name]
        plugin = plugin_cls()
        plugin.load(config)
        self._plugins[instance_name] = plugin
        logger.info(f"Loaded model instance: {instance_name} (type: {plugin_name})")

    async def run(self, instance_name: str, frame: Frame, context: Dict[str, Any]) -> Dict[str, Any]:
        if instance_name not in self._plugins:
            raise ValueError(f"Model instance not found: {instance_name}")
        
        plugin = self._plugins[instance_name]
        return await plugin.infer(frame, context)

# Global instance
model_runtime = ModelRuntime()
