// Mirrors VERSION_PATTERN in the sandbox service's Library model; keep in sync.
export const VENV_LIBRARY_VERSION_PATTERN =
    /^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?(\+[a-z0-9]+([-_.][a-z0-9]+)*)?$/;

// The sandbox_new venv lifecycle, mirrored from the service's VenvStatus enum.
export type VenvStatus = 'declared' | 'processing' | 'completed' | 'failed';

// `version` is resolved and locked by the sandbox service; the user's constraint is `specification`.
export interface VenvLib {
    name: string;
    specification: string;
    version: string | null;
    description: string | null;
}

export interface VenvLibUpdate {
    name: string;
    currentVersion: string;
    latestVersion: string;
}

// The gateway injects `owner` and `created_at` from its org-scoped binding row; the
// sandbox_new payload itself carries neither. `owner` is null when the binding predates
// the `created_by` column or no binding backs the venv.
export interface VenvOwner {
    id: number;
    email: string;
    display_name: string | null;
}

export interface Venv {
    id: number;
    name: string;
    libs: VenvLib[];
    status: VenvStatus;
    error: string | null;
    owner: VenvOwner | null;
    created_at: string | null;
}

export interface CreateVenvRequest {
    name: string;
    libs: VenvLib[];
}

export type UpdateVenvRequest = Partial<CreateVenvRequest>;

// The venv list envelope uses `result` (singular), not the `results` of the shared
// `ApiGetRequest`: it passes through sandbox_new's VenvListSchema, which also carries
// `limit`/`offset`.
export interface VenvListResponse {
    count: number;
    limit: number;
    offset: number;
    next: string | null;
    previous: string | null;
    result: Venv[];
}
