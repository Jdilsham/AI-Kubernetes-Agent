from pydantic import BaseModel, computed_field


class Issue(BaseModel):
    title: str = ""
    severity: str = "warning"  # critical | warning | info
    affected: list[str] = []
    root_cause: str
    explanation: str = ""
    fix: str = ""
    kubectl_commands: list[str] = []
    prevention: str = ""
    confidence: int = 0
    confidence_reasoning: list[str] = []


class Diagnosis(BaseModel):
    """The most important issue at the top level (backwards compatible) plus all issues."""

    root_cause: str
    explanation: str
    fix: str
    kubectl_commands: list[str] = []
    prevention: str = ""
    confidence: int
    confidence_reasoning: list[str] = []
    healthy: bool = False  # True when no issues were found
    summary: str = ""
    issues: list[Issue] = []

    @computed_field
    @property
    def kubectl_command(self) -> str:
        """First suggested command (convenience for simple clients)."""
        return self.kubectl_commands[0] if self.kubectl_commands else ""
