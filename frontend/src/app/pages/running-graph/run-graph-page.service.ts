import { Injectable, signal } from '@angular/core';
import { Memory } from './components/memory-sidebar/models/memory.model';

@Injectable({
  providedIn: 'root',
})
export class RunGraphPageService {
  private memories = signal<Memory[]>([]);

  constructor() {}

  public getMemories(): Memory[] {
    return this.memories();
  }

  public setMemories(memories: Memory[]): void {
    this.memories.set(memories);
  }

  public deleteMemory(memoryId: string): void {
    const currentMemories = this.memories();
    const updatedMemories = currentMemories.filter(
      (memory) => memory.id !== memoryId
    );
    this.memories.set(updatedMemories);
  }
}
