/**
 * Public identity of a user as the backend renders an author or last editor
 * (`UserSummarySerializer`). Only these three fields are exposed — never email,
 * roles or memberships.
 */
export interface UserSummary {
    id: number;
    /** Null when the user never set a display name; there is no email fallback. */
    display_name: string | null;
    /** Absolute URL of the user's avatar; null when none is set. */
    avatar_url: string | null;
}

/**
 * Read-only last edit of a resource whose edits the backend tracks
 * (`LastEditFieldsSerializerMixin`). Both are null until an edit is recorded;
 * `last_edited_by` is also null once the editor has left the organization.
 */
export interface LastEditFields {
    /** The user who made the last edit. */
    last_edited_by: UserSummary | null;
    /** ISO 8601 timestamp of the last edit. */
    last_edited_at: string | null;
}

/**
 * Read-only author of a resource (`AuthorSummarySerializerMixin`). Null when the
 * author is unknown or has left the organization.
 */
export interface AuthorFields {
    created_by: UserSummary | null;
}

/** Read-only author and last edit of an authored resource. */
export interface AuthorshipFields extends AuthorFields, LastEditFields {}
