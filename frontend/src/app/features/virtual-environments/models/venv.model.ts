// Mirrors VERSION_PATTERN in the sandbox service's Library model; keep in sync.
export const VENV_LIBRARY_VERSION_PATTERN =
    /^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?(\+[a-z0-9]+([-_.][a-z0-9]+)*)?$/;

// Shape of a PEP 440 specifier set such as `!=1.2,>=1.0,<=1.8`: a comma-separated list of
// clauses, each an operator followed by a version token. Deliberately looser than
// VENV_LIBRARY_VERSION_PATTERN, which rejects the `.*` wildcard a clause may carry
// (`==1.2.*`). The sandbox service validates the set with `packaging.SpecifierSet` and is the
// authority; this only catches obvious typos before the request leaves the browser.
export const VENV_LIBRARY_SPECIFICATION_PATTERN =
    /^\s*(===|==|!=|~=|>=|<=|>|<)\s*[0-9A-Za-z][0-9A-Za-z.*+!_-]*(\s*,\s*(===|==|!=|~=|>=|<=|>|<)\s*[0-9A-Za-z][0-9A-Za-z.*+!_-]*)*\s*$/;

// The sandbox_new venv lifecycle, mirrored from the service's VenvStatus enum.
export type VenvStatus = 'declared' | 'processing' | 'completed' | 'failed';

// `version` is the installed version: the user may pin it, and a successful build writes back
// what it installed. `specification` is the specifier set the version is validated against, and
// what the resolver picks from when `version` is empty.
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
