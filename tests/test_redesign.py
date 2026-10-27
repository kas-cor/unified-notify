from pathlib import Path
import settings


def test_internal_storage_and_native_identity_not_user_settings():
    hidden = {'root_home', 'db_path', 'action_category', 'delivery_namespace', 'runtime_path', 'transport_profile', 'bot_id', 'bot_username', 'token_env'}
    assert not (hidden & settings.DEFAULTS.keys())
    cfg = settings.validate({'channel_id': 42, 'owner_user_id': 42, 'db_path': '/tmp/other'})
    assert cfg['db_path'] == Path.home() / '.hermes/data/unified-notify.sqlite3'
    assert cfg['action_category'] == 'needs_owner'


def test_transport_discovery_uses_enabled_installation(tmp_path=None):
    import tempfile
    import onboard
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
        root = Path(tmp)
        for name in ("alpha", "beta"):
            home = root / "profiles" / name
            (home / "plugins/unified-notify").mkdir(parents=True)
            (home / "config.yaml").write_text("{}")
        def config(home):
            return {"plugins": {"enabled": ["unified-notify"] if home.name == "beta" else []}}
        plan = onboard.profiles_plan(root, config)
        assert [x["name"] for x in plan if x["native_plugin"]] == ["beta"]


def test_plugin_registers_in_actual_profile_without_named_transport():
    import importlib.util, sys
    from types import SimpleNamespace
    project = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("redesign_plugin", project / "__init__.py", submodule_search_locations=[str(project)])
    plugin = importlib.util.module_from_spec(spec); sys.modules[spec.name] = plugin; spec.loader.exec_module(plugin)
    handlers = []
    values = {"channel_id": -123, "owner_user_id": 42}
    ctx = SimpleNamespace(profile_name="beta", get_config=lambda k, d: values.get(k, d), register_platform_handler=lambda *args: handlers.append(args))
    plugin.register(ctx)
    assert len(handlers) == 1


def test_sender_requires_enabled_plugin_in_current_profile():
    import sender, tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
        root = Path(tmp); home = root / "profiles/beta"
        (home / "plugins/unified-notify").mkdir(parents=True)
        (home / "config.yaml").write_text("{}")
        cfg = settings.validate({"channel_id": 42, "owner_user_id": 42})
        cfg["root_home"] = root
        with patch.object(sender.settings, "load", return_value=cfg), patch("hermes_constants.get_hermes_home", return_value=home), patch("onboard.config_for", return_value={"plugins": {"enabled": []}}):
            try: sender.main()
            except PermissionError: pass
            else: assert False, "disabled plugin must not send"


import unittest

class RedesignTests(unittest.TestCase):
    def test_internal_settings(self): test_internal_storage_and_native_identity_not_user_settings()
    def test_discovery(self): test_transport_discovery_uses_enabled_installation()
    def test_plugin_profile(self): test_plugin_registers_in_actual_profile_without_named_transport()
    def test_sender_disabled(self): test_sender_requires_enabled_plugin_in_current_profile()
    def test_database_path_cannot_be_selected_on_cli(self):
        import store
        from unittest.mock import patch
        with patch.object(store, 'database') as database, self.assertRaises(SystemExit):
            store.main(['--db', '/not-allowed', 'status'])
        database.assert_not_called()


def test_sender_runs_only_in_discovered_profile():
    import sender, tempfile
    from unittest.mock import patch
    with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
        root = Path(tmp) / ".hermes"; home = root / "profiles/beta"
        (home / "plugins/unified-notify").mkdir(parents=True)
        (home / "config.yaml").write_text("{}")
        with patch.dict("os.environ", {"HOME": tmp}), patch.object(sender.settings, "load", return_value=settings.validate({"channel_id": 42, "owner_user_id": 42})), patch("hermes_constants.get_hermes_home", return_value=home), patch("onboard.config_for", return_value={"plugins": {"enabled": ["unified-notify"]}}), patch.object(sender, "load_bot_token", return_value="test"), patch.object(sender, "send_pending", return_value={"claimed":0,"unknown":0,"failed":0}) as send, patch("dispatcher.dispatch_replies", return_value={"failed":0}):
            assert sender.main() == 0
            assert send.call_args.args[0] == root / "data/unified-notify.sqlite3"

RedesignTests.test_sender_enabled = lambda self: test_sender_runs_only_in_discovered_profile()
