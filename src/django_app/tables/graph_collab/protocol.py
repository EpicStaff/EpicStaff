from pydantic import BaseModel, ConfigDict


class EditorInfo(BaseModel):
    user_id: int
    display_name: str | None
    avatar_url: str | None

    model_config = ConfigDict(from_attributes=True)


class GraphSavedMessage(BaseModel):
    type: str = "graph_saved"
    graph_id: int
    new_save_version: int
    saved_by: EditorInfo
    saved_at: str


class PresenceStateMessage(BaseModel):
    type: str = "presence_state"
    editors: list[EditorInfo]


class UserJoinedMessage(BaseModel):
    type: str = "user_joined"
    editor: EditorInfo


class UserLeftMessage(BaseModel):
    type: str = "user_left"
    user_id: int


class PresenceStateUpdatedMessage(BaseModel):
    type: str = "presence_state_updated"
    editor: EditorInfo


class ErrorMessage(BaseModel):
    type: str = "error"
    code: str
    message: str
