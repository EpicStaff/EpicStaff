export interface DeleteReport {
    affected_resources: Record<string, number>;
}

export interface UserDeleteReport extends DeleteReport {
    user_id: number;
}

export interface OrganizationDeleteReport extends DeleteReport {
    organization_id: number;
}
