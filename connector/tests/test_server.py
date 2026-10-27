"""The tools Claude sees: product tools always, diagnostics only when the build enables them."""

import json
import os
import subprocess
import sys

PRODUCT = {"sign_in_start", "sign_in_status", "whoami", "sign_out", "workspace_clone", "workspace_list",
           "workspace_status", "workspace_update", "version_create", "version_save", "version_send", "version_to_test",
           "version_propose", "specialist_settings", "dependency_check", "dependency_audit"}
DIAGNOSTICS = {"diag_environment", "diag_reach", "diag_hook_log"}

# A fresh process per case: the diagnostic tools are registered when the server module is imported.
_LIST = ("import asyncio, json\nfrom eunomai_business import server\n"
         "print(json.dumps([t.name for t in asyncio.run(server.mcp.list_tools())]))")


def _tools(diagnostics: str) -> set[str]:
    env = dict(os.environ, EUNOMAI_DIAGNOSTICS=diagnostics)
    out = subprocess.run([sys.executable, "-c", _LIST], env=env, capture_output=True, text=True, check=True)
    return set(json.loads(out.stdout))


def test_product_tools_only_by_default():
    assert _tools("0") == PRODUCT


def test_diagnostics_add_their_tools():
    assert _tools("1") == PRODUCT | DIAGNOSTICS

