/**
 * Read-only last edit of a resource whose edits the backend tracks
 * (`LastEditFieldsSerializerMixin`). Both are null until an edit is recorded;
 * `last_edited_by` is also null once the editor has left the organization.
 */
export interface LastEditFields {
    /** Id of the user who made the last edit. */
    last_edited_by: number | null;
    /** ISO 8601 timestamp of the last edit. */
    last_edited_at: string | null;
}

/**
 * Read-only author and last edit of an authored resource. `created_by` is a user
 * id; null when the author is unknown or has left the organization.
 */
export interface AuthorshipFields extends LastEditFields {
    created_by: number | null;
}
