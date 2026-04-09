export enum LabelColor {
    Default = 'default',
    Purple = 'purple',
    Blue = 'blue',
    Green = 'green',
    Orange = 'orange',
    Red = 'red',
}

export interface LabelColorOption {
    id: LabelColor;
    circleBg: string;
    chipBg: string;
    chipColor: string;
}

export const LABEL_COLOR_OPTIONS: LabelColorOption[] = [
    { id: LabelColor.Default, circleBg: '#D9D9D9', chipBg: 'rgba(217,217,222,0.08)', chipColor: '#D9D9DE' },
    { id: LabelColor.Purple, circleBg: '#685FFF', chipBg: 'rgba(104,95,255,0.08)', chipColor: '#685FFF' },
    { id: LabelColor.Blue, circleBg: '#48CBFF', chipBg: 'rgba(72,203,255,0.08)', chipColor: '#48CBFF' },
    { id: LabelColor.Green, circleBg: '#2ABA6B', chipBg: 'rgba(42,186,107,0.08)', chipColor: '#2ABA6B' },
    { id: LabelColor.Orange, circleBg: '#FF8F3F', chipBg: 'rgba(255,143,63,0.08)', chipColor: '#FF8F3F' },
    { id: LabelColor.Red, circleBg: '#F54242', chipBg: 'rgba(245,66,66,0.08)', chipColor: '#F54242' },
];

export function getLabelColorOption(color?: string | null): LabelColorOption {
    return LABEL_COLOR_OPTIONS.find((o) => o.id === color) ?? LABEL_COLOR_OPTIONS[0];
}

export interface LabelDto {
    id: number;
    name: string;
    parent: number | null;
    full_path: string;
    created_at: string;
    metadata: { color?: LabelColor };
}

export interface CreateLabelRequest {
    name: string;
    parent?: number | null;
    metadata?: { color?: LabelColor };
}

export interface UpdateLabelRequest {
    name: string;
    parent?: number | null;
    metadata?: { color?: LabelColor };
}

export interface PatchLabelRequest {
    metadata?: { color?: LabelColor };
    name?: string;
}
