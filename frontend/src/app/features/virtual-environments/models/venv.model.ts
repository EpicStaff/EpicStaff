// The sandbox_new venv lifecycle, mirrored from the service's VenvStatus enum.
export type VenvStatus = 'declared' | 'processing' | 'completed' | 'failed';

// A pinned library. `specification` is a PEP 440 specifier string (e.g. "==1.2.3")
// and `version` is the bare version the specifier was built from.
export interface VenvLib {
    name: string;
    specification: string;
    version: string | null;
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
