"""Fixes computed from cluster data instead of trusting the model."""

from app.ai.agent import _corrected_image, _prefer_in_place, _prefer_selector_fix
from app.kubernetes.network_inspector import _suggest_selector
from app.kubernetes.resources import _qty
from app.models.diagnosis import Issue


def test_corrected_image_keeps_registry_port_and_drops_digest():
    blank = Issue(root_cause="x")
    assert _corrected_image(blank, "nginx:14") == "nginx:latest"
    assert _corrected_image(blank, "registry.local:5000/team/app:1.2") == "registry.local:5000/team/app:latest"
    assert _corrected_image(blank, "repo/app@sha256:abc") == "repo/app:latest"


def test_corrected_image_uses_model_suggestion():
    issue = Issue(root_cause="x", kubectl_commands=["kubectl run p --image=nginx:1.25 -n ns"])
    assert _corrected_image(issue, "nginx:14") == "nginx:1.25"


def test_image_pull_fixed_in_place_without_delete():
    inv = {
        "pods": {"problematic_pods": [{"name": "web-1", "namespace": "ns", "status": "ImagePullBackOff", "fix_target": "deployment/web"}]},
        "pod_details": {"ns/web-1": {"containers": [{"name": "app", "image": "nginx:14"}]}},
    }
    issue = Issue(root_cause="bad tag", title="web-1: image pull failure", affected=["ns/pod/web-1"],
                  kubectl_commands=["kubectl delete pod web-1 -n ns", "kubectl run web-1 --image=nginx:1.27 -n ns"])
    _prefer_in_place(issue, inv)
    assert issue.kubectl_commands[0] == "kubectl set image deployment/web app=nginx:1.27 -n ns"
    assert not any("delete" in c for c in issue.kubectl_commands)


def test_selector_suggestion_only_when_unambiguous():
    pods = [("api-7d9-x", {"app": "api"}), ("web-5c-y", {"app": "web-frontend"})]
    assert _suggest_selector("api", {"app": "api-server"}, pods) == {"app": "api"}
    two = [("web-1-a", {"app": "web"}), ("web-2-b", {"app": "web2"})]
    assert _suggest_selector("web", {"app": "x"}, two) is None


def test_selector_fix_overrides_model_guess():
    net = {"issues": [{"service": "api", "namespace": "ns", "suggested_selector": {"app": "api"},
                       "hint": "kubectl patch service api -n ns -p '{\"spec\": {\"selector\": {\"app\": \"api\"}}}'"}]}
    issue = Issue(root_cause="x", title="service api: selector mismatch", kubectl_commands=["kubectl patch ... web-frontend"])
    _prefer_selector_fix(issue, {"network": net})
    assert "web-frontend" not in issue.kubectl_commands[0]
    assert '"app": "api"' in issue.kubectl_commands[0]


def test_quantities():
    assert _qty("100m") == 0.1
    assert _qty("2Gi") == 2 * 2**30
    assert _qty("5") == 5
