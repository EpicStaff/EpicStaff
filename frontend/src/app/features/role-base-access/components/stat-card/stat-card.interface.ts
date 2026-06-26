export interface StatCardData {
    label: string;
    value: number;
    icon?: string;
    delta?: CardDeltaInfo;
    loading?: boolean;
}

export interface CardDeltaInfo {
    value: number;
    label: string;
    trend: 'increase' | 'decrease';
    color: 'red' | 'green';
}
