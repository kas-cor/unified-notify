"""Entry-point bridge for existing producers and the existing cron job."""
import importlib.util
import os
from pathlib import Path
import sys


def package():
    home = Path(os.environ.get('HERMES_HOME', str(Path.home()/'.hermes'))).expanduser()
    root = home.parent.parent if home.parent.name == 'profiles' else home
    checkout = root/'hermes-agent'
    if checkout.is_dir() and str(checkout) not in sys.path:
        sys.path.insert(0, str(checkout))
    name = '_unified_notify_compat'
    if name not in sys.modules:
        path = Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location(name, path/'__init__.py', submodule_search_locations=[str(path)])
        if spec is None or spec.loader is None:
            raise ImportError('unified-notify source unavailable')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def export(kind, namespace):
    import importlib
    module = importlib.import_module(package().__name__+'.'+kind)
    namespace.update({key: value for key, value in vars(module).items() if not key.startswith('__')})
    return module
