from application.orchestrators.estimating import strategies
from application.orchestrators.estimating.base import AbstractEstimateOrchestrator
from application.ports import AbstractUnitOfWork
from domain.enums import RAGStrategy
from domain.errors import UnsupportedError

_STRATEGIES: dict[RAGStrategy, type[AbstractEstimateOrchestrator]] = {
    RAGStrategy.NAIVE: strategies.NaiveEstimateOrchestrator,
}


def build_estimator(strategy: RAGStrategy, uow: AbstractUnitOfWork) -> AbstractEstimateOrchestrator:
    """Build the estimator registered for `strategy`.

    Raises:
        UnsupportedError: If no estimator is registered for `strategy`.
    """
    if strategy not in _STRATEGIES:
        raise UnsupportedError(that="estimate strategy", got=strategy)
    return _STRATEGIES[strategy](uow)
