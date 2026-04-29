import { DefaultLlmsCard } from './default-llms-card.interface';

export interface DefaultLlmsSection {
    id: string;
    title: string;
    cards: DefaultLlmsCard[];
}
