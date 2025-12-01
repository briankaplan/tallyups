// Mobile Filter Sheet Functions
let activeFilters = { status: 'all', business: 'all', date: 'all', amount: 'all' };

function openFilterSheet() {
  document.getElementById('filter-sheet-backdrop').classList.add('active');
  document.getElementById('filter-sheet').classList.add('active');
  // Haptic feedback
  if ('vibrate' in navigator) navigator.vibrate(10);
}

function closeFilterSheet() {
  document.getElementById('filter-sheet-backdrop').classList.remove('active');
  document.getElementById('filter-sheet').classList.remove('active');
}

// Filter option click handlers
document.querySelectorAll('.filter-option').forEach(btn => {
  btn.addEventListener('click', function() {
    const filterType = this.dataset.filter;
    const value = this.dataset.value;

    // Deselect siblings, select this one
    this.parentElement.querySelectorAll('.filter-option').forEach(b => b.classList.remove('active'));
    this.classList.add('active');

    activeFilters[filterType] = value;
    updateFilterCount();

    // Haptic feedback
    if ('vibrate' in navigator) navigator.vibrate(5);
  });
});

function updateFilterCount() {
  let count = 0;
  if (activeFilters.status !== 'all') count++;
  if (activeFilters.business !== 'all') count++;
  if (activeFilters.date !== 'all') count++;
  if (activeFilters.amount !== 'all') count++;

  const badge = document.getElementById('mobile-filter-count');
  if (count > 0) {
    badge.textContent = count;
    badge.style.display = 'inline';
  } else {
    badge.style.display = 'none';
  }
}

function clearAllFilters() {
  activeFilters = { status: 'all', business: 'all', date: 'all', amount: 'all' };
  document.querySelectorAll('.filter-option').forEach(btn => {
    btn.classList.remove('active');
    if (btn.dataset.value === 'all') btn.classList.add('active');
  });
  updateFilterCount();
  applyMobileFilters();
}

function applyMobileFilters() {
  // Apply status filter
  if (activeFilters.status !== 'all') {
    const statusDropdown = document.getElementById('receipt-status-filter');
    if (statusDropdown) {
      statusDropdown.value = activeFilters.status;
      statusDropdown.dispatchEvent(new Event('change'));
    }
  }

  // Apply business filter
  if (activeFilters.business !== 'all') {
    const bizDropdown = document.getElementById('business-filter');
    if (bizDropdown) {
      bizDropdown.value = activeFilters.business;
      bizDropdown.dispatchEvent(new Event('change'));
    }
  }

  // Trigger data refresh if available
  if (typeof applyFilters === 'function') {
    applyFilters();
  }

  closeFilterSheet();

  // Haptic feedback
  if ('vibrate' in navigator) navigator.vibrate(20);
}

// Pull to Refresh (simplified implementation)
let pullStartY = 0;
let isPulling = false;

if ('ontouchstart' in window) {
  const tableWrap = document.querySelector('.table-wrap');
  if (tableWrap) {
    tableWrap.addEventListener('touchstart', (e) => {
      if (tableWrap.scrollTop === 0) {
        pullStartY = e.touches[0].clientY;
        isPulling = true;
      }
    }, { passive: true });

    tableWrap.addEventListener('touchmove', (e) => {
      if (!isPulling) return;
      const pullDistance = e.touches[0].clientY - pullStartY;
      if (pullDistance > 60 && pullDistance < 150) {
        document.getElementById('pull-refresh-indicator').classList.add('pulling');
      }
    }, { passive: true });

    tableWrap.addEventListener('touchend', () => {
      const indicator = document.getElementById('pull-refresh-indicator');
      if (indicator.classList.contains('pulling')) {
        indicator.classList.remove('pulling');
        indicator.classList.add('refreshing');

        // Haptic feedback
        if ('vibrate' in navigator) navigator.vibrate([20, 50, 20]);

        // Trigger refresh
        if (typeof loadData === 'function') {
          loadData().then(() => {
            indicator.classList.remove('refreshing');
          }).catch(() => {
            indicator.classList.remove('refreshing');
          });
        } else {
          setTimeout(() => indicator.classList.remove('refreshing'), 1000);
        }
      }
      isPulling = false;
    }, { passive: true });
  }
}

// Handle swipe-to-close for filter sheet
let sheetStartY = 0;
const filterSheet = document.getElementById('filter-sheet');
if (filterSheet) {
  filterSheet.addEventListener('touchstart', (e) => {
    if (e.target.closest('.filter-sheet-handle') || e.target.closest('.filter-sheet-header')) {
      sheetStartY = e.touches[0].clientY;
    }
  }, { passive: true });

  filterSheet.addEventListener('touchmove', (e) => {
    if (sheetStartY === 0) return;
    const diff = e.touches[0].clientY - sheetStartY;
    if (diff > 0) {
      filterSheet.style.transform = `translateY(${diff}px)`;
    }
  }, { passive: true });

  filterSheet.addEventListener('touchend', (e) => {
    if (sheetStartY === 0) return;
    const diff = e.changedTouches[0].clientY - sheetStartY;
    filterSheet.style.transform = '';
    if (diff > 100) {
      closeFilterSheet();
    }
    sheetStartY = 0;
  }, { passive: true });
}
