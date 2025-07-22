import {
  Component,
  Input,
  ElementRef,
  OnDestroy,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { Dialog } from '@angular/cdk/dialog';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { EmbeddingConfigsService } from '../../../../../features/settings-dialog/services/embeddings/embedding_configs.service';
import { ConfirmationDialogService } from '../../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { ClickOutsideDirective } from '../../../../../shared/directives/click-outside.directive';
import {
  CollectionStatus,
  GetSourceCollectionRequest,
} from '../../../models/source-collection.model';

import { KnowledgeSourcesPageService } from '../../../services/knowledge-sources-page.service';
import { CollectionsService } from '../../../services/source-collections.service';
import { RenameCollectionDialogComponent } from '../rename-collection-dialog/rename-collection-dialog.component';

@Component({
  selector: 'app-collection-item',
  standalone: true,
  imports: [CommonModule, ClickOutsideDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="collection-item"
      [class.active]="isActive"
      (click)="onCollectionClick()"
    >
      <div
        class="collection-status-dot"
        [class.status-new]="collection.status === CollectionStatus.NEW"
        [class.status-processing]="
          collection.status === CollectionStatus.PROCESSING
        "
        [class.status-completed]="
          collection.status === CollectionStatus.COMPLETED
        "
        [class.status-failed]="collection.status === CollectionStatus.FAILED"
      ></div>

      <div class="collection-name">{{ collection.collection_name }}</div>

      <div class="dropdown" clickOutside (clickOutside)="onClickOutside()">
        <button class="more-options-button" (click)="toggleDropdown($event)">
          <svg width="16" height="16" viewBox="0 0 24 24">
            <circle cx="12" cy="6" r="2" fill="currentColor" />
            <circle cx="12" cy="12" r="2" fill="currentColor" />
            <circle cx="12" cy="18" r="2" fill="currentColor" />
          </svg>
        </button>

        <div class="dropdown-menu" [class.show]="isDropdownOpen">
          <div class="dropdown-item" (click)="onCopyClick($event)">Copy</div>
          <div class="dropdown-item" (click)="onRenameClick($event)">
            Rename
          </div>
          <div class="dropdown-item" (click)="onDeleteClick($event)">
            Delete
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      @keyframes breathing {
        0% {
          opacity: 0.6;
          transform: scale(0.9);
        }
        50% {
          opacity: 1;
          transform: scale(1.1);
        }
        100% {
          opacity: 0.6;
          transform: scale(0.9);
        }
      }

      .collection-item {
        display: flex;
        align-items: center;
        padding: 10px 16px;
        border-radius: 10px;
        margin-bottom: 8px;
        background-color: #151515;
        cursor: pointer;
        transition: background-color 0.2s ease;
        position: relative;

        &:hover {
          background-color: rgba(40, 40, 40, 0.8);
        }

        &.active {
          background-color: rgba(104, 95, 255, 0.15);
        }

        .collection-status-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          margin-right: 15px;

          &.status-new {
            background-color: #22c55e;
          }

          &.status-processing {
            background-color: #f97316;
            animation: breathing 2s infinite ease-in-out;
          }

          &.status-completed {
            background-color: #685fff;
          }

          &.status-failed {
            background-color: #ef4444;
          }
        }

        .collection-name {
          flex: 1;
          font-size: 14px;
          color: rgba(255, 255, 255, 0.9);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        .dropdown {
          position: relative;
          display: inline-block;

          .more-options-button {
            background: none;
            border: none;
            color: rgba(255, 255, 255, 0.5);
            margin-left: 8px;
            padding: 4px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;

            &:hover {
              background-color: rgba(255, 255, 255, 0.1);
              color: rgba(255, 255, 255, 0.8);
            }
          }

          .dropdown-menu {
            display: none;
            position: absolute;
            right: 0;
            top: 100%;
            margin-top: 5px;
            background-color: #2a2a2a;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
            z-index: 10;
            overflow: hidden;
            min-width: 150px;
            padding: 8px 0;

            &.show {
              display: block;
            }

            .dropdown-item {
              padding: 6px 12px;
              font-size: 14px;
              color: rgba(255, 255, 255, 0.9);
              cursor: pointer;
              transition: background-color 0.2s ease;
              margin: 2px 8px;
              border-radius: 4px;

              &:hover {
                background-color: rgba(255, 255, 255, 0.1);
              }
            }
          }
        }
      }
    `,
  ],
})
export class CollectionItemComponent implements OnDestroy {
  @Input() collection!: GetSourceCollectionRequest;
  @Input() isActive: boolean = false;

  public CollectionStatus = CollectionStatus;

  private _destroy$ = new Subject<void>();
  isDropdownOpen = false;

  constructor(
    private elementRef: ElementRef,
    private _dialog: Dialog,
    private _pageService: KnowledgeSourcesPageService,
    private _GetSourceCollectionRequestsService: CollectionsService,
    private _embeddingConfigsService: EmbeddingConfigsService,
    private _confirmationDialogService: ConfirmationDialogService
  ) {}

  ngOnDestroy(): void {
    this._destroy$.next();
    this._destroy$.complete();
  }

  onCollectionClick(): void {
    this.selectCollection(this.collection);
  }

  toggleDropdown(event: MouseEvent): void {
    event.stopPropagation();
    this.isDropdownOpen = !this.isDropdownOpen;
  }

  onClickOutside(): void {
    if (this.isDropdownOpen) {
      this.isDropdownOpen = false;
      console.log('Dropdown closed (outside click)');
    }
  }

  public onRenameClick(event: MouseEvent): void {
    event.stopPropagation();
    this.renameCollection(this.collection);
    this.toggleDropdown(event);
  }

  public onDeleteClick(event: MouseEvent): void {
    event.stopPropagation();
    console.log('Delete collection:', this.collection.collection_name);
    this.deleteCollection(this.collection);
    this.isDropdownOpen = false;
  }
  public onCopyClick(event: MouseEvent): void {
    event.stopPropagation();
    console.log('Copy collection:', this.collection.collection_name);
    this.isDropdownOpen = false;
  }

  private selectCollection(collection: GetSourceCollectionRequest): void {
    this._pageService.setSelectedCollection(collection);

    if (collection.embedder) {
      this._embeddingConfigsService
        .getEmbeddingConfigById(collection.embedder)
        .pipe(takeUntil(this._destroy$))
        .subscribe({
          next: (embeddingConfig) => {
            this._pageService.setSelectedEmbeddingConfig(embeddingConfig);
          },
          error: (error) => {
            console.error('Failed to load embedding model', error);
          },
        });
    }
  }

  private renameCollection(collection: GetSourceCollectionRequest): void {
    const dialogRef = this._dialog.open<string>(
      RenameCollectionDialogComponent,
      {
        width: '450px',
        data: {
          collectionName: collection.collection_name,
          collectionId: collection.collection_id,
        },
      }
    );

    dialogRef.closed.pipe(takeUntil(this._destroy$)).subscribe((newName) => {
      if (newName) {
        this._GetSourceCollectionRequestsService
          .patchGetSourceCollectionRequest(collection.collection_id, newName)
          .pipe(takeUntil(this._destroy$))
          .subscribe({
            next: () => {
              this._pageService.updateCollection(collection.collection_id, {
                collection_name: newName,
              });
            },
            error: (error) => {
              console.error('Failed to rename collection', error);
              alert(`Failed to rename collection: ${error.message}`);
            },
          });
      }
    });
  }

  private deleteCollection(collection: GetSourceCollectionRequest): void {
    this._confirmationDialogService
      .confirmDelete(collection.collection_name)
      .pipe(takeUntil(this._destroy$))
      .subscribe({
        next: (confirmed) => {
          if (confirmed === true) {
            this._GetSourceCollectionRequestsService
              .deleteGetSourceCollectionRequest(collection.collection_id)
              .pipe(takeUntil(this._destroy$))
              .subscribe({
                next: () => {
                  this._pageService.removeCollection(collection.collection_id);

                  if (
                    this._pageService.selectedCollection()?.collection_id ===
                    collection.collection_id
                  ) {
                    const remainingCollections =
                      this._pageService.collections();
                    if (remainingCollections.length > 0) {
                      this.selectCollection(remainingCollections[0]);
                    } else {
                      this._pageService.setSelectedCollection(null);
                    }
                  }
                },
                error: (error) => {
                  console.error('Failed to delete collection', error);
                  alert(`Failed to delete collection: ${error.message}`);
                },
              });
          }
        },
      });
  }
}
