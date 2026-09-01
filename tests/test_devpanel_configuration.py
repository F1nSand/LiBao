from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest


DEV_PANEL = Path(__file__).parents[1] / "tools" / "devpanel" / "main.py"


def _load_devpanel(monkeypatch, **values):
    for name in ("LIBAO_BACKEND_PORT", "LIBAO_FRONTEND_PORT", "LIBAO_DEVPANEL_PORT"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, str(value))
    module_name = f"libao_devpanel_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, DEV_PANEL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_devpanel_defaults_to_loopback_real_backend(monkeypatch):
    module = _load_devpanel(monkeypatch)

    backend = module.ServiceManager().services["backend"]
    frontend = module.ServiceManager().services["frontend"]

    assert module.BE_PORT == 8000
    assert module.FE_PORT == 5173
    assert module.PANEL_PORT_DEFAULT == 9100
    assert backend.cmd[-4:] == ["--host", "127.0.0.1", "--port", "8000"]
    assert frontend.cmd[-5:-1] == ["--host", "127.0.0.1", "--port", "5173"]
    assert frontend.extra_env == {"VITE_USE_MOCK": "false", "VITE_API_PROXY": "http://127.0.0.1:8000"}


def test_devpanel_custom_ports_are_consistent(monkeypatch):
    module = _load_devpanel(
        monkeypatch,
        LIBAO_BACKEND_PORT=18000,
        LIBAO_FRONTEND_PORT=15173,
        LIBAO_DEVPANEL_PORT=19100,
    )
    manager = module.ServiceManager()
    backend = manager.services["backend"]
    frontend = manager.services["frontend"]

    assert (module.BE_PORT, module.FE_PORT, module.PANEL_PORT_DEFAULT) == (18000, 15173, 19100)
    assert "18000" in backend.health_url and backend.cmd[-1] == "18000"
    assert "15173" in frontend.health_url and frontend.cmd[-2] == "15173"
    assert frontend.extra_env["VITE_API_PROXY"] == "http://127.0.0.1:18000"


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_devpanel_rejects_invalid_port_values(monkeypatch, value):
    with pytest.raises(ValueError, match="LIBAO_BACKEND_PORT"):
        _load_devpanel(monkeypatch, LIBAO_BACKEND_PORT=value)
