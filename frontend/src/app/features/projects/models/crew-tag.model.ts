export interface GetCrewTagRequest {
    id: number;
    name: string;
    predifined: boolean;
}

export interface CreateCrewTagRequest {
    name: string;
    predifined: boolean;
}

export interface UpdateCrewTagRequest {
    name: string;
    predifined: boolean;
}
