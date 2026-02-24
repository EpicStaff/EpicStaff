export interface MarkdownStrategyModel {
    chunk_size: number;
    chunk_overlap: number;
    headers_to_split_on: string[];
    return_each_line: boolean;
    strip_headers: boolean;
}

export interface CharacterStrategyModel {
    chunk_size: number;
    chunk_overlap: number;
    regex: string;
}

export interface CsvStrategyModel {
    rows_in_chunk: number;
    headers_level: number;
}

export interface HtmlStrategyModel {
    chunk_size: number;
    chunk_overlap: number;
    preserve_links: boolean;
    normalize_text: boolean;
    external_metadata: string;
    denylist_tags: string;
}

export interface TokenStrategyModel {
    chunk_size: number;
    chunk_overlap: number;
}

export interface JsonStrategyModel {
    chunk_size: number;
    chunk_overlap: number;
}

export type StrategyModel =
    | MarkdownStrategyModel
    | CharacterStrategyModel
    | HtmlStrategyModel
    | TokenStrategyModel
    | JsonStrategyModel
    | CsvStrategyModel
