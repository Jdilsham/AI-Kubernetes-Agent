"""The AI agent's kubectl guard and its investigation loop (with a fake Claude client)."""

from types import SimpleNamespace

import pytest

from app.ai import agent_tools, claude_agent
from app.ai.agent_tools import CommandRejected, validate
from app.ai.llm_client import LLMError


@pytest.mark.parametrize(
    "command",
    [
        "get pods -A",
        "kubectl describe pod web-1 -n shop",
        "logs web-1 -n shop --previous",
        "top nodes",
        "get events -n shop --sort-by=.lastTimestamp",
        "get pods -o jsonpath='{.items[*].metadata.name}'",
        "auth can-i get pods",
        "rollout status deployment/web -n shop",
        "get secrets -n shop",
        "describe secret db -n shop",
    ],
)
def test_read_only_commands_allowed(command):
    assert validate(command, None)


@pytest.mark.parametrize(
    "command",
    [
        "delete pod web-1",
        "apply -f x.yaml",
        "exec -it web-1 -- sh",
        "patch deployment web -p '{}'",
        "scale deployment web --replicas=0",
        "rollout restart deployment web",
        "auth reconcile",
        "config view",
        "port-forward svc/web 8080:80",
        "get pods -w",
        "logs web-1 -f",
        "get pods --kubeconfig /etc/other",
        "get pods --context prod",
        "get pods --as admin",
        "get --raw /api",
        "get pods | grep Crash",
        "get pods; delete pod x",
        "get pods $(whoami)",
        "get secret db -o yaml",
        "get secrets,pods -o jsonpath='{.items[*].data}'",
        "",
        "-n shop get pods",
    ],
)
def test_unsafe_commands_rejected(command):
    with pytest.raises(CommandRejected):
        validate(command, None)


def test_logs_get_a_default_tail_and_rollout_status_does_not_wait():
    assert "--tail=200" in validate("logs web-1 -n shop", None)
    assert "--tail=50" in validate("logs web-1 --tail=50", None) and "--tail=200" not in validate("logs web-1 --tail=50", None)
    assert "--watch=false" in validate("rollout status deployment/web", None)


def test_namespace_scope_is_enforced():
    assert validate("get pods", "shop")[-2:] == ["-n", "shop"]
    assert validate("get pods -n shop", "shop").count("-n") == 1
    assert validate("get pods --namespace=shop", "shop")[-2:] == ["-n", "shop"]
    for command in ("get pods -A", "get pods --all-namespaces", "get pods -n other", "get pods --namespace other"):
        with pytest.raises(CommandRejected):
            validate(command, "shop")


def test_run_command_truncates_and_redacts(monkeypatch):
    big = "DB_PASSWORD=hunter2\n" + "x" * (agent_tools.MAX_OUTPUT_CHARS + 500)
    monkeypatch.setattr(agent_tools, "run_kubectl", lambda args, timeout: {"success": True, "stdout": big, "stderr": "", "returncode": 0})
    text, is_error = agent_tools.run_command("get cm app -o yaml")
    assert not is_error and "hunter2" not in text and "truncated" in text


def test_run_command_reports_rejection_and_failure(monkeypatch):
    text, is_error = agent_tools.run_command("delete pod x")
    assert is_error and "not allowed" in text
    monkeypatch.setattr(agent_tools, "run_kubectl", lambda args, timeout: {"success": False, "stdout": "", "stderr": "pods not found", "returncode": 1})
    text, is_error = agent_tools.run_command("get pods")
    assert is_error and "pods not found" in text


# ---------------------------------------------------------------- the loop


def _tool_use(name, input_, id_="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=input_, id=id_)


def _reply(*blocks, stop="tool_use"):
    usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=usage)


class FakeClaude:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # snapshot: the loop keeps appending
        return self.replies.pop(0)


INVESTIGATION = {"pods": {}, "logs": {}, "events": {}, "deployments": {}, "network": {}, "nodes": {}, "resources": {}}
DIAGNOSIS = {"summary": "one pod down", "issues": [{"title": "x", "root_cause": "oom", "severity": "critical"}]}


@pytest.fixture
def settings(monkeypatch):
    s = SimpleNamespace(anthropic_api_key="k", anthropic_model="claude-sonnet-5-5", agent_max_steps=2, agent_effort="medium",
                        agent_timeout_seconds=60, allowed_namespace="")
    monkeypatch.setattr(claude_agent, "get_settings", lambda: s)
    return s


def _install(monkeypatch, fake, ran):
    monkeypatch.setattr(claude_agent.anthropic, "Anthropic", lambda **kw: fake)
    monkeypatch.setattr(claude_agent, "run_command", lambda cmd: (ran.append(cmd) or "output", False))


def test_agent_runs_commands_then_submits(monkeypatch, settings):
    fake = FakeClaude([
        _reply(_tool_use("kubectl", {"command": "describe pod web-1"})),
        _reply(_tool_use("kubectl", {"command": "logs web-1 --previous"})),
        _reply(_tool_use("submit_diagnosis", DIAGNOSIS)),
    ])
    ran, steps = [], []
    _install(monkeypatch, fake, ran)
    assert claude_agent.run_agent(INVESTIGATION, steps.append) == DIAGNOSIS
    assert ran == ["describe pod web-1", "logs web-1 --previous"]
    assert any("describe pod web-1" in s and s.startswith("ai|") for s in steps)
    # the model sees each command's output on the next turn, and the history is only ever appended to
    result = fake.calls[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and result["content"] == "output" and result["tool_use_id"] == "t1"
    assert "temperature" not in fake.calls[0] and "tool_choice" not in fake.calls[0]


def test_agent_stops_running_commands_after_the_budget(monkeypatch, settings):
    fake = FakeClaude([_reply(_tool_use("kubectl", {"command": f"get pods -n n{i}"}, f"t{i}")) for i in range(2)]
                      + [_reply(_tool_use("kubectl", {"command": "get nodes"}, "t9")), _reply(_tool_use("submit_diagnosis", DIAGNOSIS))])
    ran = []
    _install(monkeypatch, fake, ran)
    claude_agent.run_agent(INVESTIGATION)
    assert len(ran) == 2  # the third command was refused, not run
    refused = fake.calls[3]["messages"][-1]["content"][0]
    assert refused["is_error"] and "submit_diagnosis" in refused["content"]


def test_agent_asks_once_for_the_structured_answer(monkeypatch, settings):
    prose = _reply(SimpleNamespace(type="text", text="the pod is OOMKilled"), stop="end_turn")
    fake = FakeClaude([prose, _reply(_tool_use("submit_diagnosis", DIAGNOSIS))])
    _install(monkeypatch, fake, [])
    assert claude_agent.run_agent(INVESTIGATION) == DIAGNOSIS
    fake = FakeClaude([prose, prose])
    _install(monkeypatch, fake, [])
    with pytest.raises(LLMError):
        claude_agent.run_agent(INVESTIGATION)


def test_agent_maps_api_errors_to_friendly_messages(monkeypatch, settings):
    import httpx

    class Boom(FakeClaude):
        def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise claude_agent.anthropic.AuthenticationError("bad", response=httpx.Response(401, request=request), body=None)

    _install(monkeypatch, Boom([]), [])
    with pytest.raises(LLMError, match="API key"):
        claude_agent.run_agent(INVESTIGATION)


# ------------------------------------------------ the OpenAI-compatible loop


def _call(name, arguments, id_="c1"):
    import json

    return {"id": id_, "type": "function", "function": {"name": name, "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}}


def _msg(content="", calls=None):
    return {"choices": [{"message": {"role": "assistant", "content": content, "reasoning": "x", **({"tool_calls": calls} if calls else {})}}]}


def _install_openai(monkeypatch, replies, ran):
    from app.ai import openai_agent

    sent = []

    def fake_post(body):
        sent.append({**body, "messages": list(body["messages"])})
        return replies.pop(0)

    monkeypatch.setattr(openai_agent, "post_chat", fake_post)
    monkeypatch.setattr(openai_agent, "run_command", lambda cmd: (ran.append(cmd) or "output", False))
    monkeypatch.setattr(openai_agent, "get_settings", lambda: SimpleNamespace(agent_max_steps=2, agent_timeout_seconds=60, allowed_namespace=""))
    return openai_agent, sent


def test_openai_agent_runs_commands_then_submits(monkeypatch):
    ran = []
    agent, sent = _install_openai(monkeypatch, [
        _msg(calls=[_call("kubectl", {"command": "describe pod web-1"})]),
        _msg(calls=[_call("submit_diagnosis", DIAGNOSIS)]),
    ], ran)
    assert agent.run_openai_agent(INVESTIGATION) == DIAGNOSIS
    assert ran == ["describe pod web-1"]
    second = sent[1]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": "output"}
    assert "reasoning" not in second[-2]  # provider-specific extras are not replayed
    assert sent[0]["tools"][0]["function"]["name"] == "kubectl" and sent[0]["messages"][0]["role"] == "system"


def test_openai_agent_accepts_json_text_and_rejects_bad_arguments(monkeypatch):
    agent, _ = _install_openai(monkeypatch, [_msg('```json\n{"summary": "s", "issues": [{"root_cause": "x"}]}\n```')], [])
    assert agent.run_openai_agent(INVESTIGATION)["issues"][0]["root_cause"] == "x"

    ran = []
    agent, sent = _install_openai(monkeypatch, [
        _msg(calls=[_call("kubectl", "{not json")]),
        _msg(calls=[_call("submit_diagnosis", DIAGNOSIS)]),
    ], ran)
    agent.run_openai_agent(INVESTIGATION)
    assert ran == [] and "not valid JSON" in sent[1]["messages"][-1]["content"]


def test_openai_agent_enforces_budget_and_gives_up_on_prose(monkeypatch):
    ran = []
    agent, sent = _install_openai(monkeypatch, [_msg(calls=[_call("kubectl", {"command": f"get pods -n n{i}"}, f"c{i}")]) for i in range(3)]
                                  + [_msg(calls=[_call("submit_diagnosis", DIAGNOSIS)])], ran)
    agent.run_openai_agent(INVESTIGATION)
    assert len(ran) == 2 and "budget" in sent[3]["messages"][-2]["content"]

    agent, _ = _install_openai(monkeypatch, [_msg("no idea"), _msg("still no idea")], [])
    with pytest.raises(LLMError):
        agent.run_openai_agent(INVESTIGATION)


def test_agent_mode_selection(monkeypatch):
    from app.ai import agent

    def pick(mode, key):
        monkeypatch.setattr(agent, "get_settings", lambda: SimpleNamespace(agent_mode=mode, anthropic_api_key=key))
        return agent._agent_runner()

    assert pick("auto", "k") is agent.run_agent and pick("loop", "k") is agent.run_agent
    assert pick("auto", "") is None and pick("single", "k") is None
    assert pick("loop", "") is agent.run_openai_agent


def test_openai_agent_retries_unusable_replies_and_reports_the_provider_error(monkeypatch):
    monkeypatch.setattr("app.ai.openai_agent.time.sleep", lambda s: None)
    replies = [{"error": {"message": "provider overloaded"}}, {"choices": None}, _msg(calls=[_call("submit_diagnosis", DIAGNOSIS)])]
    agent, _ = _install_openai(monkeypatch, replies, [])
    assert agent.run_openai_agent(INVESTIGATION) == DIAGNOSIS

    agent, _ = _install_openai(monkeypatch, [{"error": {"message": "provider overloaded"}}] * 3, [])
    with pytest.raises(LLMError, match="provider overloaded"):
        agent.run_openai_agent(INVESTIGATION)


def test_agent_sees_the_full_kubectl_error(monkeypatch):
    stderr = "error: unknown shorthand flag: 'a' in -a\nSee 'kubectl get --help' for usage."
    failed = {"success": False, "stdout": "", "stderr": "See 'kubectl get --help'", "stderr_full": stderr, "returncode": 1}
    monkeypatch.setattr(agent_tools, "run_kubectl", lambda args, timeout: failed)
    text, is_error = agent_tools.run_command("get pods -a")
    assert is_error and "unknown shorthand flag" in text
