from enum import Enum, unique


@unique
class SessionWarningType(Enum):
    USER_VARS_WITH_NO_USER = (
        "Because no user was provided, default flow variables were used instead of persistent ones."
    )
