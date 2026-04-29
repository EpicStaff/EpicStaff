export interface FirstSetupStatus {
    needs_setup: boolean;
}

export interface FirstSetupRequest {
    email: string;
    password: string;
    display_name?: string;
}

export interface FirstSetupResponse {
    access: string;
    refresh: string;
    organization: SetupOrganizationResponse;
    user: SetupUserResponse;
}

export interface SetupOrganizationResponse {
    id: number;
    is_active: boolean;
    name: string;
}

export interface SetupUserResponse {
    display_name: string;
    email: string;
    id: number;
    is_superadmin: boolean;
}

export interface GetMeResponse {
    id: number;
    email: string;
    display_name: string;
    avatar_url: string;
    is_superadmin: boolean;
    memberships: Membership[];
}

export interface Membership {
    organization: Organization;
    role: Role;
    joined_at: string;
}

export interface Organization {
    id: number;
    name: string;
}

export interface Role {
    id: number;
    name: string;
}
