export interface ResetPasswordRequest {
    email: string;
}

export interface ResetPasswordResponse {
    detail?: string | null;
    smtp_configured?: boolean;
}

export interface ConfirmResetPasswordRequest {
    token: string;
    new_password: string;
}

export interface ConfirmResetPasswordResponse {
    detail: string;
}
