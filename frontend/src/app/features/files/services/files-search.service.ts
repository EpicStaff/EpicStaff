import { Injectable, signal } from '@angular/core';

@Injectable()
export class FilesSearchService {
    private searchTermSignal = signal<string>('');
    public readonly searchTerm = this.searchTermSignal.asReadonly();

    setSearchTerm(term: string): void {
        this.searchTermSignal.set(term);
    }

    clear(): void {
        this.searchTermSignal.set('');
    }
}
