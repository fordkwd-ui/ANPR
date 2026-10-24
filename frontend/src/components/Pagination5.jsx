import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export const Pagination5 = ({
  currentPage = 1,
  totalPages = 1,
  onPageChange,
  className,
}) => {
  if (totalPages <= 1) return null;

  // Generate page numbers to display
  const pages = [];
  const maxButtons = 5;
  let startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
  let endPage = Math.min(totalPages, startPage + maxButtons - 1);
  if (endPage - startPage + 1 < maxButtons) {
    startPage = Math.max(1, endPage - maxButtons + 1);
  }

  for (let i = startPage; i <= endPage; i++) {
    pages.push(i);
  }

  return (
    <nav aria-label="Pagination Navigation" className={cn('pagination-container', className)}>
      <ul className="pagination-content">
        {/* Previous Button */}
        <li className="pagination-item">
          <button
            type="button"
            disabled={currentPage <= 1}
            onClick={() => onPageChange && onPageChange(currentPage - 1)}
            className={cn(
              'pagination-btn pagination-prev',
              currentPage <= 1 && 'is-disabled'
            )}
            aria-label="Previous Page"
          >
            <ChevronLeft size={14} />
            <span>Prev</span>
          </button>
        </li>

        {/* Page Numbers */}
        {pages.map((page) => {
          const isActive = page === currentPage;
          return (
            <li key={page} className="pagination-item">
              <button
                type="button"
                onClick={() => onPageChange && onPageChange(page)}
                className={cn(
                  'pagination-link',
                  isActive ? 'is-active' : 'is-inactive'
                )}
                aria-current={isActive ? 'page' : undefined}
              >
                {page}
              </button>
            </li>
          );
        })}

        {/* Next Button */}
        <li className="pagination-item">
          <button
            type="button"
            disabled={currentPage >= totalPages}
            onClick={() => onPageChange && onPageChange(currentPage + 1)}
            className={cn(
              'pagination-btn pagination-next',
              currentPage >= totalPages && 'is-disabled'
            )}
            aria-label="Next Page"
          >
            <span>Next</span>
            <ChevronRight size={14} />
          </button>
        </li>
      </ul>
    </nav>
  );
};

export default Pagination5;
