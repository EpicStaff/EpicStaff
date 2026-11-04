export interface VisualizationEntity {
    id: string;
    title: string;
    type: string | null;
    description: string | null;
    degree: number;
    community_ids: string[];
}

export interface VisualizationRelationship {
    id: string;
    source: string;
    target: string;
    description: string | null;
    weight: number;
}

export interface VisualizationCommunity {
    id: string;
    title: string;
    level: number;
    size: number;
    entity_ids: string[];
}

export interface GraphVisualizationData {
    entities: VisualizationEntity[];
    relationships: VisualizationRelationship[];
    communities: VisualizationCommunity[];
}
