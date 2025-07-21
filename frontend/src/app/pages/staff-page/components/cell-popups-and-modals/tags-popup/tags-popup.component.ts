import {
  Component,
  Input,
  Output,
  EventEmitter,
  ChangeDetectionStrategy,
  OnInit,
} from '@angular/core';
import { NgClass, NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-tags-popup',
  standalone: true,
  imports: [NgFor, FormsModule, NgClass],
  template: `
    <div class="tags-popup" (click)="$event.stopPropagation()">
      <div class="header">
        <h3>Manage Tags</h3>
        <span class="clear-all" (click)="clearAllTags()">Clear all</span>
      </div>
      <div class="content">
        <div class="tags-container">
          <div
            class="tag-item"
            *ngFor="let tag of tags; let i = index"
            [ngClass]="{ duplicate: duplicateTagIndex === i }"
          >
            <div class="tag-text">#{{ tag }}</div>
            <button
              type="button"
              class="remove-btn"
              (click)="removeTag(i)"
              aria-label="Remove tag"
            >
              ×
            </button>
          </div>
          <div class="tag-input-item">
            <input
              type="text"
              placeholder="Add tag"
              [(ngModel)]="newTag"
              (keyup.enter)="addTag()"
            />
            <button
              type="button"
              class="add-btn"
              (click)="addTag()"
              aria-label="Add tag"
            >
              <i class="ti ti-plus"></i>
            </button>
          </div>
        </div>
      </div>

      <button class="save" type="button" (click)="saveTags()">Save</button>
    </div>
  `,
  styles: [
    `
      .tags-popup {
        width: 350px;
        padding: 16px;
        background: #1a1a1a;
        border: 1px solid #333;
        color: #f0f0f0;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
        border-radius: 12px;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI',
          Roboto, sans-serif;
        font-size: 14px;
        transition: all 0.2s ease;
        .header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 16px;
          padding-bottom: 12px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.08);

          h3 {
            margin: 0;
            font-size: 18px;
            font-weight: 600;
            color: #f0f0f0;
            letter-spacing: 0.3px;
          }

          .clear-all {
            font-size: 13px;
            color: #5e9ced;
            cursor: pointer;
            user-select: none;
            transition: all 0.2s ease;
            padding: 4px 8px;
            border-radius: 4px;

            &:hover {
              background: rgba(94, 156, 237, 0.1);
              color: #7aafff;
            }
          }
        }

        .content {
          flex: 1;
          overflow-y: auto;
          min-height: 120px;
          max-height: 200px;
          margin-bottom: 16px;
          padding-bottom: 4px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.06);
          scrollbar-width: thin;
          scrollbar-color: #444 #222;

          .tags-container {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
          }

          .tag-item,
          .tag-input-item {
            display: flex;
            align-items: center;
            height: 30px;
            border-radius: 6px;
            transition: all 0.15s ease;
          }

          .tag-item {
            background: #2a2a2a;
            padding: 0 6px 0 12px;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
            border: 1px solid #3a3a3a;

            &:hover {
              background: #333;
              border-color: #444;
            }

            &.duplicate {
              border: 1px solid #5e9ced;
              background: rgba(94, 156, 237, 0.15);
              animation: shake 0.5s;
            }

            .tag-text {
              font-size: 13px;
              margin-right: 8px;
              color: #e6e6e6;
              font-weight: 500;
            }

            .remove-btn {
              display: flex;
              align-items: center;
              justify-content: center;
              background: transparent;
              border: none;
              color: #999;
              cursor: pointer;
              font-size: 18px;
              width: 20px;
              height: 20px;
              border-radius: 50%;
              transition: all 0.15s ease;
              padding: 0;
              margin-left: 4px;

              &:hover {
                background: rgba(255, 107, 107, 0.15);
                color: #ff6b6b;
              }
            }
          }

          .tag-input-item {
            background: #252525;
            border: 1px solid #3a3a3a;
            padding: 0 6px 0 12px;
            min-width: 120px;
            transition: all 0.2s ease;

            &:focus-within {
              background: #2d2d2d;
              border-color: #5e9ced;
              box-shadow: 0 0 0 2px rgba(94, 156, 237, 0.25);
            }

            input[type='text'] {
              border: none;
              background: transparent;
              color: #f0f0f0;
              width: 100px;
              font-size: 13px;
              font-family: inherit;
              outline: none;
              padding: 0;

              &::placeholder {
                color: #888;
              }
            }

            .add-btn {
              background: transparent;
              border: none;
              color: #5e9ced;
              cursor: pointer;
              width: 24px;
              height: 24px;
              display: flex;
              align-items: center;
              justify-content: center;
              border-radius: 50%;
              transition: all 0.15s ease;
              padding: 0;

              &:hover {
                background: rgba(94, 156, 237, 0.15);
                color: #7aafff;
              }

              i {
                font-size: 16px;
                height: 16px;
                width: 16px;
              }
            }
          }
        }

        .save {
          display: block;
          margin-left: auto;
          padding: 6px 12px; // Reduced padding for smaller button
          font-size: 12px; // Reduced font size
          font-weight: 500;
          background: #5e9ced;
          color: #fff;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          transition: all 0.2s ease;
          box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);

          &:hover {
            background: #4a8ae0;
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.25);
          }

          &:active {
            transform: translateY(0);
            background: #3a7ad0;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
          }
        }
      }

      @keyframes shake {
        0% {
          transform: translateX(0);
        }
        25% {
          transform: translateX(-5px);
        }
        50% {
          transform: translateX(5px);
        }
        75% {
          transform: translateX(-5px);
        }
        100% {
          transform: translateX(0);
        }
      }
    `,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TagsPopupComponent implements OnInit {
  @Input() cellTags: string[] = [];
  @Output() tagsSaved = new EventEmitter<string[]>();

  tags: string[] = [];
  newTag: string = '';
  duplicateTagIndex: number | null = null;

  ngOnInit(): void {
    // Initialize internal tags array with cellTags input
    this.tags = [...this.cellTags];
  }

  addTag(): void {
    const trimmedTag = this.newTag.trim();
    if (trimmedTag) {
      // Check for duplicates (case-insensitive)
      const existingIndex = this.tags.findIndex(
        (tag) => tag.toLowerCase() === trimmedTag.toLowerCase()
      );
      if (existingIndex === -1) {
        this.tags.push(trimmedTag);
        this.newTag = '';
      } else {
        // Duplicate found: trigger shake animation and blue border,
        // but keep the current input value so the user can modify it.
        this.duplicateTagIndex = existingIndex;
        // Removed resetting of this.newTag to keep the input unchanged
        setTimeout(() => {
          this.duplicateTagIndex = null;
        }, 500);
      }
    }
  }

  removeTag(index: number): void {
    this.tags.splice(index, 1);
  }

  clearAllTags(): void {
    this.tags = [];
  }

  saveTags(): void {
    this.tagsSaved.emit([...this.tags]);
  }
}
