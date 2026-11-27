export interface DashboardCardDetail {
    value: string | number;
    label: string;
}

export interface DashboardResourceCard {
    icon: string;
    label: string;
    value: number;
    details: DashboardCardDetail[];
    link: string;
}
