/** A name the browser may save a file under: letters, digits, dots, dashes and underscores, not starting with a dot. */
const SAFE_FILE_NAME = /^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$/;

/** `filename="<name>"` or `filename=<name>` in a `Content-Disposition` header. */
const FILE_NAME_PARAMETER = /(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;\s"]+))/i;

/**
 * The file name a `Content-Disposition: attachment; filename="…"` header gives, or `null` when there is none or it is
 * not a plain file name (a path, a hidden file, an encoded `filename*` only).
 */
export function attachmentFileName(contentDisposition: string | null): string | null {
    if (!contentDisposition) return null;
    const match = FILE_NAME_PARAMETER.exec(contentDisposition);
    const name = match?.[1] ?? match?.[2] ?? null;
    return name !== null && SAFE_FILE_NAME.test(name) ? name : null;
}
