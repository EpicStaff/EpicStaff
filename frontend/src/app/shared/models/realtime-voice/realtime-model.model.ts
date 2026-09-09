export interface RealtimeModel {
    id: number;
    name: string;
    provider: number;
    is_custom: boolean;
}

export interface CreateRealtimeModel {
    name: string;
    provider: number;
}
