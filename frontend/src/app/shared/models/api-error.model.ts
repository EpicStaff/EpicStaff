/** One thing that went wrong, as every error answer lists it. */
export interface ApiErrorDetail {
    /** Machine-readable name for what went wrong. */
    code: string;
    /** What went wrong, in words. */
    detail: string;
    /** The request field at fault, dotted for a nested one; null when the error belongs to no single field. */
    attr: string | null;
    /** Safe structured data about the error (a limit, the names involved); null when there is none. */
    context: Record<string, unknown> | null;
}

/** The one shape every error answer takes, whatever the status code. */
export interface ApiErrorResponse {
    type: string;
    errors: ApiErrorDetail[];
}
