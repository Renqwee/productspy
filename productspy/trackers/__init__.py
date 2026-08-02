import pkgutil
from importlib import import_module

for _module in pkgutil.iter_modules(__path__):
    import_module(f"{__name__}.{_module.name}")