/** `GET system-info/`: the backend's build and which optional features it has switched on. */
export interface SystemInfo {
    version: string | null;
    git_ref: string | null;
    git_sha: string | null;
    commit_date: string | null;
    import_version: number;
    features: SystemInfoFeatures;
}

export interface SystemInfoFeatures {
    chats: boolean;
    plugins: boolean;
    session_audit: boolean;
    user_audit: boolean;
}

/** The commit the running frontend bundle was built from; `null` where the bundle carries no build file. */
export interface FrontendBuild {
    gitSha: string | null;
    commitDate: string | null;
}
