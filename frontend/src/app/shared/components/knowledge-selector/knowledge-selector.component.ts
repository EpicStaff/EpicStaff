import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ClickOutsideDirective } from '../../directives/click-outside.directive';
import { GetSourceCollectionRequest } from '../../../pages/knowledge-sources/models/source-collection.model';

@Component({
  selector: 'app-knowledge-selector',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    ClickOutsideDirective,
  ],
  templateUrl: './knowledge-selector.component.html',
  styleUrls: ['./knowledge-selector.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KnowledgeSelectorComponent {
  @Input() collections: GetSourceCollectionRequest[] = [];
  @Input() selectedCollectionId: number | null = null;
  @Input() label: string = 'Knowledge Source';
  @Input() disabled: boolean = false;
  @Input() loading: boolean = false;

  @Output() collectionChange = new EventEmitter<number | null>();

  public isOpen = false;
  public isPlaceholder = true;

  constructor(private cdr: ChangeDetectorRef) {}

  public toggleDropdown(): void {
    if (this.disabled || this.loading) {
      return;
    }

    this.isOpen = !this.isOpen;
    this.cdr.markForCheck();
  }

  public closeDropdown(): void {
    this.isOpen = false;
    this.cdr.markForCheck();
  }

  public selectCollection(
    collectionId: number | null,
    isPlaceholder: boolean = true
  ): void {
    this.selectedCollectionId = collectionId;
    this.isPlaceholder = isPlaceholder;
    this.collectionChange.emit(collectionId);
    this.closeDropdown();
  }

  public getSelectedCollectionName(): string {
    if (this.selectedCollectionId === null) {
      return this.loading ? 'Loading...' : 'Select knowledge source';
    }

    const selectedCollection = this.collections.find(
      (c) => c.collection_id === this.selectedCollectionId
    );
    return selectedCollection
      ? selectedCollection.collection_name
      : 'Select knowledge source';
  }
}
