"""Safety rules that must never regress: secret redaction and destructive-command guards."""

from app.ai.agent import DESTRUCTIVE, _guard_commands
from app.kubernetes.kubectl import redact
from app.models.diagnosis import Issue


def test_redacts_passwords_and_tokens():
    assert redact("mysql -u admin -pS3cret! -e 'x'") == "mysql -u admin -p*** -e 'x'"
    assert redact("mysql --password=abc123") == "mysql --password=***"
    assert redact("DB_PASSWORD=hunter2 run") == "DB_PASSWORD=*** run"
    assert redact("API_KEY=abc") == "API_KEY=***"
    assert "eyJ" not in redact("Authorization: Bearer eyJabc.def")


def test_keeps_useful_mysql_hint():
    line = "Access denied for user 'a'@'h' (using password: YES)"
    assert redact(line) == line


def test_destructive_commands_detected():
    for cmd in ["kubectl delete service x -n a", "kubectl delete svc x", "kubectl delete -n a pvc data", "kubectl delete ns prod"]:
        assert DESTRUCTIVE.search(cmd), cmd
    for cmd in ["kubectl delete pod p -n a", "kubectl delete job j -n a", "kubectl rollout undo deployment/x"]:
        assert not DESTRUCTIVE.search(cmd), cmd


def test_guard_replaces_destructive_with_verified_hint():
    inv = {"resources": {"findings": {"networking": [{"kind": "Service", "name": "lb1", "hint": "kubectl get events -n a"}]}}}
    issue = Issue(root_cause="x", affected=["a/service/lb1"], fix="1. kubectl delete service lb1 -n a",
                  kubectl_commands=["kubectl delete service lb1 -n a"])
    _guard_commands(issue, inv)
    assert issue.kubectl_commands == ["kubectl get events -n a"]
