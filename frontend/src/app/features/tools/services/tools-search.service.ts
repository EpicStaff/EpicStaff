import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

@Injectable({
  providedIn: 'root',
})
export class ToolsSearchService {
  private searchTermSubject = new BehaviorSubject<string>('');
  public searchTerm$: Observable<string> = this.searchTermSubject.asObservable();

  public setSearchTerm(term: string): void {
    this.searchTermSubject.next(term);
  }

  public clearSearch(): void {
    this.searchTermSubject.next('');
  }
}

