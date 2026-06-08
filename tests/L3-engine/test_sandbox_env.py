"""Tests for sandbox_env() and sandboxed action subprocess execution."""

import os
import pytest
from husks.engine import sandbox_env, build, rule, action, _make_shell_action


class TestSandboxEnvStripsNetworkVars:
    """sandbox_env strips proxy and network configuration vars."""

    def test_proxy_vars_absent(self, monkeypatch):
        proxy_vars = [
            "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
            "ALL_PROXY", "all_proxy", "no_proxy", "NO_PROXY",
            "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE",
            "NODE_EXTRA_CA_CERTS",
        ]
        for var in proxy_vars:
            monkeypatch.setenv(var, "should-be-stripped")
        env = sandbox_env()
        for var in proxy_vars:
            assert var not in env, f"{var} should be stripped"


class TestSandboxEnvSetsMarkers:
    """sandbox_env sets HUSKS_SANDBOX and SOURCE_DATE_EPOCH."""

    def test_markers_present(self):
        env = sandbox_env()
        assert env["HUSKS_SANDBOX"] == "1"
        assert env["SOURCE_DATE_EPOCH"] == "0"


class TestSandboxEnvPreservesEssentialVars:
    """sandbox_env preserves PATH, HOME, and other essential vars."""

    def test_path_and_home_preserved(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin:/bin")
        monkeypatch.setenv("HOME", "/home/test")
        env = sandbox_env()
        assert env["PATH"] == "/usr/bin:/bin"
        assert env["HOME"] == "/home/test"


class TestActionUsesSandboxEnv:
    """Shell action with S['sandbox']=True sees HUSKS_SANDBOX in env."""

    def test_sandbox_marker_visible(self, tmp_path):
        out = str(tmp_path / "out.txt")
        S = build(
            "sandbox-test", 4,
            rule("check-env",
                 outputs=["out.txt"],
                 run="echo $HUSKS_SANDBOX > out.txt"),
            site=str(tmp_path),
            sandbox=True,
        )
        assert S["status"] == "committed"
        content = (tmp_path / "out.txt").read_text().strip()
        assert content == "1"


class TestActionInheritsNormalEnvWithoutSandbox:
    """Without sandbox key, subprocess env is inherited normally."""

    def test_no_sandbox_marker(self, tmp_path):
        S = build(
            "no-sandbox-test", 4,
            rule("check-env",
                 outputs=["out.txt"],
                 run="echo ${HUSKS_SANDBOX:-unset} > out.txt"),
            site=str(tmp_path),
        )
        assert S["status"] == "committed"
        content = (tmp_path / "out.txt").read_text().strip()
        assert content == "unset"
