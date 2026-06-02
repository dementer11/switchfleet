from __future__ import annotations

from app.core.exceptions import SafetyError
from app.schemas.lab_apply import ApplySafetyDecisionRead
from app.services.apply_safety_kernel import ApplySafetyEvaluation
from app.services.fake_lab_transport import FakeLabTransport
from app.services.transport_runtime import RuntimeCredentials, TransportRuntime


class LabTransportFactory:
    def __init__(self, runtime: TransportRuntime | None = None):
        self.runtime = runtime or TransportRuntime()

    def create_fake_transport(self, evaluation: ApplySafetyEvaluation) -> FakeLabTransport:
        self._assert_allowed(evaluation.decision)
        if evaluation.transport_decision is None:
            raise SafetyError("Cannot create lab transport without runtime decision")
        return FakeLabTransport(transport_kind=evaluation.transport_decision.selected_transport.value)

    def create_runtime_adapter(self, evaluation: ApplySafetyEvaluation, credentials: RuntimeCredentials | None = None) -> object:
        self._assert_allowed(evaluation.decision)
        if evaluation.transport_decision is None:
            raise SafetyError("Cannot create lab runtime adapter without runtime decision")
        return self.runtime.create_session(evaluation.transport_decision, credentials=credentials, mode="read_only")

    def _assert_allowed(self, decision: ApplySafetyDecisionRead) -> None:
        if not decision.allowed:
            raise SafetyError("Lab transport cannot be created until Apply Safety Kernel allows the request")
