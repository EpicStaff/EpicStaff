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
    organization: SetupOrganizationResponse;
    user: SetupUserResponse;
}

export interface AccessToken {
    access: string;
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
