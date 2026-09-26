/**
 * Wallpaper Manager - Single Unified View Application Logic
 * Supports Singular Delete & Batch Delete from Main, Cache, and Index together.
 */

(function () {
  'use strict';

  // --- STATE ---
  const state = {
    search: '',
    category: 'all',
    orientation: 'all',
    sort: 'newest',
    page: 1,
    limit: 48,
    items: [],
    total: 0,
    totalPages: 1,
    stats: null,
    selectedItems: new Map(), // file_name -> item object
    pendingDelete: null,      // items array to delete
    currentPreviewItem: null
  };

  // --- DOM ELEMENTS ---
  const el = {
    // Header Stats
    statCount: document.getElementById('stat-count'),
    statMain: document.getElementById('stat-main'),
    statCache: document.getElementById('stat-cache'),
    btnRefresh: document.getElementById('btn-refresh'),

    // Toolbar
    inputSearch: document.getElementById('input-search'),
    btnClearSearch: document.getElementById('btn-clear-search'),
    selectCategory: document.getElementById('select-category'),
    selectOrientation: document.getElementById('select-orientation'),
    selectSort: document.getElementById('select-sort'),
    selectPageSize: document.getElementById('select-page-size'),
    categoryChipsBar: document.getElementById('category-chips-bar'),
    btnSelectAll: document.getElementById('btn-select-all'),
    btnDeselectAllTop: document.getElementById('btn-deselect-all-top'),

    // Gallery
    resultsCount: document.getElementById('results-count'),
    wallpaperGrid: document.getElementById('wallpaper-grid'),
    pagination: document.getElementById('pagination'),

    // Batch Bar
    batchBar: document.getElementById('batch-bar'),
    batchCount: document.getElementById('batch-count'),
    batchSavingsText: document.getElementById('batch-savings-text'),
    btnBatchClear: document.getElementById('btn-batch-clear'),
    btnBatchDelete: document.getElementById('btn-batch-delete'),

    // Delete Modal
    modalDelete: document.getElementById('modal-delete'),
    deleteTitle: document.getElementById('delete-title'),
    deleteSubtitle: document.getElementById('delete-subtitle'),
    delPreviewImg: document.getElementById('del-preview-img'),
    delPreviewTitle: document.getElementById('del-preview-title'),
    delPreviewSpace: document.getElementById('del-preview-space'),
    delMainPath: document.getElementById('del-main-path'),
    delCachePath: document.getElementById('del-cache-path'),
    btnCancelDel: document.getElementById('btn-cancel-del'),
    btnConfirmDel: document.getElementById('btn-confirm-del'),
    btnConfirmText: document.getElementById('btn-confirm-text'),
    delSpinner: document.getElementById('del-spinner'),

    // Preview Lightbox
    modalPreview: document.getElementById('modal-preview'),
    btnClosePreview: document.getElementById('btn-close-preview'),
    lbImage: document.getElementById('lb-image'),
    lbLoader: document.getElementById('lb-loader'),
    lbTitle: document.getElementById('lb-title'),
    lbFilename: document.getElementById('lb-filename'),
    lbResolution: document.getElementById('lb-resolution'),
    lbDimensions: document.getElementById('lb-dimensions'),
    lbMainSize: document.getElementById('lb-main-size'),
    lbCacheSize: document.getElementById('lb-cache-size'),
    lbDescSection: document.getElementById('lb-desc-section'),
    lbDescription: document.getElementById('lb-description'),
    lbTagsSection: document.getElementById('lb-tags-section'),
    lbTags: document.getElementById('lb-tags'),
    lbBtnOriginal: document.getElementById('lb-btn-original'),
    lbBtnDelete: document.getElementById('lb-btn-delete'),

    // Toasts
    toastShelf: document.getElementById('toast-shelf')
  };

  // --- TOAST ALERTS ---
  function showToast(message, type = 'info', duration = 3600) {
    const toast = document.createElement('div');
    toast.className = `toast-msg ${type}`;
    const icon = type === 'success' ? '✅' : (type === 'error' ? '❌' : 'ℹ️');
    toast.innerHTML = `<span>${icon}</span><span>${message}</span>`;
    el.toastShelf.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  // --- API CALLS ---
  const api = {
    async getStats() {
      const res = await fetch('/api/stats');
      if (!res.ok) throw new Error('Stats request failed');
      return await res.json();
    },

    async getWallpapers(params) {
      const q = new URLSearchParams(params).toString();
      const res = await fetch(`/api/wallpapers?${q}`);
      if (!res.ok) throw new Error('Wallpapers request failed');
      return await res.json();
    },

    async deleteWallpapers(fileNames) {
      const res = await fetch('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_names: fileNames,
          delete_main: true,
          delete_cache: true,
          delete_index: true
        }),
        signal: AbortSignal.timeout ? AbortSignal.timeout(15000) : undefined
      });
      const data = await res.json();
      return { ok: res.ok, data };
    },

    async refresh() {
      const res = await fetch('/api/refresh', { method: 'POST' });
      return await res.json();
    }
  };

  // --- INITIALIZATION ---
  async function init() {
    setupEventListeners();
    await loadStats();
    await loadWallpapers();
  }

  // --- EVENT HANDLERS ---
  function setupEventListeners() {
    // Refresh Button
    el.btnRefresh.addEventListener('click', async () => {
      showToast('Rescanning storage directories...', 'info');
      try {
        await api.refresh();
        await loadStats();
        await loadWallpapers();
        showToast('Storage refreshed successfully', 'success');
      } catch (err) {
        showToast(`Refresh error: ${err.message}`, 'error');
      }
    });

    // Search with debounce
    let searchDebounce;
    el.inputSearch.addEventListener('input', (e) => {
      const val = e.target.value;
      el.btnClearSearch.classList.toggle('hidden', !val);

      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        state.search = val;
        state.page = 1;
        loadWallpapers();
      }, 250);
    });

    el.btnClearSearch.addEventListener('click', () => {
      el.inputSearch.value = '';
      el.btnClearSearch.classList.add('hidden');
      state.search = '';
      state.page = 1;
      loadWallpapers();
      el.inputSearch.focus();
    });

    // Dropdowns
    el.selectCategory.addEventListener('change', (e) => {
      state.category = e.target.value;
      state.page = 1;
      updateActiveCategoryChip();
      loadWallpapers();
    });

    el.selectOrientation.addEventListener('change', (e) => {
      state.orientation = e.target.value;
      state.page = 1;
      loadWallpapers();
    });

    el.selectSort.addEventListener('change', (e) => {
      state.sort = e.target.value;
      state.page = 1;
      loadWallpapers();
    });

    el.selectPageSize.addEventListener('change', (e) => {
      state.limit = parseInt(e.target.value, 10);
      state.page = 1;
      loadWallpapers();
    });

    // Selection buttons
    el.btnSelectAll.addEventListener('click', () => {
      state.items.forEach(item => {
        state.selectedItems.set(item.file_name, item);
      });
      syncCardCheckboxes();
      updateBatchBar();
    });

    el.btnDeselectAllTop.addEventListener('click', clearSelection);
    el.btnBatchClear.addEventListener('click', clearSelection);

    // Batch Delete
    el.btnBatchDelete.addEventListener('click', () => {
      if (state.selectedItems.size === 0) return;
      openDeleteModal(Array.from(state.selectedItems.values()));
    });

    // Delete Modal Actions
    el.btnCancelDel.addEventListener('click', closeDeleteModal);
    el.modalDelete.addEventListener('click', (e) => {
      if (e.target === el.modalDelete) closeDeleteModal();
    });
    el.btnConfirmDel.addEventListener('click', executeDelete);

    // Lightbox Modal Actions
    el.btnClosePreview.addEventListener('click', closePreviewModal);
    el.modalPreview.addEventListener('click', (e) => {
      if (e.target === el.modalPreview) closePreviewModal();
    });
    el.lbBtnDelete.addEventListener('click', () => {
      if (state.currentPreviewItem) {
        const itemToDelete = state.currentPreviewItem;
        closePreviewModal();
        openDeleteModal([itemToDelete]);
      }
    });

    // Keyboard Shortcuts
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (!el.modalDelete.classList.contains('hidden')) closeDeleteModal();
        else if (!el.modalPreview.classList.contains('hidden')) closePreviewModal();
        else if (state.selectedItems.size > 0) clearSelection();
      } else if (e.key === '/' && document.activeElement !== el.inputSearch) {
        e.preventDefault();
        el.inputSearch.focus();
      }
    });
  }

  // --- STATS & CHIPS POPULATION ---
  async function loadStats() {
    try {
      const stats = await api.getStats();
      state.stats = stats;

      el.statCount.textContent = stats.total_index.toLocaleString();
      el.statMain.textContent = stats.total_main_formatted;
      el.statCache.textContent = stats.total_cache_formatted;

      // Populate Category Dropdown
      const currentCat = el.selectCategory.value;
      el.selectCategory.innerHTML = `<option value="all">All Categories</option>`;
      stats.categories.forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat.name;
        opt.textContent = `${cat.name} (${cat.count})`;
        el.selectCategory.appendChild(opt);
      });
      if (currentCat) el.selectCategory.value = currentCat;

      // Populate Category Chips
      el.categoryChipsBar.innerHTML = '';
      const allChip = document.createElement('button');
      allChip.className = `chip ${state.category === 'all' ? 'active' : ''}`;
      allChip.innerHTML = `<span>All</span><span class="chip-count">${stats.total_index}</span>`;
      allChip.addEventListener('click', () => {
        state.category = 'all';
        el.selectCategory.value = 'all';
        state.page = 1;
        updateActiveCategoryChip();
        loadWallpapers();
      });
      el.categoryChipsBar.appendChild(allChip);

      stats.categories.forEach(cat => {
        const chip = document.createElement('button');
        chip.className = `chip ${state.category === cat.name ? 'active' : ''}`;
        chip.innerHTML = `<span>${cat.name}</span><span class="chip-count">${cat.count}</span>`;
        chip.addEventListener('click', () => {
          state.category = cat.name;
          el.selectCategory.value = cat.name;
          state.page = 1;
          updateActiveCategoryChip();
          loadWallpapers();
        });
        el.categoryChipsBar.appendChild(chip);
      });

    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  }

  function updateActiveCategoryChip() {
    const chips = el.categoryChipsBar.querySelectorAll('.chip');
    chips.forEach(chip => {
      const label = chip.querySelector('span:first-child').textContent;
      const isActive = (state.category === 'all' && label === 'All') || (state.category === label);
      chip.classList.toggle('active', isActive);
    });
  }

  // --- WALLPAPERS GALLERY ---
  async function loadWallpapers() {
    el.resultsCount.innerHTML = `<span>Loading wallpapers...</span>`;
    try {
      const res = await api.getWallpapers({
        search: state.search,
        category: state.category,
        orientation: state.orientation,
        sort: state.sort,
        page: state.page,
        limit: state.limit
      });

      state.items = res.items;
      state.total = res.total;
      state.totalPages = res.total_pages;

      renderGrid(res.items);
      renderPagination(res.total, res.page, res.limit);

      el.resultsCount.innerHTML = `Showing <strong>${res.items.length}</strong> of <strong>${res.total.toLocaleString()}</strong> wallpapers (Page ${res.page}/${res.total_pages})`;
      syncCardCheckboxes();
    } catch (err) {
      el.resultsCount.textContent = `Error loading wallpapers: ${err.message}`;
    }
  }

  function renderGrid(items) {
    el.wallpaperGrid.innerHTML = '';

    if (items.length === 0) {
      el.wallpaperGrid.innerHTML = `
        <div style="grid-column: 1 / -1; text-align: center; padding: 60px 20px; color: var(--text-muted);">
          <div style="font-size: 3rem; margin-bottom: 12px;">🔍</div>
          <h3>No wallpapers found</h3>
          <p>Try clearing your search query or choosing another category.</p>
        </div>`;
      return;
    }

    items.forEach(item => {
      const card = document.createElement('div');
      card.className = 'wp-card';
      const isSelected = state.selectedItems.has(item.file_name);
      if (isSelected) card.classList.add('selected');

      // 1. Checkbox for Batch Delete Selection
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'card-select-checkbox';
      checkbox.checked = isSelected;
      checkbox.title = 'Select for batch delete';
      checkbox.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleSelection(item, checkbox.checked);
        card.classList.toggle('selected', checkbox.checked);
      });

      // 2. Singular Delete Button (Trash Can)
      const trashBtn = document.createElement('button');
      trashBtn.className = 'card-trash-btn';
      trashBtn.title = 'Delete from Main, Cache & Index';
      trashBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>`;
      trashBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        openDeleteModal([item]);
      });

      // 3. Thumbnail (Loaded from cache/ with fallback to main/)
      const imgWrap = document.createElement('div');
      imgWrap.className = 'card-img-wrap';

      const hasValidCache = item.file_cache_name && item.cache_exists;
      if (hasValidCache) {
        const img = document.createElement('img');
        img.className = 'card-thumb';
        img.loading = 'lazy';
        img.src = `/cache/${encodeURIComponent(item.file_cache_name)}`;
        img.alt = item.file_name;
        img.onerror = () => {
          if (item.file_main_name) {
            img.src = `/main/${encodeURIComponent(item.file_main_name)}`;
          } else {
            imgWrap.innerHTML = `<div class="thumb-fallback">⚠️ Image Missing</div>`;
          }
        };
        imgWrap.appendChild(img);
      } else if (item.file_main_name) {
        const img = document.createElement('img');
        img.className = 'card-thumb';
        img.loading = 'lazy';
        img.src = `/main/${encodeURIComponent(item.file_main_name)}`;
        img.alt = item.file_name;
        imgWrap.appendChild(img);
      } else {
        imgWrap.innerHTML = `<div class="thumb-fallback">⚠️ Image Missing</div>`;
      }

      // 4. Card Details
      const details = document.createElement('div');
      details.className = 'card-details';

      const displayName = item.data?.suggested_filename || item.file_name || 'Untitled';
      details.innerHTML = `
        <h4 class="card-title" title="${displayName}">${displayName}</h4>
        <div class="card-meta">
          <span class="badge-res">${item.resolution || 'HD'}</span>
          <span>${item.category || '#wall'}</span>
          <span class="card-size">${item.main_size_formatted || ''}</span>
        </div>`;

      // Assemble
      card.appendChild(checkbox);
      card.appendChild(trashBtn);
      card.appendChild(imgWrap);
      card.appendChild(details);

      // Card Click -> Open Lightbox Preview
      card.addEventListener('click', () => {
        openPreviewModal(item);
      });

      el.wallpaperGrid.appendChild(card);
    });
  }

  // --- SELECTION & BATCH BAR ---
  function toggleSelection(item, isSelected) {
    if (isSelected) {
      state.selectedItems.set(item.file_name, item);
    } else {
      state.selectedItems.delete(item.file_name);
    }
    updateBatchBar();
  }

  function clearSelection() {
    state.selectedItems.clear();
    syncCardCheckboxes();
    updateBatchBar();
  }

  function syncCardCheckboxes() {
    const cards = el.wallpaperGrid.querySelectorAll('.wp-card');
    cards.forEach((card, idx) => {
      const item = state.items[idx];
      if (!item) return;
      const isSel = state.selectedItems.has(item.file_name);
      const cb = card.querySelector('.card-select-checkbox');
      if (cb) cb.checked = isSel;
      card.classList.toggle('selected', isSel);
    });
  }

  function updateBatchBar() {
    const count = state.selectedItems.size;
    el.batchCount.textContent = count;
    el.btnDeselectAllTop.classList.toggle('hidden', count === 0);

    if (count > 0) {
      el.batchBar.classList.remove('hidden');

      let totalBytes = 0;
      state.selectedItems.forEach(item => {
        totalBytes += (item.main_size || 0) + (item.cache_size || 0);
      });
      el.batchSavingsText.textContent = `(~${formatBytes(totalBytes)} to reclaim)`;
    } else {
      el.batchBar.classList.add('hidden');
    }
  }

  // --- PAGINATION ---
  function renderPagination(total, page, limit) {
    el.pagination.innerHTML = '';
    const totalPages = Math.ceil(total / limit) || 1;
    if (totalPages <= 1) return;

    // Prev
    const btnPrev = document.createElement('button');
    btnPrev.className = 'btn-page';
    btnPrev.innerHTML = '&laquo; Prev';
    btnPrev.disabled = page <= 1;
    btnPrev.addEventListener('click', () => {
      state.page = page - 1;
      loadWallpapers();
      window.scrollTo({ top: 120, behavior: 'smooth' });
    });
    el.pagination.appendChild(btnPrev);

    // Number Buttons
    const maxButtons = 7;
    let start = Math.max(1, page - 3);
    let end = Math.min(totalPages, start + maxButtons - 1);
    if (end - start < maxButtons - 1) {
      start = Math.max(1, end - maxButtons + 1);
    }

    for (let p = start; p <= end; p++) {
      const btnP = document.createElement('button');
      btnP.className = `btn-page ${p === page ? 'active' : ''}`;
      btnP.textContent = p;
      btnP.addEventListener('click', () => {
        state.page = p;
        loadWallpapers();
        window.scrollTo({ top: 120, behavior: 'smooth' });
      });
      el.pagination.appendChild(btnP);
    }

    // Next
    const btnNext = document.createElement('button');
    btnNext.className = 'btn-page';
    btnNext.innerHTML = 'Next &raquo;';
    btnNext.disabled = page >= totalPages;
    btnNext.addEventListener('click', () => {
      state.page = page + 1;
      loadWallpapers();
      window.scrollTo({ top: 120, behavior: 'smooth' });
    });
    el.pagination.appendChild(btnNext);
  }

  // --- DELETE MODAL & EXECUTION ---
  function openDeleteModal(items) {
    state.pendingDelete = items;
    const count = items.length;

    if (count === 1) {
      const item = items[0];
      const title = item.data?.suggested_filename || item.file_name;
      el.deleteTitle.textContent = `Delete "${title}"?`;
      el.deleteSubtitle.textContent = `This will permanently delete from main storage, cache, and index.json.`;

      // Thumbnail
      if (item.file_cache_name && item.cache_exists) {
        el.delPreviewImg.src = `/cache/${encodeURIComponent(item.file_cache_name)}`;
        el.delPreviewImg.style.display = 'block';
      } else if (item.file_main_name) {
        el.delPreviewImg.src = `/main/${encodeURIComponent(item.file_main_name)}`;
        el.delPreviewImg.style.display = 'block';
      } else {
        el.delPreviewImg.style.display = 'none';
      }

      el.delPreviewTitle.textContent = title;
      const space = (item.main_size || 0) + (item.cache_size || 0);
      el.delPreviewSpace.textContent = `Reclaims: ~${formatBytes(space)}`;

      el.delMainPath.textContent = item.file_main_name ? `main/${item.file_main_name}` : 'Not in main';
      el.delCachePath.textContent = item.file_cache_name ? `cache/${item.file_cache_name}` : 'Not in cache';
      el.btnConfirmText.textContent = 'Delete Wallpaper';
    } else {
      el.deleteTitle.textContent = `Delete ${count} Selected Wallpapers?`;
      el.deleteSubtitle.textContent = `This will permanently delete all ${count} wallpapers from main storage, cache, and index.json.`;

      const firstItem = items[0];
      if (firstItem.file_cache_name && firstItem.cache_exists) {
        el.delPreviewImg.src = `/cache/${encodeURIComponent(firstItem.file_cache_name)}`;
        el.delPreviewImg.style.display = 'block';
      } else {
        el.delPreviewImg.style.display = 'none';
      }

      el.delPreviewTitle.textContent = `${count} Wallpapers Selected`;
      let space = 0;
      items.forEach(i => { space += (i.main_size || 0) + (i.cache_size || 0); });
      el.delPreviewSpace.textContent = `Total Reclaim: ~${formatBytes(space)}`;

      el.delMainPath.textContent = `All ${count} files in main/`;
      el.delCachePath.textContent = `All ${count} files in cache/`;
      el.btnConfirmText.textContent = `Delete ${count} Wallpapers`;
    }

    el.delSpinner.classList.add('hidden');
    el.btnConfirmDel.disabled = false;
    el.modalDelete.classList.remove('hidden');
  }

  function closeDeleteModal() {
    el.modalDelete.classList.add('hidden');
    state.pendingDelete = null;
  }

  async function executeDelete() {
    if (!state.pendingDelete || state.pendingDelete.length === 0) return;

    const items = state.pendingDelete;
    const fileNames = items.map(i => i.file_name);

    el.btnConfirmDel.disabled = true;
    el.delSpinner.classList.remove('hidden');
    el.btnConfirmText.textContent = 'Deleting...';

    try {
      const result = await api.deleteWallpapers(fileNames);

      if (result.ok && result.data.success) {
        showToast(result.data.message || `Successfully deleted ${items.length} wallpapers`, 'success', 4500);

        // Remove deleted items from selected list
        items.forEach(i => state.selectedItems.delete(i.file_name));
        updateBatchBar();

        closeDeleteModal();

        // Refresh stats & gallery
        await loadStats();
        await loadWallpapers();
      } else {
        showToast(result.data.message || 'Deletion failed', 'error', 5000);
      }
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, 'error', 5000);
    } finally {
      el.btnConfirmDel.disabled = false;
      el.delSpinner.classList.add('hidden');
      el.btnConfirmText.textContent = 'Delete Permanently';
    }
  }

  // --- PREVIEW LIGHTBOX ---
  function openPreviewModal(item) {
    state.currentPreviewItem = item;
    const data = item.data || {};
    const title = data.suggested_filename || item.file_name;

    el.lbTitle.textContent = title;
    el.lbFilename.textContent = item.file_name;

    el.lbResolution.textContent = item.resolution || 'HD';
    el.lbDimensions.textContent = (item.width && item.height) ? `${item.width} × ${item.height}` : '-';
    el.lbMainSize.textContent = item.main_size_formatted || '-';
    el.lbCacheSize.textContent = item.cache_size_formatted || '-';

    // Scene description
    if (data.scene_description) {
      el.lbDescSection.style.display = 'block';
      el.lbDescription.textContent = data.scene_description;
    } else {
      el.lbDescSection.style.display = 'none';
    }

    // Tags
    el.lbTags.innerHTML = '';
    const tags = data.tags || [];
    if (tags.length > 0) {
      el.lbTagsSection.style.display = 'block';
      tags.forEach(t => {
        const span = document.createElement('span');
        span.className = 'lb-tag';
        span.textContent = `#${t}`;
        el.lbTags.appendChild(span);
      });
    } else {
      el.lbTagsSection.style.display = 'none';
    }

    // Open Original Link
    if (item.file_main_name) {
      el.lbBtnOriginal.href = `/main/${encodeURIComponent(item.file_main_name)}`;
      el.lbBtnOriginal.style.display = 'inline-flex';
    } else {
      el.lbBtnOriginal.style.display = 'none';
    }

    // Load Image
    el.lbLoader.classList.remove('hidden');
    el.lbImage.style.opacity = '0.2';

    const targetUrl = item.file_main_name
      ? `/main/${encodeURIComponent(item.file_main_name)}`
      : `/cache/${encodeURIComponent(item.file_cache_name)}`;

    el.lbImage.onload = () => {
      el.lbLoader.classList.add('hidden');
      el.lbImage.style.opacity = '1';
    };
    el.lbImage.onerror = () => {
      el.lbLoader.classList.add('hidden');
      el.lbImage.style.opacity = '1';
    };
    el.lbImage.src = targetUrl;

    el.modalPreview.classList.remove('hidden');
  }

  function closePreviewModal() {
    el.modalPreview.classList.add('hidden');
    state.currentPreviewItem = null;
  }

  // --- HELPERS ---
  function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  // Start app
  document.addEventListener('DOMContentLoaded', init);
})();
