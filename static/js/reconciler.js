// Global state
let csvData = [];
let filteredData = [];
let selectedRow = null;
let sortColumn = 'Chase Date';
let sortAsc = true;
let panzoomInstance = null;
let currentRotation = 0;
let wheelHandler = null; // Prevent duplicate wheel listeners

// Undo system
let undoStack = [];
const MAX_UNDO_STACK = 50;

// Debug mode - set to false in production
const DEBUG_MODE = false;
function debugLog(...args) {
  if (DEBUG_MODE) console.log(...args);
}

// ============================================
// Security: HTML escaping to prevent XSS
// ============================================
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[char]));
}

// ============================================
// Loading States and Error Handling
// ============================================
let activeLoaders = 0;
let loadingOverlay = null;

function createLoadingOverlay() {
  if (loadingOverlay) return loadingOverlay;
  loadingOverlay = document.createElement('div');
  loadingOverlay.id = 'global-loading-overlay';
  loadingOverlay.innerHTML = `
    <div class="loading-spinner"></div>
    <div class="loading-text">Loading...</div>
  `;
  loadingOverlay.style.cssText = `
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.5);
    z-index: 10000;
    justify-content: center;
    align-items: center;
    flex-direction: column;
  `;
  const style = document.createElement('style');
  style.textContent = `
    .loading-spinner {
      width: 40px;
      height: 40px;
      border: 4px solid #f3f3f3;
      border-top: 4px solid #3498db;
      border-radius: 50%;
      animation: spin 1s linear infinite;
    }
    @keyframes spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }
    .loading-text {
      color: white;
      margin-top: 16px;
      font-size: 14px;
    }
  `;
  document.head.appendChild(style);
  document.body.appendChild(loadingOverlay);
  return loadingOverlay;
}

function showLoading(text = 'Loading...') {
  activeLoaders++;
  const overlay = createLoadingOverlay();
  const textEl = overlay.querySelector('.loading-text');
  if (textEl) textEl.textContent = text;
  overlay.style.display = 'flex';
}

function hideLoading() {
  activeLoaders = Math.max(0, activeLoaders - 1);
  if (activeLoaders === 0 && loadingOverlay) {
    loadingOverlay.style.display = 'none';
  }
}

// Wrapper for fetch with loading states and error handling
async function fetchWithLoading(url, options = {}, loadingText = 'Loading...') {
  showLoading(loadingText);
  try {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unknown error');
      throw new Error(`HTTP ${response.status}: ${errorText.slice(0, 100)}`);
    }
    return response;
  } catch (error) {
    // Network errors, timeouts, etc.
    if (error.name === 'TypeError' && error.message.includes('fetch')) {
      showToast('Network error - check your connection', '❌');
    } else if (!error.message.startsWith('HTTP')) {
      showToast(`Request failed: ${error.message}`, '❌');
    }
    throw error;
  } finally {
    hideLoading();
  }
}

// Retry wrapper for critical operations
async function fetchWithRetry(url, options = {}, maxRetries = 2, loadingText = 'Loading...') {
  let lastError;
  for (let i = 0; i <= maxRetries; i++) {
    try {
      return await fetchWithLoading(url, options, i > 0 ? `${loadingText} (retry ${i}/${maxRetries})` : loadingText);
    } catch (error) {
      lastError = error;
      if (i < maxRetries) {
        await new Promise(r => setTimeout(r, 1000 * (i + 1))); // Exponential backoff
      }
    }
  }
  throw lastError;
}

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
  await loadCSV();
  setupEventListeners();
  setupDragDrop();
  setupResizer();
  loadTheme();
  updateIncomingBadge();  // Show pending incoming receipts count

  // Handle URL parameters for navigation (e.g., /?page=reports)
  const urlParams = new URLSearchParams(window.location.search);
  const requestedPage = urlParams.get('page');
  if (requestedPage && ['home', 'reports', 'stats'].includes(requestedPage)) {
    switchPage(requestedPage);
  }

  showToast('System ready! Press ? for keyboard shortcuts', '🚀');
});

// Fetch and display incoming receipts badge count
async function updateIncomingBadge() {
  try {
    const res = await fetch('/api/incoming/receipts?status=pending&limit=1', { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById('incoming-badge');
    if (!badge) return;
    const pendingCount = data.counts?.pending || 0;
    if (pendingCount > 0) {
      badge.textContent = pendingCount;
      badge.style.display = 'block';
    } else {
      badge.style.display = 'none';
    }
  } catch (e) {
    debugLog('Could not fetch incoming badge count:', e.message);
  }
}

// API calls
async function loadCSV() {
  try {
    const res = await fetchWithLoading('/api/transactions', {}, 'Loading transactions...');
    const data = await res.json();
    csvData = data || [];  // Server returns array directly from MySQL
    // Re-apply existing filters instead of resetting
    applyFilters();  // This calls renderTable() + updateDashboard() internally
    showToast(`Loaded ${csvData.length} transactions`, '📊');
  } catch (e) {
    showToast('Failed to load transactions: ' + e.message, '❌');
    csvData = [];
    applyFilters();
  }
}

async function saveCSV() {
  // NOTE: Server auto-saves on each update_row call
  // This function kept for Ctrl+S hotkey compatibility
  showToast('Changes are auto-saved on each update', '✓');
}

async function aiMatch() {
  if (!selectedRow) return showToast('Select a transaction first', '⚠️');

  // Save undo state BEFORE making changes
  const oldData = {
    'Receipt File': selectedRow['Receipt File'] || '',
    'ai_receipt_merchant': selectedRow['ai_receipt_merchant'] || '',
    'ai_receipt_date': selectedRow['ai_receipt_date'] || '',
    'ai_receipt_total': selectedRow['ai_receipt_total'] || '',
    'AI Confidence': selectedRow['AI Confidence'] || '',
    'mi_merchant': selectedRow['mi_merchant'] || '',
    'mi_category': selectedRow['mi_category'] || '',
    'mi_description': selectedRow['mi_description'] || '',
    'mi_confidence': selectedRow['mi_confidence'] || ''
  };

  showToast('🔍 Finding receipt...', '🔍');
  try {
    const res = await fetch('/ai_match', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({_index: selectedRow._index})
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.ok) {
      // Save undo state
      saveUndoState('AI Receipt Match + MI', selectedRow._index, oldData);

      // Update selected row with matched receipt data
      Object.assign(selectedRow, data.result);
      renderTable();
      loadReceipt();

      // Show detailed success message
      const confidence = data.result['AI Confidence'] || data.result['ai_confidence'] || 0;
      const receiptFile = data.result['Receipt File'] || '';
      const fileName = receiptFile.split('/').pop();

      showToast(`✅ Receipt matched! ${fileName} (${Math.round(confidence)}%) - Running Donut OCR...`, '🔄', 3000);

      // Now run Donut OCR + MI processing on the matched receipt
      try {
        const miRes = await fetch('/process_mi_ocr', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({_index: selectedRow._index})
        });
        const miData = await miRes.json();
        if (miData.ok) {
          // Update with MI results
          if (miData.result) {
            selectedRow.mi_merchant = miData.result.mi_merchant || selectedRow.mi_merchant;
            selectedRow.mi_category = miData.result.mi_category || selectedRow.mi_category;
            selectedRow.mi_description = miData.result.mi_description || selectedRow.mi_description;
            selectedRow.mi_confidence = miData.result.mi_confidence || selectedRow.mi_confidence;
            selectedRow.mi_is_subscription = miData.result.mi_is_subscription || 0;
            selectedRow.mi_subscription_name = miData.result.mi_subscription_name || '';
          }
          renderTable();

          const usedOcr = miData.used_ocr ? '🍩 Donut' : '📋 Pattern';
          const miConf = Math.round((miData.result?.mi_confidence || 0) * 100);
          showToast(`✅ Complete! ${usedOcr}: ${miData.result?.mi_merchant || 'Unknown'} (${miConf}%) - Ctrl+Z to undo`, '✅', 5000);
        } else {
          showToast(`⚠️ Receipt matched but MI failed: ${miData.message}`, '⚠️', 4000);
        }
      } catch (miError) {
        showToast(`⚠️ Receipt matched but MI error: ${miError.message}`, '⚠️', 4000);
      }
    } else {
      // No receipt found - still run MI with pattern matching
      showToast(`❌ No receipt found - running pattern MI...`, '🔄', 2000);

      try {
        const miRes = await fetch('/process_mi_ocr', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({_index: selectedRow._index})
        });
        const miData = await miRes.json();
        if (miData.ok && miData.result) {
          // Save undo state for MI-only change
          saveUndoState('MI Pattern Match', selectedRow._index, oldData);

          selectedRow.mi_merchant = miData.result.mi_merchant || '';
          selectedRow.mi_category = miData.result.mi_category || '';
          selectedRow.mi_description = miData.result.mi_description || '';
          selectedRow.mi_confidence = miData.result.mi_confidence || 0;
          renderTable();

          const miConf = Math.round((miData.result.mi_confidence || 0) * 100);
          showToast(`📋 No receipt, but MI processed: ${miData.result.mi_merchant} (${miConf}%)`, '📋', 4000);
        }
      } catch (e) {
        showToast(`❌ ${data.message || 'No receipt found'}`, '❌', 4000);
      }
    }
  } catch (e) {
    showToast(`❌ AI Match failed: ${e.message}`, '❌');
  }
}

async function aiNote() {
  if (!selectedRow) return showToast('Select a transaction first', '⚠️');

  showToast('Generating AI note...', '✍️');
  try {
    const res = await fetch('/ai_note', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({_index: selectedRow._index})
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.ok) {
      selectedRow.Notes = data.note;
      renderTable();
      showToast('AI note generated', '✓');
    }
  } catch (e) {
    showToast('AI Note failed: ' + e.message, '❌');
  }
}

// Undo system functions
function saveUndoState(action, transactionIndex, oldData) {
  const undoEntry = {
    action,
    transactionIndex,
    oldData: {...oldData}, // Clone the old data
    timestamp: Date.now()
  };

  undoStack.push(undoEntry);

  // Limit stack size
  if (undoStack.length > MAX_UNDO_STACK) {
    undoStack.shift(); // Remove oldest entry
  }

  debugLog(`Undo state saved: ${action} for transaction ${transactionIndex}`, undoEntry);
}

async function undo() {
  if (undoStack.length === 0) {
    showToast('⚠️ Nothing to undo', '⚠️');
    return;
  }

  const entry = undoStack.pop();

  try {
    showToast(`↩️ Undoing: ${entry.action}...`, '↩️');

    // Restore the old data
    const res = await fetch('/update_row', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        _index: entry.transactionIndex,
        patch: entry.oldData
      })
    });

    if (!res.ok) {
      throw new Error(`Failed to undo: ${res.statusText}`);
    }

    // Update local state
    const rowIndex = csvData.findIndex(r => r._index === entry.transactionIndex);
    if (rowIndex >= 0) {
      Object.assign(csvData[rowIndex], entry.oldData);
      if (selectedRow && selectedRow._index === entry.transactionIndex) {
        Object.assign(selectedRow, entry.oldData);
      }
    }

    renderTable();
    loadReceipt();

    showToast(`✅ Undid: ${entry.action}`, '✅', 3000);

  } catch (e) {
    showToast(`❌ Undo failed: ${e.message}`, '❌');
    // Put entry back on stack since undo failed
    undoStack.push(entry);
  }
}

let batchProcessCancelled = false;

// Process all transactions through Merchant Intelligence
async function processMerchantIntelligence() {
  if (!confirm(`Process all ${csvData.length} transactions through Merchant Intelligence?\n\nThis will:\n- Normalize merchant names\n- Assign categories\n- Detect subscriptions\n- Generate descriptions\n- Match contacts from CRM`)) {
    return;
  }

  showToast('Processing Merchant Intelligence...', '🧠');

  try {
    const response = await fetch('/process_mi', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({all: true})
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();

    if (result.ok) {
      showToast(result.message, '✅');
      // Reload data to show updated MI fields
      await loadCSV();
      applyFilters();
      renderTable();
    } else {
      showToast(result.message || 'MI processing failed', '❌');
    }
  } catch (e) {
    showToast('MI processing error: ' + e.message, '❌');
  }
}

// Smart Search - Intelligent multi-source search with learning
async function smartSearchMissing() {
  const missingRows = csvData.filter(r => !r['Receipt File'] || r['Receipt File'].trim() === '');

  if (missingRows.length === 0) {
    showToast('All transactions have receipts!', '✓');
    return;
  }

  if (!confirm(`Smart Search will find receipts using AI match, Gmail, and iMessage.\n\nProcess ${missingRows.length} missing receipts?\n\nThis may take several minutes.`)) {
    return;
  }

  debugLog(`🔍 Starting Smart Search: ${missingRows.length} receipts to find`);

  batchProcessCancelled = false;

  const modal = document.getElementById('progress-modal');
  modal.classList.add('active');

  document.getElementById('progress-close-btn').style.display = 'none';
  document.getElementById('progress-cancel-btn').style.display = 'block';
  document.getElementById('progress-log').innerHTML = '<div style="color:var(--muted)">🧠 Smart Search: AI → Gmail → iMessage</div>';

  let processed = 0;
  let found = 0;
  const total = missingRows.length;
  const startTime = Date.now();

  // Phase 1: AI Match (try local receipts first)
  addProgressLog('\n🤖 Phase 1: AI matching local receipts...', 'ok');

  for (const row of missingRows) {
    if (batchProcessCancelled) {
      addProgressLog(`\n⚠️ Cancelled! Processed ${processed} of ${total}`, 'bad');
      document.getElementById('progress-cancel-btn').style.display = 'none';
      document.getElementById('progress-close-btn').style.display = 'block';
      showToast(`Cancelled after ${processed} receipts`, '⚠️');
      return;
    }

    try {
      processed++;
      const percent = Math.round((processed / total) * 100);
      updateProgress(processed, found, percent, total);

      // Try AI match first
      const res = await fetch('/ai_match', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({_index: row._index})
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (data.ok && data.result.receipt_file) {
        found++;
        Object.assign(row, data.result);
        row._newlyMatched = true;
        addProgressLog(`✓ ${(row['Chase Description'] || 'Unknown').substring(0, 30)} → AI matched`, 'ok');
        document.getElementById('progress-found').textContent = found;
      }
    } catch (e) {
      console.error(`AI match error:`, e);
    }
  }

  // Get still-missing receipts
  let stillMissing = csvData.filter(r => !r['Receipt File'] || r['Receipt File'].trim() === '');

  if (stillMissing.length === 0) {
    addProgressLog(`\n✅ All receipts found via AI match!`, 'ok');
    finishSmartSearch(found, total, startTime);
    return;
  }

  // Phase 2: Gmail Search
  addProgressLog(`\n📧 Phase 2: Searching Gmail (${stillMissing.length} remaining)...`, 'ok');

  for (const row of stillMissing) {
    if (batchProcessCancelled) break;

    try {
      const res = await fetch('/smart_search_receipt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          _index: row._index,
          merchant: row['Chase Description'],
          amount: row['Chase Amount'],
          date: row['Chase Date'],
          source: 'gmail'
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (data.ok && data.result && data.result.found) {
        found++;
        Object.assign(row, data.result);
        row._newlyMatched = true;
        const source = data.result.source || 'Gmail';
        addProgressLog(`✓ ${(row['Chase Description'] || 'Unknown').substring(0, 30)} → ${source}`, 'ok');
        document.getElementById('progress-found').textContent = found;
      }
    } catch (e) {
      console.error(`Gmail search error:`, e);
    }
  }

  // Get still-missing receipts
  stillMissing = csvData.filter(r => !r['Receipt File'] || r['Receipt File'].trim() === '');

  if (stillMissing.length === 0) {
    addProgressLog(`\n✅ All receipts found!`, 'ok');
    finishSmartSearch(found, total, startTime);
    return;
  }

  // Phase 3: iMessage Search
  addProgressLog(`\n💬 Phase 3: Searching iMessage (${stillMissing.length} remaining)...`, 'ok');

  for (const row of stillMissing) {
    if (batchProcessCancelled) break;

    try {
      const res = await fetch('/smart_search_receipt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          _index: row._index,
          merchant: row['Chase Description'],
          amount: row['Chase Amount'],
          date: row['Chase Date'],
          source: 'imessage'
        })
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      if (data.ok && data.result && data.result.found) {
        found++;
        Object.assign(row, data.result);
        row._newlyMatched = true;
        addProgressLog(`✓ ${(row['Chase Description'] || 'Unknown').substring(0, 30)} → iMessage`, 'ok');
        document.getElementById('progress-found').textContent = found;
      }
    } catch (e) {
      console.error(`iMessage search error:`, e);
    }
  }

  finishSmartSearch(found, total, startTime);
}

function finishSmartSearch(found, total, startTime) {
  const elapsed = Math.round((Date.now() - startTime) / 1000);
  debugLog(`✅ Smart Search complete in ${elapsed}s: Found ${found} of ${total} receipts`);

  addProgressLog(`\n✅ Smart Search complete! Found ${found} of ${total} receipts in ${elapsed}s`, 'ok');
  document.getElementById('progress-cancel-btn').style.display = 'none';
  document.getElementById('progress-close-btn').style.display = 'block';

  showToast(`Smart Search complete: ${found} receipts found`, '✅');

  // Reload to show new receipts
  loadCSV().then(() => {
    applyFilters();
    renderTable();
  });
}

// Gmail Search - Search Gmail for missing receipts
async function searchGmailForMissing() {
  const missingRows = csvData.filter(r => !r['Receipt File'] || r['Receipt File'].trim() === '');

  if (missingRows.length === 0) {
    showToast('All transactions have receipts!', '✓');
    return;
  }

  if (!confirm(`Search Gmail for ${missingRows.length} missing receipts? This may take several minutes.`)) {
    return;
  }

  debugLog(`📧 Starting Gmail search: ${missingRows.length} receipts to find`);

  batchProcessCancelled = false;

  const modal = document.getElementById('progress-modal');
  modal.classList.add('active');

  document.getElementById('progress-close-btn').style.display = 'none';
  document.getElementById('progress-cancel-btn').style.display = 'block';
  document.getElementById('progress-log').innerHTML = '<div style="color:var(--muted)">Searching Gmail accounts...</div>';

  let processed = 0;
  let found = 0;
  const total = missingRows.length;
  const startTime = Date.now();

  for (const row of missingRows) {
    if (batchProcessCancelled) {
      debugLog('❌ Gmail search cancelled');
      addProgressLog(`\n⚠️ Cancelled! Searched ${processed} of ${total}`, 'bad');
      document.getElementById('progress-cancel-btn').style.display = 'none';
      document.getElementById('progress-close-btn').style.display = 'block';
      showToast(`Cancelled after ${processed} receipts`, '⚠️');
      return;
    }

    try {
      processed++;
      const percent = Math.round((processed / total) * 100);
      updateProgress(processed, found, percent, total);

      debugLog(`[${processed}/${total}] Searching Gmail: ${row['Chase Description']?.substring(0, 40) || 'Unknown'}`);

      const res = await fetch('/search_gmail_receipt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          _index: row._index,
          merchant: row['Chase Description'],
          amount: row['Chase Amount'],
          date: row['Chase Date']
        })
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const data = await res.json();

      if (data.ok && data.result && data.result.receipt_file) {
        found++;
        Object.assign(row, data.result);
        row._newlyMatched = true;

        const merchant = row['Chase Description'] || 'Unknown';
        debugLog(`  ✓ Found in Gmail`);
        addProgressLog(`✓ ${merchant.substring(0, 30)} → Found in email`, 'ok');
      } else {
        debugLog(`  ⊘ Not found in Gmail`);
        addProgressLog(`⊘ ${(row['Chase Description'] || 'Unknown').substring(0, 30)} → Not found`, 'muted');
      }

      document.getElementById('progress-found').textContent = found;

    } catch (e) {
      console.error(`  ✗ Error searching Gmail:`, e);
      addProgressLog(`✗ Error: ${e.message}`, 'bad');
    }
  }

  const elapsed = Math.round((Date.now() - startTime) / 1000);
  debugLog(`✅ Gmail search complete in ${elapsed}s: Found ${found} of ${total} receipts`);

  addProgressLog(`\n✅ Complete! Found ${found} receipts in ${elapsed}s`, 'ok');
  document.getElementById('progress-cancel-btn').style.display = 'none';
  document.getElementById('progress-close-btn').style.display = 'block';

  showToast(`Gmail search complete: ${found} receipts found`, '✅');

  await loadCSV();
  applyFilters();
  renderTable();
}

// iMessage Search - Search iMessage for missing receipts
async function searchIMessageForMissing() {
  const missingRows = csvData.filter(r => !r['Receipt File'] || r['Receipt File'].trim() === '');

  if (missingRows.length === 0) {
    showToast('All transactions have receipts!', '✓');
    return;
  }

  if (!confirm(`Search iMessage for ${missingRows.length} missing receipts? This may take several minutes.`)) {
    return;
  }

  debugLog(`💬 Starting iMessage search: ${missingRows.length} receipts to find`);

  batchProcessCancelled = false;

  const modal = document.getElementById('progress-modal');
  modal.classList.add('active');

  document.getElementById('progress-close-btn').style.display = 'none';
  document.getElementById('progress-cancel-btn').style.display = 'block';
  document.getElementById('progress-log').innerHTML = '<div style="color:var(--muted)">Searching iMessage database...</div>';

  let processed = 0;
  let found = 0;
  const total = missingRows.length;
  const startTime = Date.now();

  for (const row of missingRows) {
    if (batchProcessCancelled) {
      debugLog('❌ iMessage search cancelled');
      addProgressLog(`\n⚠️ Cancelled! Searched ${processed} of ${total}`, 'bad');
      document.getElementById('progress-cancel-btn').style.display = 'none';
      document.getElementById('progress-close-btn').style.display = 'block';
      showToast(`Cancelled after ${processed} receipts`, '⚠️');
      return;
    }

    try {
      processed++;
      const percent = Math.round((processed / total) * 100);
      updateProgress(processed, found, percent, total);

      debugLog(`[${processed}/${total}] Searching iMessage: ${row['Chase Description']?.substring(0, 40) || 'Unknown'}`);

      const res = await fetch('/search_imessage_receipt', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          _index: row._index,
          merchant: row['Chase Description'],
          amount: row['Chase Amount'],
          date: row['Chase Date']
        })
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const data = await res.json();

      if (data.ok && data.result && data.result.receipt_file) {
        found++;
        Object.assign(row, data.result);
        row._newlyMatched = true;

        const merchant = row['Chase Description'] || 'Unknown';
        debugLog(`  ✓ Found in iMessage`);
        addProgressLog(`✓ ${merchant.substring(0, 30)} → Found in messages`, 'ok');
      } else {
        debugLog(`  ⊘ Not found in iMessage`);
        addProgressLog(`⊘ ${(row['Chase Description'] || 'Unknown').substring(0, 30)} → Not found`, 'muted');
      }

      document.getElementById('progress-found').textContent = found;

    } catch (e) {
      console.error(`  ✗ Error searching iMessage:`, e);
      addProgressLog(`✗ Error: ${e.message}`, 'bad');
    }
  }

  const elapsed = Math.round((Date.now() - startTime) / 1000);
  debugLog(`✅ iMessage search complete in ${elapsed}s: Found ${found} of ${total} receipts`);

  addProgressLog(`\n✅ Complete! Found ${found} receipts in ${elapsed}s`, 'ok');
  document.getElementById('progress-cancel-btn').style.display = 'none';
  document.getElementById('progress-close-btn').style.display = 'block';

  showToast(`iMessage search complete: ${found} receipts found`, '✅');

  await loadCSV();
  applyFilters();
  renderTable();
}

// Process single transaction through MI
async function processSingleMI(rowIndex) {
  try {
    const response = await fetch('/process_mi', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({_index: rowIndex})
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();

    if (result.ok) {
      showToast(result.message, '✅');
      await loadCSV();
      applyFilters();
      renderTable();
    } else {
      showToast(result.message || 'MI processing failed', '❌');
    }
  } catch (e) {
    showToast('MI error: ' + e.message, '❌');
  }
}

async function findMissingReceipts() {
  // Find rows without receipts
  const missingRows = csvData.filter(r => !r['Receipt File'] || r['Receipt File'].trim() === '');

  if (missingRows.length === 0) {
    showToast('All transactions have receipts!', '✓');
    return;
  }

  if (!confirm(`Process ${missingRows.length} missing receipts? This may take several minutes.`)) {
    return;
  }

  debugLog(`🚀 Starting batch process: ${missingRows.length} receipts to process`);

  // Reset cancel flag
  batchProcessCancelled = false;

  // Show progress modal
  const modal = document.getElementById('progress-modal');
  debugLog('📊 Showing progress modal...');
  modal.classList.add('active');
  debugLog('📊 Modal classList:', modal.classList.toString());
  debugLog('📊 Modal display:', window.getComputedStyle(modal).display);
  debugLog('📊 Modal z-index:', window.getComputedStyle(modal).zIndex);

  document.getElementById('progress-close-btn').style.display = 'none';
  document.getElementById('progress-cancel-btn').style.display = 'block';
  document.getElementById('progress-log').innerHTML = '<div style="color:var(--muted)">Starting batch process...</div>';

  debugLog('✅ Progress modal configuration complete!');

  let processed = 0;
  let found = 0;
  const total = missingRows.length;
  const startTime = Date.now();

  // Process each row individually so we can show progress
  for (const row of missingRows) {
    // Check if cancelled
    if (batchProcessCancelled) {
      debugLog('❌ Batch process cancelled by user');
      addProgressLog(`\n⚠️ Cancelled! Processed ${processed} of ${total}`, 'bad');
      document.getElementById('progress-cancel-btn').style.display = 'none';
      document.getElementById('progress-close-btn').style.display = 'block';
      showToast(`Cancelled after ${processed} receipts`, '⚠️');
      return;
    }

    try {
      // Update progress
      processed++;
      const percent = Math.round((processed / total) * 100);
      updateProgress(processed, found, percent, total);

      debugLog(`[${processed}/${total}] Processing: ${row['Chase Description']?.substring(0, 40) || 'Unknown'}`);

      // Call AI match endpoint for this row
      const res = await fetch('/ai_match', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({_index: row._index})
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const data = await res.json();

      if (data.ok && data.result.receipt_file) {
        found++;
        // Update the row in our data
        Object.assign(row, data.result);

        // Mark as newly matched for visual highlighting
        row._newlyMatched = true;

        // Log the match
        const merchant = row['Chase Description'] || 'Unknown';
        const confidence = data.result.ai_confidence || 0;
        debugLog(`  ✓ Found receipt: ${confidence}% confidence`);
        addProgressLog(`✓ ${merchant.substring(0, 30)} → ${confidence}% match`, 'ok');
      } else {
        debugLog(`  ⊘ No match found`);
        addProgressLog(`⊘ ${(row['Chase Description'] || 'Unknown').substring(0, 30)} → No match`, 'muted');
      }

      // Update progress counters
      document.getElementById('progress-found').textContent = found;

    } catch (e) {
      console.error(`  ✗ Error processing receipt:`, e);
      addProgressLog(`✗ Error: ${e.message}`, 'bad');
    }
  }

  // Calculate time
  const elapsed = Math.round((Date.now() - startTime) / 1000);
  debugLog(`✅ Batch complete in ${elapsed}s: Found ${found} of ${total} receipts`);

  // Complete - hide cancel, show close button
  document.getElementById('progress-cancel-btn').style.display = 'none';
  document.getElementById('progress-close-btn').style.display = 'block';
  addProgressLog(`\n🎉 Complete! Found ${found} of ${total} receipts (${elapsed}s)`, 'ok');

  // Reload CSV to get all updates
  await loadCSV();
  showToast(`Batch complete! Found ${found} of ${total} receipts`, '✓');

  // Auto-remove highlighting after 30 seconds
  setTimeout(() => {
    csvData.forEach(row => {
      if (row._newlyMatched) {
        row._newlyMatched = false;
      }
    });
    renderTable();
    debugLog('🎨 Removed newly-matched highlighting');
  }, 30000);
}

function cancelBatchProcess() {
  if (confirm('Cancel batch processing?')) {
    batchProcessCancelled = true;
    debugLog('🛑 Cancelling batch process...');
  }
}

function updateProgress(processed, found, percent, total) {
  document.getElementById('progress-bar').style.width = `${percent}%`;
  document.getElementById('progress-text').textContent = `${percent}%`;
  document.getElementById('progress-processed').textContent = `${processed} / ${total}`;
  document.getElementById('progress-found').textContent = found;
}

function addProgressLog(message, type = 'muted') {
  const log = document.getElementById('progress-log');
  const colors = {
    ok: 'var(--ok)',
    bad: 'var(--bad)',
    muted: 'var(--muted)'
  };

  const entry = document.createElement('div');
  entry.style.color = colors[type] || colors.muted;
  entry.textContent = message;

  // Keep only last 20 entries
  if (log.children.length > 20) {
    log.removeChild(log.firstChild);
  }

  log.appendChild(entry);
  log.scrollTop = log.scrollHeight; // Auto-scroll to bottom
}

function closeProgressModal() {
  document.getElementById('progress-modal').classList.remove('active');
  renderTable();
}

async function detachReceipt() {
  if (!selectedRow) return;

  try {
    const response = await fetch('/detach_receipt', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({_index: selectedRow._index})
    });

    if (!response.ok) {
      throw new Error('Server error');
    }

    // Clear all receipt-related fields in local data
    selectedRow['Receipt File'] = '';
    selectedRow.receipt_file = '';
    selectedRow.r2_url = '';
    selectedRow['Review Status'] = '';  // This moves it to "Missing Receipt"
    selectedRow['AI Confidence'] = '';
    selectedRow.ai_receipt_merchant = '';
    selectedRow.ai_receipt_total = '';
    selectedRow.ai_receipt_date = '';

    // Re-apply filters - this will move the row to Missing Receipts if that filter exists
    applyFilters();
    loadReceipt();  // Show empty receipt panel
    showToast('Receipt detached - moved to Missing Receipts', '✓');
  } catch (e) {
    showToast('Failed to detach: ' + e.message, '❌');
  }
}

async function updateField(field, value) {
  if (!selectedRow) return;

  // Save scroll position BEFORE update
  const scrollContainer = document.querySelector('.table-wrap');
  const scrollPos = scrollContainer ? scrollContainer.scrollTop : 0;

  selectedRow[field] = value;
  try {
    await fetch('/update_row', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        _index: selectedRow._index,
        patch: {[field]: value}  // FIXED: was 'updates', should be 'patch'
      })
    });

    // ✅ FIX: Re-apply filters to rebuild filteredData with updated values
    // applyFilters() calls renderTable() + updateDashboard() - handles everything
    applyFilters();

    // Restore scroll position
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollPos;
    }
  } catch (e) {
    showToast('Update failed: ' + e.message, '❌');
  }
}

// NEW: Update a single row in-place without rebuilding table
function updateRowInPlace(row) {
  const tbody = document.getElementById('tbody');
  const tr = Array.from(tbody.children).find(
    tr => tr.dataset.index == row._index
  );

  if (!tr) {
    // Row doesn't exist in current filter - it may have been filtered out
    applyFilters();  // Re-filter to remove it
    return;
  }

  // Update cells in-place
  const cells = tr.cells;
  if (!cells || cells.length < 7) return;

  // Cell 0: Date - handles both YYYY-MM-DD and MySQL date formats
  const dateStr = row['Chase Date'] || '';
  if (dateStr) {
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    let year, month, day;
    const parts = dateStr.split('-');
    if (parts.length === 3 && parts[0].length === 4) {
      year = parts[0];
      month = months[parseInt(parts[1]) - 1] || parts[1];
      day = parseInt(parts[2]);
    } else {
      try {
        const d = new Date(dateStr);
        if (!isNaN(d.getTime())) {
          year = d.getFullYear();
          month = months[d.getMonth()];
          day = d.getDate();
        }
      } catch (e) {}
    }
    if (year && month && day) {
      cells[0].innerHTML = `<div class="date-cell"><span class="date-month-day">${month} ${day}</span><span class="date-year">${year}</span></div>`;
    }
  }

  // Cell 1: Description
  cells[1].textContent = row['Chase Description'] || '';

  // Cell 2: Amount
  const amt = parseFloat(row['Chase Amount'] || 0);
  const amtClass = amt > 0 ? 'neg' : 'pos';
  const amtSign = amt > 0 ? '-' : '+';
  cells[2].innerHTML = `<span class="amount ${amtClass}">${amtSign}$${Math.abs(amt).toFixed(2)}</span>`;

  // Cell 3: Business Type
  cells[3].textContent = row['Business Type'] || '';

  // Cell 4: Review Status
  cells[4].innerHTML = getStatusBadge(row['Review Status']);

  // Cell 5: AI Confidence
  cells[5].innerHTML = getConfidenceIndicator(row);

  // Cell 6: Notes
  const notes = row['Notes'] || '';
  const notesHtml = notes
    ? `<div class="notes-cell" onclick="editNotes(event, ${row._index})" title="${notes}">${notes}</div>`
    : `<div class="notes-cell empty" onclick="editNotes(event, ${row._index})">Click to add note</div>`;
  cells[6].innerHTML = notesHtml;
}

// Connect Gmail account via OAuth popup
function connectGmail(email) {
  showToast(`Opening Google authorization...`, '🔗');

  // Open OAuth in a popup window
  const width = 600;
  const height = 700;
  const left = (window.innerWidth - width) / 2 + window.screenX;
  const top = (window.innerHeight - height) / 2 + window.screenY;

  const popup = window.open(
    `/api/gmail/authorize/${encodeURIComponent(email)}`,
    'gmail_oauth',
    `width=${width},height=${height},left=${left},top=${top},menubar=no,toolbar=no,location=no,status=no`
  );

  // Poll for popup closure and refresh status
  const pollTimer = setInterval(() => {
    if (popup.closed) {
      clearInterval(pollTimer);
      showToast('Checking Gmail status...', '🔄');
      setTimeout(() => checkGmailStatus(), 500);
    }
  }, 500);
}

// Disconnect Gmail account
async function disconnectGmail(email) {
  if (!confirm(`Disconnect ${email}? You'll need to re-authorize to use Gmail features.`)) {
    return;
  }

  try {
    const res = await fetch(`/api/gmail/disconnect/${encodeURIComponent(email)}`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.ok) {
      showToast(`Disconnected ${email}`, '✓');
      await checkGmailStatus();
    } else {
      showToast(data.error || 'Failed to disconnect', '❌');
    }
  } catch (e) {
    showToast(`Error: ${e.message}`, '❌');
  }
}

// Check Gmail account status from backend
async function checkGmailStatus() {
  const emailToId = {
    'kaplan.brian@gmail.com': { status: 'gmail-status-personal', btn: 'gmail-btn-personal' },
    'brian@secondary.com': { status: 'gmail-status-sec', btn: 'gmail-btn-sec' },
    'brian@business.com': { status: 'gmail-status-business', btn: 'gmail-btn-business' }
  };

  try {
    const res = await fetch('/settings/gmail/status');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.ok && data.accounts) {
      data.accounts.forEach(account => {
        const ids = emailToId[account.email];
        if (!ids) return;

        const statusEl = document.getElementById(ids.status);
        const btnEl = document.getElementById(ids.btn);

        if (!statusEl) return;

        // If we have a refresh_token, we're connected (access token auto-refreshes when used)
        const isConnected = account.exists && account.has_refresh_token;

        if (!account.exists) {
          statusEl.className = 'badge badge-neutral';
          statusEl.textContent = 'Not connected';
          if (btnEl) {
            btnEl.textContent = '🔗 Connect';
            btnEl.onclick = () => connectGmail(account.email);
          }
        } else if (account.has_refresh_token) {
          // Connected - has refresh token so can auto-refresh when needed
          statusEl.className = 'badge badge-good';
          statusEl.textContent = account.expired ? 'Connected (will refresh)' : 'Connected';
          if (btnEl) {
            btnEl.textContent = '🔌 Disconnect';
            btnEl.onclick = () => disconnectGmail(account.email);
          }
        } else if (account.expired) {
          // No refresh token AND expired - need to reconnect
          statusEl.className = 'badge badge-bad';
          statusEl.textContent = 'Expired';
          if (btnEl) {
            btnEl.textContent = '🔄 Reconnect';
            btnEl.onclick = () => connectGmail(account.email);
          }
        } else {
          statusEl.className = 'badge badge-neutral';
          statusEl.textContent = 'Needs auth';
          if (btnEl) {
            btnEl.textContent = '🔗 Connect';
            btnEl.onclick = () => connectGmail(account.email);
          }
        }
      });
    }
  } catch (e) {
    console.error('Error checking Gmail status:', e);
  }
}

// Rendering
// Cached month names for performance
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// Virtual scrolling configuration
const VIRTUAL_SCROLL_CONFIG = {
  rowHeight: 48,        // Approximate row height in pixels
  bufferSize: 20,       // Extra rows to render above/below viewport
  enabled: true,        // Enable/disable virtual scrolling
  threshold: 50         // Only enable for datasets > this size
};
let virtualScrollState = { startIndex: 0, endIndex: 0 };

function renderTable() {
  const tbody = document.getElementById('tbody');
  const tableWrap = document.querySelector('.table-wrap');

  // Use virtual scrolling for large datasets
  const useVirtual = VIRTUAL_SCROLL_CONFIG.enabled && filteredData.length > VIRTUAL_SCROLL_CONFIG.threshold;

  if (useVirtual && tableWrap) {
    renderVirtualTable(tbody, tableWrap);
    return;
  }

  // Use DocumentFragment for batch DOM operations (significant performance improvement)
  const fragment = document.createDocumentFragment();

  // Pre-calculate selected index for faster comparison
  const selectedIndex = selectedRow ? selectedRow._index : null;

  filteredData.forEach(row => {
    const tr = document.createElement('tr');
    const rowIndex = row._index;

    if (selectedIndex !== null && rowIndex === selectedIndex) {
      tr.classList.add('selected');
    }

    // Highlight newly matched receipts
    if (row._newlyMatched) {
      tr.classList.add('newly-matched');
    }

    // Check if this is a refund (cache amount)
    const amt = parseFloat(row['Chase Amount'] || row['Amount'] || 0);
    const isRefund = amt < 0 || row['Review Status'] === 'refund';
    if (isRefund) {
      tr.classList.add('refund-row');
    }

    // Format date - optimized parsing
    const dateStr = row['Chase Date'] || '';
    let dateHtml = '';
    if (dateStr) {
      let year, month, day;
      const parts = dateStr.split('-');
      if (parts.length === 3 && parts[0].length === 4) {
        year = parts[0];
        month = MONTHS[parseInt(parts[1]) - 1] || parts[1];
        day = parseInt(parts[2]);
      } else {
        try {
          const d = new Date(dateStr);
          if (!isNaN(d.getTime())) {
            year = d.getFullYear();
            month = MONTHS[d.getMonth()];
            day = d.getDate();
          }
        } catch (e) {}
      }

      dateHtml = (year && month && day)
        ? `<div class="date-cell"><span class="date-month-day">${month} ${day}</span><span class="date-year">${year}</span></div>`
        : dateStr;
    }

    // Format amount with +/- sign
    const amtClass = amt > 0 ? 'neg' : 'pos';
    const amtSign = amt > 0 ? '-' : '+';
    const amtHtml = `<span class="amount ${amtClass}">${amtSign}$${Math.abs(amt).toFixed(2)}</span>`;

    // MI Enhanced fields
    const miMerchant = row['MI Merchant'] || row['Chase Description'] || '';
    const miCategory = row['MI Category'] || row['Chase Category'] || '';
    const miDescription = row['MI Description'] || row['Notes'] || '';
    const isSubscription = row['MI Is Subscription'] === 1;

    // Merchant cell with subscription badge (XSS-safe)
    const merchantHtml = isSubscription
      ? `<div class="merchant-cell" title="${escapeHtml(row['Chase Description'] || '')}">${escapeHtml(miMerchant)} <span class="sub-badge">SUB</span></div>`
      : `<div class="merchant-cell" title="${escapeHtml(row['Chase Description'] || '')}">${escapeHtml(miMerchant)}</div>`;

    // Category cell
    const categoryHtml = `<span class="category-badge">${miCategory}</span>`;

    // Description cell with inline editing (XSS-safe)
    const descHtml = miDescription
      ? `<div class="notes-cell" onclick="editNotes(event, ${rowIndex})" title="${escapeHtml(miDescription)}">${escapeHtml(miDescription)}</div>`
      : `<div class="notes-cell empty" onclick="editNotes(event, ${rowIndex})">Click to add note</div>`;

    // Receipt indicator - check both local file and R2 URL + validation status
    const receiptFile = row['Receipt File'] || '';
    const r2Url = row['r2_url'] || row['R2 URL'] || row['receipt_url'] || '';
    const hasReceipt = receiptFile || r2Url;
    const validationStatus = row['receipt_validation_status'] || '';
    const validationNote = row['receipt_validation_note'] || '';
    let receiptHtml;
    if (hasReceipt) {
      if (validationStatus === 'verified') {
        receiptHtml = `<span class="receipt-indicator verified" title="Verified: ${escapeHtml(validationNote)}">✓✓</span>`;
      } else if (validationStatus === 'mismatch') {
        receiptHtml = `<span class="receipt-indicator mismatch" title="MISMATCH: ${escapeHtml(validationNote)}">✗</span>`;
      } else if (validationStatus === 'needs_review') {
        receiptHtml = `<span class="receipt-indicator needs-review" title="Needs Review: ${escapeHtml(validationNote)}">?</span>`;
      } else {
        receiptHtml = `<span class="receipt-indicator has-receipt" title="${escapeHtml(receiptFile || r2Url)}">✓</span>`;
      }
    } else {
      receiptHtml = `<span class="receipt-indicator no-receipt">–</span>`;
    }

    tr.innerHTML = `
      <td>${dateHtml}</td>
      <td>${merchantHtml}</td>
      <td>${amtHtml}</td>
      <td>${escapeHtml(miCategory)}</td>
      <td>${escapeHtml(row['Business Type'] || '')}</td>
      <td>${getStatusBadge(row['Review Status'], isRefund)}</td>
      <td>${receiptHtml}</td>
      <td>${descHtml}</td>
    `;

    tr.dataset.index = rowIndex;
    tr.onclick = (e) => {
      // Don't select row if clicking on notes cell
      if (!e.target.classList.contains('notes-cell') && !e.target.classList.contains('notes-input')) {
        // On mobile/tablet, open the mobile receipt viewer
        if (window.innerWidth <= 1024) {
          showMobileReceiptViewer(rowIndex);
        } else {
          selectRow(row);
        }
      }
    };
    fragment.appendChild(tr);
  });

  // Single DOM update - much faster than individual appendChild calls
  tbody.innerHTML = '';
  tbody.appendChild(fragment);

  // Also render mobile cards
  renderMobileCards();
}

// Virtual scrolling for large datasets
function renderVirtualTable(tbody, tableWrap) {
  const { rowHeight, bufferSize } = VIRTUAL_SCROLL_CONFIG;
  const totalRows = filteredData.length;
  const totalHeight = totalRows * rowHeight;

  // Calculate visible range based on scroll position
  const scrollTop = tableWrap.scrollTop || 0;
  const viewportHeight = tableWrap.clientHeight || 500;

  let startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - bufferSize);
  let endIndex = Math.min(totalRows, Math.ceil((scrollTop + viewportHeight) / rowHeight) + bufferSize);

  // Save state for scroll handler
  virtualScrollState = { startIndex, endIndex };

  const fragment = document.createDocumentFragment();
  const selectedIndex = selectedRow ? selectedRow._index : null;

  // Create top spacer for scroll position
  if (startIndex > 0) {
    const topSpacer = document.createElement('tr');
    topSpacer.innerHTML = `<td colspan="8" style="height: ${startIndex * rowHeight}px; padding: 0; border: none;"></td>`;
    topSpacer.classList.add('virtual-spacer');
    fragment.appendChild(topSpacer);
  }

  // Render visible rows
  for (let i = startIndex; i < endIndex; i++) {
    const row = filteredData[i];
    if (!row) continue;

    const tr = createTableRow(row, selectedIndex);
    fragment.appendChild(tr);
  }

  // Create bottom spacer
  const bottomSpacerHeight = (totalRows - endIndex) * rowHeight;
  if (bottomSpacerHeight > 0) {
    const bottomSpacer = document.createElement('tr');
    bottomSpacer.innerHTML = `<td colspan="8" style="height: ${bottomSpacerHeight}px; padding: 0; border: none;"></td>`;
    bottomSpacer.classList.add('virtual-spacer');
    fragment.appendChild(bottomSpacer);
  }

  tbody.innerHTML = '';
  tbody.appendChild(fragment);

  // Setup scroll listener (debounced)
  if (!tableWrap._virtualScrollHandler) {
    let scrollTimeout;
    tableWrap._virtualScrollHandler = () => {
      clearTimeout(scrollTimeout);
      scrollTimeout = setTimeout(() => {
        const newScrollTop = tableWrap.scrollTop;
        const newStartIndex = Math.max(0, Math.floor(newScrollTop / rowHeight) - bufferSize);
        const newEndIndex = Math.min(totalRows, Math.ceil((newScrollTop + viewportHeight) / rowHeight) + bufferSize);

        // Only re-render if visible range changed significantly
        if (Math.abs(newStartIndex - virtualScrollState.startIndex) > bufferSize / 2 ||
            Math.abs(newEndIndex - virtualScrollState.endIndex) > bufferSize / 2) {
          renderVirtualTable(tbody, tableWrap);
        }
      }, 16); // ~60fps
    };
    tableWrap.addEventListener('scroll', tableWrap._virtualScrollHandler, { passive: true });
  }

  // Also render mobile cards
  renderMobileCards();
}

// Helper function to create a single table row
function createTableRow(row, selectedIndex) {
  const tr = document.createElement('tr');
  const rowIndex = row._index;

  if (selectedIndex !== null && rowIndex === selectedIndex) {
    tr.classList.add('selected');
  }
  if (row._newlyMatched) {
    tr.classList.add('newly-matched');
  }

  const amt = parseFloat(row['Chase Amount'] || row['Amount'] || 0);
  const isRefund = amt < 0 || row['Review Status'] === 'refund';
  if (isRefund) {
    tr.classList.add('refund-row');
  }

  // Format date
  const dateStr = row['Chase Date'] || '';
  let dateHtml = '';
  if (dateStr) {
    const parts = dateStr.split('-');
    if (parts.length === 3 && parts[0].length === 4) {
      const year = parts[0];
      const month = MONTHS[parseInt(parts[1]) - 1] || parts[1];
      const day = parseInt(parts[2]);
      dateHtml = `<div class="date-cell"><span class="date-month-day">${month} ${day}</span><span class="date-year">${year}</span></div>`;
    } else {
      dateHtml = dateStr;
    }
  }

  const amtClass = amt > 0 ? 'neg' : 'pos';
  const amtSign = amt > 0 ? '-' : '+';
  const amtHtml = `<span class="amount ${amtClass}">${amtSign}$${Math.abs(amt).toFixed(2)}</span>`;

  const miMerchant = row['MI Merchant'] || row['Chase Description'] || '';
  const miCategory = row['MI Category'] || row['Chase Category'] || '';
  const miDescription = row['MI Description'] || row['Notes'] || '';
  const isSubscription = row['MI Is Subscription'] === 1;

  const merchantHtml = isSubscription
    ? `<div class="merchant-cell" title="${escapeHtml(row['Chase Description'] || '')}">${escapeHtml(miMerchant)} <span class="sub-badge">SUB</span></div>`
    : `<div class="merchant-cell" title="${escapeHtml(row['Chase Description'] || '')}">${escapeHtml(miMerchant)}</div>`;

  const descHtml = miDescription
    ? `<div class="notes-cell" onclick="editNotes(event, ${rowIndex})" title="${escapeHtml(miDescription)}">${escapeHtml(miDescription)}</div>`
    : `<div class="notes-cell empty" onclick="editNotes(event, ${rowIndex})">Click to add note</div>`;

  const receiptFile = row['Receipt File'] || '';
  const r2Url = row['r2_url'] || row['R2 URL'] || row['receipt_url'] || '';
  const hasReceipt = receiptFile || r2Url;
  const validationStatus = row['receipt_validation_status'] || '';
  const validationNote = row['receipt_validation_note'] || '';
  let receiptHtml;
  if (hasReceipt) {
    if (validationStatus === 'verified') {
      receiptHtml = `<span class="receipt-indicator verified" title="Verified: ${escapeHtml(validationNote)}">✓✓</span>`;
    } else if (validationStatus === 'mismatch') {
      receiptHtml = `<span class="receipt-indicator mismatch" title="MISMATCH: ${escapeHtml(validationNote)}">✗</span>`;
    } else if (validationStatus === 'needs_review') {
      receiptHtml = `<span class="receipt-indicator needs-review" title="Needs Review: ${escapeHtml(validationNote)}">?</span>`;
    } else {
      receiptHtml = `<span class="receipt-indicator has-receipt" title="${escapeHtml(receiptFile || r2Url)}">✓</span>`;
    }
  } else {
    receiptHtml = `<span class="receipt-indicator no-receipt">–</span>`;
  }

  tr.innerHTML = `
    <td>${dateHtml}</td>
    <td>${merchantHtml}</td>
    <td>${amtHtml}</td>
    <td>${escapeHtml(miCategory)}</td>
    <td>${escapeHtml(row['Business Type'] || '')}</td>
    <td>${getStatusBadge(row['Review Status'], isRefund)}</td>
    <td>${receiptHtml}</td>
    <td>${descHtml}</td>
  `;

  tr.dataset.index = rowIndex;
  tr.onclick = (e) => {
    if (!e.target.classList.contains('notes-cell') && !e.target.classList.contains('notes-input')) {
      if (window.innerWidth <= 1024) {
        showMobileReceiptViewer(rowIndex);
      } else {
        selectRow(row);
      }
    }
  };

  return tr;
}

// Render mobile card view
function renderMobileCards() {
  const mobileCards = document.getElementById('mobile-cards');
  if (!mobileCards) return;

  if (filteredData.length === 0) {
    mobileCards.innerHTML = `
      <div class="mobile-cards-empty">
        <div class="mobile-cards-empty-icon">📭</div>
        <div class="mobile-cards-empty-text">No transactions match your filters</div>
      </div>`;
    return;
  }

  const selectedIndex = selectedRow ? selectedRow._index : null;
  let html = '';

  filteredData.forEach(row => {
    const rowIndex = row._index;
    const isSelected = selectedIndex !== null && rowIndex === selectedIndex;

    // Amount
    const amt = parseFloat(row['Chase Amount'] || row['Amount'] || 0);
    const isRefund = amt < 0 || row['Review Status'] === 'refund';
    const amtClass = isRefund ? 'refund' : (amt > 0 ? 'negative' : 'positive');
    const amtSign = amt > 0 ? '-' : '+';
    const amtDisplay = `${amtSign}$${Math.abs(amt).toFixed(2)}`;

    // Date
    const dateStr = row['Chase Date'] || '';
    let dateDisplay = dateStr;
    if (dateStr) {
      const parts = dateStr.split('-');
      if (parts.length === 3 && parts[0].length === 4) {
        const month = MONTHS[parseInt(parts[1]) - 1] || parts[1];
        const day = parseInt(parts[2]);
        dateDisplay = `${month} ${day}, ${parts[0]}`;
      }
    }

    // Fields
    const merchant = row['MI Merchant'] || row['Chase Description'] || 'Unknown';
    const category = row['MI Category'] || row['Chase Category'] || '';
    const business = row['Business Type'] || '';
    const status = row['Review Status'] || 'pending';

    // Receipt check + validation status
    const receiptFile = row['Receipt File'] || '';
    const r2Url = row['r2_url'] || row['R2 URL'] || row['receipt_url'] || '';
    const hasReceipt = receiptFile || r2Url;
    const validationStatus = row['receipt_validation_status'] || '';
    let receiptClass = hasReceipt ? 'has-receipt' : 'no-receipt';
    let receiptIcon = hasReceipt ? '✓' : '!';
    let receiptIconClass = hasReceipt ? 'has' : 'missing';
    if (hasReceipt && validationStatus === 'verified') {
      receiptClass = 'verified';
      receiptIcon = '✓✓';
      receiptIconClass = 'verified';
    } else if (hasReceipt && validationStatus === 'mismatch') {
      receiptClass = 'mismatch';
      receiptIcon = '✗';
      receiptIconClass = 'mismatch';
    } else if (hasReceipt && validationStatus === 'needs_review') {
      receiptClass = 'needs-review';
      receiptIcon = '?';
      receiptIconClass = 'needs-review';
    }

    // Status badge
    let statusHtml = '';
    if (isRefund) {
      statusHtml = '<span class="badge badge-refund" style="font-size:10px;padding:3px 8px">Refund</span>';
    } else if (status === 'good') {
      statusHtml = '<span class="badge badge-good" style="font-size:10px;padding:3px 8px">Good</span>';
    } else if (status === 'bad') {
      statusHtml = '<span class="badge badge-bad" style="font-size:10px;padding:3px 8px">Bad</span>';
    }

    html += `
      <div class="tx-card ${receiptClass}${isSelected ? ' selected' : ''}"
           data-index="${rowIndex}"
           onclick="openMobileDrawer(${rowIndex})">
        <div class="tx-card-header">
          <div class="tx-card-merchant">${escapeHtml(merchant)}</div>
          <div class="tx-card-amount ${amtClass}">${amtDisplay}</div>
        </div>
        <div class="tx-card-body">
          <div class="tx-card-date">${escapeHtml(dateDisplay)}</div>
          ${category ? `<div class="tx-card-category">${escapeHtml(category)}</div>` : ''}
          ${business ? `<div class="tx-card-business">${escapeHtml(business)}</div>` : ''}
        </div>
        <div class="tx-card-footer">
          <div class="tx-card-status">
            <div class="tx-card-receipt-icon ${receiptIconClass}">${receiptIcon}</div>
            ${statusHtml}
          </div>
          <div class="tx-card-arrow">›</div>
        </div>
      </div>`;
  });

  mobileCards.innerHTML = html;
}

// Mobile drawer functions
let currentDrawerRow = null;

function openMobileDrawer(rowIndex) {
  const row = csvData.find(r => r._index === rowIndex);
  if (!row) return;

  currentDrawerRow = row;
  selectedRow = row;

  // Create drawer if not exists
  let drawer = document.getElementById('tx-drawer');
  let backdrop = document.getElementById('tx-drawer-backdrop');

  if (!drawer) {
    backdrop = document.createElement('div');
    backdrop.id = 'tx-drawer-backdrop';
    backdrop.className = 'tx-drawer-backdrop';
    backdrop.onclick = closeMobileDrawer;
    document.body.appendChild(backdrop);

    drawer = document.createElement('div');
    drawer.id = 'tx-drawer';
    drawer.className = 'tx-drawer';
    document.body.appendChild(drawer);
  }

  // Get data
  const amt = parseFloat(row['Chase Amount'] || row['Amount'] || 0);
  const isRefund = amt < 0 || row['Review Status'] === 'refund';
  const amtSign = amt > 0 ? '-' : '+';
  const amtDisplay = `${amtSign}$${Math.abs(amt).toFixed(2)}`;
  const amtClass = isRefund ? 'color:var(--pos)' : (amt > 0 ? '' : 'color:var(--pos)');

  const dateStr = row['Chase Date'] || '';
  let dateDisplay = dateStr;
  if (dateStr) {
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const month = MONTHS[parseInt(parts[1]) - 1] || parts[1];
      dateDisplay = `${month} ${parseInt(parts[2])}, ${parts[0]}`;
    }
  }

  const merchant = row['MI Merchant'] || row['Chase Description'] || 'Unknown';
  const category = row['MI Category'] || row['Chase Category'] || 'Uncategorized';
  const business = row['Business Type'] || 'Unassigned';
  const status = row['Review Status'] || 'pending';
  const description = row['Chase Description'] || '';
  const notes = row['MI Description'] || row['Notes'] || '';

  // Receipt
  const receiptFile = row['Receipt File'] || '';
  const r2Url = row['r2_url'] || row['R2 URL'] || row['receipt_url'] || '';
  const hasReceipt = receiptFile || r2Url;

  let receiptHtml = '';
  if (hasReceipt) {
    const imgUrl = r2Url || `/receipts/${encodeURIComponent(receiptFile)}`;
    receiptHtml = `<img src="${imgUrl}" alt="Receipt" onerror="this.parentElement.innerHTML='<div class=tx-drawer-receipt-placeholder><div class=tx-drawer-receipt-placeholder-icon>⚠️</div><div>Failed to load receipt</div></div>'">`;
  } else {
    receiptHtml = `
      <div class="tx-drawer-receipt-placeholder">
        <div class="tx-drawer-receipt-placeholder-icon">📄</div>
        <div>No receipt attached</div>
      </div>`;
  }

  drawer.innerHTML = `
    <div class="tx-drawer-handle"></div>
    <div class="tx-drawer-header">
      <div class="tx-drawer-title">${escapeHtml(merchant)}</div>
      <button class="tx-drawer-close" onclick="closeMobileDrawer()">×</button>
    </div>
    <div class="tx-drawer-body">
      <div class="tx-drawer-receipt">${receiptHtml}</div>
      <div class="tx-drawer-details">
        <div class="tx-drawer-row">
          <div class="tx-drawer-label">Amount</div>
          <div class="tx-drawer-value amount" style="${amtClass}">${amtDisplay}</div>
        </div>
        <div class="tx-drawer-row">
          <div class="tx-drawer-label">Date</div>
          <div class="tx-drawer-value">${escapeHtml(dateDisplay)}</div>
        </div>
        <div class="tx-drawer-row">
          <div class="tx-drawer-label">Category</div>
          <div class="tx-drawer-value">${escapeHtml(category)}</div>
        </div>
        <div class="tx-drawer-row">
          <div class="tx-drawer-label">Business</div>
          <div class="tx-drawer-value">${escapeHtml(business)}</div>
        </div>
        <div class="tx-drawer-row">
          <div class="tx-drawer-label">Status</div>
          <div class="tx-drawer-value">${escapeHtml(status.charAt(0).toUpperCase() + status.slice(1))}</div>
        </div>
        ${description ? `<div class="tx-drawer-row"><div class="tx-drawer-label">Description</div><div class="tx-drawer-value" style="font-size:13px">${escapeHtml(description)}</div></div>` : ''}
        ${notes ? `<div class="tx-drawer-row"><div class="tx-drawer-label">Notes</div><div class="tx-drawer-value" style="font-size:13px">${escapeHtml(notes)}</div></div>` : ''}
      </div>
    </div>
    <div class="tx-drawer-actions">
      <button class="tx-drawer-btn secondary" onclick="markMobileStatus('good')">✓ Good</button>
      <button class="tx-drawer-btn secondary" onclick="markMobileStatus('bad')">✗ Bad</button>
      ${!hasReceipt ? `<button class="tx-drawer-btn primary" onclick="closeMobileDrawer();window.location.href='/scanner'" style="grid-column:span 2">📷 Add Receipt</button>` : ''}
    </div>`;

  // Show drawer
  setTimeout(() => {
    backdrop.classList.add('active');
    drawer.classList.add('active');
  }, 10);

  // Update card selection
  renderMobileCards();
}

function closeMobileDrawer() {
  const drawer = document.getElementById('tx-drawer');
  const backdrop = document.getElementById('tx-drawer-backdrop');
  if (drawer) drawer.classList.remove('active');
  if (backdrop) backdrop.classList.remove('active');
  currentDrawerRow = null;
}

async function markMobileStatus(status) {
  if (!currentDrawerRow) return;

  try {
    await fetch('/update_row', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        _index: currentDrawerRow._index,
        patch: {'Review Status': status}
      })
    });

    currentDrawerRow['Review Status'] = status;
    showToast(`Marked as ${status}`, '✓');
    closeMobileDrawer();
    renderTable();
  } catch (e) {
    showToast('Failed to update: ' + e.message, '❌');
  }
}

function getStatusBadge(status, isRefund) {
  if (isRefund || status === 'refund') return '<span class="badge badge-refund">Refund</span>';
  if (!status) return '<span class="badge badge-pending">Pending</span>';
  if (status === 'good') return '<span class="badge badge-good">Good</span>';
  if (status === 'bad') return '<span class="badge badge-bad">Bad</span>';
  return `<span class="badge badge-pending">${status}</span>`;
}

function getConfidenceIndicator(row) {
  // Check if receipt exists (any source)
  const receiptFile = (row['Receipt File'] || '').trim();
  const receiptUrl = (row.receipt_url || '').trim();
  const r2Url = (row.r2_url || row['R2 URL'] || '').trim();
  if (!receiptFile && !receiptUrl && !r2Url) {
    return '—';
  }

  // Get confidence score
  const confidence = parseFloat(row['AI Confidence']) || 0;

  // Determine confidence level and color
  let level, className, label;
  if (confidence >= 90) {
    level = 'excellent';
    className = 'conf-excellent';
    label = `${confidence.toFixed(0)}%`;
  } else if (confidence >= 80) {
    level = 'very-good';
    className = 'conf-very-good';
    label = `${confidence.toFixed(0)}%`;
  } else if (confidence >= 70) {
    level = 'good';
    className = 'conf-good';
    label = `${confidence.toFixed(0)}%`;
  } else if (confidence >= 60) {
    level = 'fair';
    className = 'conf-fair';
    label = `${confidence.toFixed(0)}%`;
  } else if (confidence > 0) {
    level = 'low';
    className = 'conf-low';
    label = `${confidence.toFixed(0)}%`;
  } else {
    // Receipt exists but no confidence score
    level = 'none';
    className = 'conf-none';
    label = '—';
  }

  return `<span class="confidence-indicator ${className}" title="Match Confidence: ${label}">
    <span class="confidence-dot ${className}"></span>
    ${label}
  </span>`;
}

function selectRow(row) {
  selectedRow = row;
  renderTable();
  loadReceipt();
}

// Notes inline editing
function editNotes(event, rowIndex) {
  event.stopPropagation();

  const row = csvData.find(r => r._index === rowIndex);
  if (!row) return;

  const cell = event.target;
  const currentNotes = row['Notes'] || '';

  // Create input field
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'notes-input';
  input.value = currentNotes;
  input.placeholder = 'Add note...';

  // Replace cell content
  cell.innerHTML = '';
  cell.appendChild(input);
  input.focus();
  input.select();

  // Save on blur or Enter
  const saveNotes = async () => {
    const newNotes = input.value.trim();
    row['Notes'] = newNotes;

    // Update on server
    try {
      await fetch('/update_row', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          _index: rowIndex,
          patch: {Notes: newNotes}
        })
      });
      renderTable();
      showToast('Note saved', '✓');
    } catch (e) {
      showToast('Failed to save note: ' + e.message, '❌');
      renderTable();
    }
  };

  input.addEventListener('blur', saveNotes);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      saveNotes();
    } else if (e.key === 'Escape') {
      renderTable();
    }
  });
}

function loadReceipt() {
  const wrap = document.getElementById('panzoom-wrap');
  const title = document.getElementById('viewer-title');

  // Check for R2 URL first (cloud storage), then local Receipt File
  const r2Url = selectedRow ? (selectedRow['r2_url'] || selectedRow['R2 URL'] || selectedRow['receipt_url']) : null;
  const receiptFile = selectedRow ? selectedRow['Receipt File'] : null;
  const reviewStatus = selectedRow ? (selectedRow['Review Status'] || '').toLowerCase().trim() : '';

  // Check if marked as "not needed" first
  if (selectedRow && reviewStatus === 'not needed') {
    wrap.innerHTML = `
      <div class="no-receipt" style="background:linear-gradient(135deg, rgba(34,197,94,0.1), rgba(22,163,74,0.05))">
        <div class="no-receipt-icon" style="font-size:64px">✅</div>
        <div class="no-receipt-text" style="color:#22c55e;font-weight:600">No Receipt Needed</div>
        <div style="font-size:12px;color:var(--muted);margin-top:8px">This expense doesn't require a receipt</div>
      </div>`;
    title.textContent = 'Not Needed';
    return;
  }

  if (!selectedRow || (!receiptFile && !r2Url)) {
    wrap.innerHTML = `
      <div class="no-receipt">
        <div class="no-receipt-icon">📄</div>
        <div class="no-receipt-text">No receipt attached</div>
        <div style="font-size:12px;color:var(--muted);margin-top:8px">Drag & drop a receipt or use AI Match</div>
      </div>`;
    title.textContent = 'Receipt Viewer';
    return;
  }

  // Handle multiple receipt paths (comma-separated) - take first one
  let receiptPath = receiptFile ? receiptFile.split(',')[0].trim() : '';

  // Skip special values
  if (receiptPath === 'NO_RECEIPT_NEEDED' || receiptPath === 'NO_RECEIPT') {
    wrap.innerHTML = `
      <div class="no-receipt" style="background:linear-gradient(135deg, rgba(34,197,94,0.1), rgba(22,163,74,0.05))">
        <div class="no-receipt-icon" style="font-size:64px">✅</div>
        <div class="no-receipt-text" style="color:#22c55e;font-weight:600">No Receipt Needed</div>
        <div style="font-size:12px;color:var(--muted);margin-top:8px">This expense doesn't require a receipt</div>
      </div>`;
    title.textContent = 'Not Needed';
    return;
  }

  // Set title from receipt path or R2 URL
  if (receiptPath) {
    title.textContent = receiptPath.split('/').pop();
  } else if (r2Url) {
    title.textContent = r2Url.split('/').pop();
  }

  const img = document.createElement('img');

  // Use R2 URL if available (cloud storage), otherwise use local path
  if (r2Url && r2Url.startsWith('http')) {
    img.src = r2Url;
  } else if (receiptPath) {
    // Build proper local path - handle various path formats
    if (receiptPath.startsWith('receipts/')) {
      img.src = `/${receiptPath}`;
    } else if (receiptPath.startsWith('incoming/')) {
      img.src = `/${receiptPath}`;
    } else {
      img.src = `/receipts/${receiptPath}`;
    }
  } else {
    // Fallback - no valid path
    wrap.innerHTML = `
      <div class="no-receipt">
        <div class="no-receipt-icon">📄</div>
        <div class="no-receipt-text">Receipt path not found</div>
      </div>`;
    title.textContent = 'Receipt Viewer';
    return;
  }
  img.alt = 'Receipt';
  img.style.imageOrientation = 'from-image'; // Auto-handle EXIF orientation

  // Auto-rotation: detect if image needs rotation after load
  img.onload = function() {
    let rotation = currentRotation;

    // Auto-rotate landscape images (width > height * 1.3) to portrait
    if (currentRotation === 0 && img.naturalWidth > img.naturalHeight * 1.3) {
      rotation = 90;
      currentRotation = 90;
    }

    // Apply rotation
    img.style.transform = `rotate(${rotation}deg)`;

    // Re-initialize panzoom after image loads
    if (panzoomInstance) panzoomInstance.destroy();
    panzoomInstance = Panzoom(img, {
      maxScale: 5,
      minScale: 0.5,
      startScale: 1.2,
      contain: 'inside'
    });

    // Remove old wheel handler before adding new one to prevent memory leak
    if (wheelHandler) {
      wrap.removeEventListener('wheel', wheelHandler);
    }
    wheelHandler = (e) => {
      e.preventDefault();
      panzoomInstance.zoomWithWheel(e);
    };
    wrap.addEventListener('wheel', wheelHandler);
  };

  // Error handling - try fallback if R2 URL fails
  img.onerror = function() {
    if (r2Url && receiptPath && !img.dataset.retried) {
      console.warn('R2 URL failed, trying local path:', receiptPath);
      img.dataset.retried = 'true';
      img.src = `/receipts/${receiptPath}`;
    } else {
      wrap.innerHTML = `
        <div class="no-receipt">
          <div class="no-receipt-icon">⚠️</div>
          <div class="no-receipt-text">Failed to load receipt</div>
          <div style="font-size:11px;color:var(--muted);margin-top:4px">Image may have been moved or deleted</div>
        </div>`;
      title.textContent = 'Load Error';
    }
  };

  // Initial rotation transform
  img.style.transform = `rotate(${currentRotation}deg)`;

  wrap.innerHTML = '';
  wrap.appendChild(img);
}

function updateDashboard() {
  // ✅ FIX: Use csvData for header totals so they ALWAYS show ALL transactions
  // This ensures live stats update correctly when business type changes
  const dataToUse = csvData;

  // Calculate totals by Business Type
  // Expenses (positive) + Refunds (negative, excluding payments) = Net Total
  // ✅ FIX: Use both Title Case and snake_case field names for robust field access
  const getAmount = (r) => parseFloat(r['Chase Amount'] || r['chase_amount'] || 0);
  const getDesc = (r) => (r['Chase Description'] || r['chase_description'] || '').toLowerCase();
  const isPaymentTxn = (desc) => desc.includes('payment thank you') || desc.includes('payment - web');

  // Helper to get business type (checks both Title Case and snake_case)
  const getBizType = (r) => (r['Business Type'] || r['business_type'] || '').trim();

  const businessTotal = dataToUse
    .filter(r => getBizType(r) === 'Business' || getBizType(r) === 'Business')
    .reduce((sum, r) => {
      const amt = getAmount(r);
      const desc = getDesc(r);
      // Include positive (expenses) and negative (refunds, but not payments)
      if (isPaymentTxn(desc)) return sum;  // Skip payments
      return sum + amt;  // Add positive expenses, subtract refunds (negative amounts)
    }, 0);

  const secTotal = dataToUse
    .filter(r => getBizType(r) === 'Secondary' || getBizType(r) === 'Secondary' || getBizType(r) === 'MCR')
    .reduce((sum, r) => {
      const amt = getAmount(r);
      const desc = getDesc(r);
      if (isPaymentTxn(desc)) return sum;
      return sum + amt;
    }, 0);

  const personalTotal = dataToUse
    .filter(r => getBizType(r) === 'Personal')
    .reduce((sum, r) => {
      const amt = getAmount(r);
      const desc = getDesc(r);
      if (isPaymentTxn(desc)) return sum;
      return sum + amt;
    }, 0);

  // EM.co total
  const emcoTotal = dataToUse
    .filter(r => getBizType(r) === 'EM.co' || getBizType(r) === 'EM Co' || getBizType(r) === 'EM_co')
    .reduce((sum, r) => {
      const amt = getAmount(r);
      const desc = getDesc(r);
      if (isPaymentTxn(desc)) return sum;
      return sum + amt;
    }, 0);

  // Credit Card Payments - Description contains "PAYMENT THANK YOU" (negative amounts)
  const paymentsTotal = dataToUse
    .reduce((sum, r) => {
      const amt = getAmount(r);
      const desc = getDesc(r);
      return isPaymentTxn(desc) ? sum + Math.abs(amt) : sum;
    }, 0);

  document.getElementById('business-total').textContent = `$${businessTotal.toFixed(2)}`;
  document.getElementById('sec-total').textContent = `$${secTotal.toFixed(2)}`;
  document.getElementById('emco-total').textContent = `$${emcoTotal.toFixed(2)}`;
  document.getElementById('personal-total').textContent = `$${personalTotal.toFixed(2)}`;
  document.getElementById('payments-total').textContent = `+$${paymentsTotal.toFixed(2)}`;

  // Update collapsed dashboard summary
  const totalBusiness = businessTotal + secTotal + emcoTotal;
  const summaryEl = document.getElementById('dashboard-summary');
  if (summaryEl) {
    summaryEl.innerHTML = `
      <span class="dashboard-summary-item">Business: <span class="dashboard-summary-value">$${totalBusiness.toFixed(0)}</span></span>
      <span class="dashboard-summary-item">Personal: <span class="dashboard-summary-value">$${personalTotal.toFixed(0)}</span></span>
      <span class="dashboard-summary-item">Payments: <span class="dashboard-summary-value">+$${paymentsTotal.toFixed(0)}</span></span>
    `;
  }

  // Update ALL filter counts (from ALL data, not filtered)
  const counts = {
    all: csvData.length,
    // ✅ Needs review = has receipt AND (no status OR status not in good/bad/not needed)
    needsReview: csvData.filter(r => {
      const status = (r['Review Status'] || '').toLowerCase().trim();
      const receiptFile = (r['Receipt File'] || '').trim();
      const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
      const hasReceipt = receiptFile !== '' || r2Url !== '';
      return hasReceipt && (!status || (status !== 'good' && status !== 'bad' && status !== 'not needed'));
    }).length,
    // ✅ Good/Bad must have receipts
    good: csvData.filter(r => {
      const receiptFile = (r['Receipt File'] || '').trim();
      const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
      const hasReceipt = receiptFile !== '' || r2Url !== '';
      return hasReceipt && r['Review Status'] === 'good';
    }).length,
    bad: csvData.filter(r => {
      const receiptFile = (r['Receipt File'] || '').trim();
      const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
      const hasReceipt = receiptFile !== '' || r2Url !== '';
      return hasReceipt && r['Review Status'] === 'bad';
    }).length,
    missing: csvData.filter(r => {
      const receiptFile = (r['Receipt File'] || '').trim();
      const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
      const status = (r['Review Status'] || '').toLowerCase().trim();
      const hasReceipt = receiptFile !== '' || r2Url !== '';
      return !hasReceipt && status !== 'not needed';
    }).length,
    withReceipts: csvData.filter(r => {
      const receiptFile = (r['Receipt File'] || '').trim();
      const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
      return receiptFile !== '' || r2Url !== '';
    }).length,
    notNeeded: csvData.filter(r => r['Review Status'] === 'not needed' || r['Receipt File'] === 'NO_RECEIPT_NEEDED').length,
    // ✅ Refunds = negative amounts OR review_status = refund
    refunds: csvData.filter(r => {
      const amount = parseFloat(r['Chase Amount'] || r['Amount'] || 0);
      return amount < 0 || r['Review Status'] === 'refund';
    }).length,
    sec: csvData.filter(r => r['Business Type'] === 'Secondary').length,
    business: csvData.filter(r => r['Business Type'] === 'Business').length,
    personal: csvData.filter(r => r['Business Type'] === 'Personal').length,
    unassigned: csvData.filter(r => !r['Business Type'] || r['Business Type'] === 'Unassigned').length,
    alreadySubmitted: csvData.filter(r => {
      const submitted = (r['Already Submitted'] || '').toLowerCase().trim();
      return submitted === 'yes';
    }).length,
    // Receipt validation status counts
    receiptVerified: csvData.filter(r => r.receipt_validation_status === 'verified').length,
    receiptMismatch: csvData.filter(r => r.receipt_validation_status === 'mismatch').length,
    receiptError: csvData.filter(r => r.receipt_validation_status === 'error').length
  };

  // Update badge elements (badges are now shown on hover via CSS)
  const updateBadge = (id, count) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = count;
      // No need to control display - CSS handles visibility via hover
    }
  };

  updateBadge('all-count', counts.all);
  updateBadge('needs-review-count', counts.needsReview);
  updateBadge('good-count', counts.good);
  updateBadge('bad-count', counts.bad);
  updateBadge('missing-count', counts.missing);
  updateBadge('with-receipts-count', counts.withReceipts);
  updateBadge('not-needed-count', counts.notNeeded);
  updateBadge('refunds-count', counts.refunds);
  updateBadge('sec-count', counts.sec);
  updateBadge('business-count', counts.business);
  updateBadge('personal-count', counts.personal);
  updateBadge('unassigned-count', counts.unassigned);
  updateBadge('already-submitted-count', counts.alreadySubmitted);
  // Receipt validation status badges
  updateBadge('receipt-verified-count', counts.receiptVerified);
  updateBadge('receipt-mismatch-count', counts.receiptMismatch);
  updateBadge('receipt-error-count', counts.receiptError);
}

// Dashboard toggle - collapse/expand stats (starts expanded by default)
let dashboardExpanded = true;
function toggleDashboard() {
  const dashboard = document.getElementById('dashboard');
  const arrow = document.getElementById('dashboard-arrow');
  if (!dashboard) return;

  dashboardExpanded = !dashboardExpanded;
  // Use 'collapsed' class instead of 'expanded' since it's expanded by default
  dashboard.classList.toggle('collapsed', !dashboardExpanded);
  if (arrow) arrow.classList.toggle('expanded', dashboardExpanded);
}

// Image controls
function rotateImage() {
  currentRotation = (currentRotation + 90) % 360;
  loadReceipt();
}

function zoomIn() {
  if (panzoomInstance) panzoomInstance.zoomIn();
}

function zoomOut() {
  if (panzoomInstance) panzoomInstance.zoomOut();
}

function resetZoom() {
  currentRotation = 0; // Reset rotation first
  if (panzoomInstance) {
    panzoomInstance.reset();
    panzoomInstance.zoom(1.2); // Reset to 120%
  }
  loadReceipt(); // Reload to apply reset rotation
}

// Quick Viewer - Fast Navigation
let quickViewerReceipts = []; // All receipts with images
let quickViewerIndex = 0; // Current index in receipts array
let quickPanzoomInstance = null; // Panzoom instance for quick viewer

function openQuickViewer() {
  if (!selectedRow) return;

  // Build list of ALL receipts (filtered or all, depending on view)
  // Check all receipt sources: Receipt File, r2_url
  quickViewerReceipts = filteredData.filter(r => {
    const receiptFile = (r['Receipt File'] || '').trim();
    const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
    return receiptFile !== '' || r2Url !== '';
  });

  if (quickViewerReceipts.length === 0) {
    showToast('No receipts to view', '📄');
    return;
  }

  // Find current row in the list
  quickViewerIndex = quickViewerReceipts.findIndex(r => r._index === selectedRow._index);
  if (quickViewerIndex === -1) quickViewerIndex = 0;

  // Show modal and load first receipt
  document.getElementById('quick-viewer').classList.add('active');
  updateQuickViewer();

  // Focus modal for keyboard events
  document.getElementById('quick-viewer').focus();
}

function closeQuickViewer() {
  // Cleanup Panzoom instance
  if (quickPanzoomInstance) {
    quickPanzoomInstance.destroy();
    quickPanzoomInstance = null;
  }
  document.getElementById('quick-viewer').classList.remove('active');
}

function navigateQuickViewer(direction) {
  if (quickViewerReceipts.length === 0) return;

  quickViewerIndex += direction;

  // Wrap around
  if (quickViewerIndex < 0) quickViewerIndex = quickViewerReceipts.length - 1;
  if (quickViewerIndex >= quickViewerReceipts.length) quickViewerIndex = 0;

  updateQuickViewer();
}

function jumpToQuickReceipt(percent) {
  if (quickViewerReceipts.length === 0) return;
  quickViewerIndex = Math.floor((quickViewerReceipts.length - 1) * (percent / 10));
  updateQuickViewer();
}

function updateQuickViewer() {
  const receipt = quickViewerReceipts[quickViewerIndex];
  if (!receipt) return;

  const imageDiv = document.getElementById('quick-image');

  // Update title
  document.getElementById('quick-title').textContent =
    `${receipt['Chase Description']} - ${receipt['Chase Date']}`;

  // Preserve zoom controls and confidence badge
  const zoomControls = imageDiv.querySelector('.quick-zoom-controls');
  const confidenceBadge = imageDiv.querySelector('.match-confidence');

  // Check for R2 URL (cloud storage) first, then local file
  const r2Url = receipt['r2_url'] || receipt['R2 URL'] || receipt['receipt_url'] || '';
  const receiptFile = receipt['Receipt File'] || '';
  const hasReceipt = r2Url || receiptFile;

  // Check if marked as "not needed"
  const reviewStatus = (receipt['Review Status'] || '').toLowerCase().trim();
  if (reviewStatus === 'not needed') {
    imageDiv.innerHTML = `
      <div class="no-receipt" style="background:linear-gradient(135deg, rgba(34,197,94,0.1), rgba(22,163,74,0.05))">
        <div class="no-receipt-icon" style="font-size:64px">✅</div>
        <div class="no-receipt-text" style="color:#22c55e;font-weight:600">No Receipt Needed</div>
      </div>`;
    if (zoomControls) imageDiv.appendChild(zoomControls);
    if (confidenceBadge) imageDiv.appendChild(confidenceBadge);
  } else if (hasReceipt) {
    const imgEl = document.createElement('img');

    // Use R2 URL (cloud) if available, otherwise local path
    if (r2Url && r2Url.startsWith('http')) {
      imgEl.src = r2Url;
    } else if (receiptFile) {
      // Build local path - handle various formats
      if (receiptFile.startsWith('http')) {
        imgEl.src = receiptFile;
      } else if (receiptFile.startsWith('receipts/') || receiptFile.startsWith('incoming/')) {
        imgEl.src = `/${receiptFile}`;
      } else {
        imgEl.src = `/receipts/${receiptFile}`;
      }
    }

    imgEl.alt = 'Receipt';
    imgEl.style.transition = 'opacity 0.2s ease';
    imgEl.style.imageOrientation = 'from-image'; // Auto-handle EXIF orientation
    imgEl.id = 'quick-viewer-img';

    // Auto-rotation: detect if image needs rotation after load
    imgEl.onload = function() {
      // Auto-rotate landscape images (width > height * 1.3) to portrait
      if (imgEl.naturalWidth > imgEl.naturalHeight * 1.3) {
        imgEl.style.transform = 'rotate(90deg)';
      } else {
        imgEl.style.transform = 'none';
      }
    };

    // Error handling - try fallback if R2 URL fails
    imgEl.onerror = function() {
      if (r2Url && receiptFile && !imgEl.dataset.retried) {
        console.warn('R2 URL failed, trying local path:', receiptFile);
        imgEl.dataset.retried = 'true';
        imgEl.src = `/receipts/${receiptFile}`;
      } else {
        imageDiv.innerHTML = `
          <div class="no-receipt">
            <div class="no-receipt-icon">⚠️</div>
            <div class="no-receipt-text">Failed to load receipt</div>
            <div style="font-size:11px;color:var(--muted);margin-top:4px">Image may have been moved or deleted</div>
          </div>`;
      }
    };

    // Initial transform (will be updated in onload)
    imgEl.style.transform = 'none';

    // Clear and rebuild
    imageDiv.innerHTML = '';
    if (zoomControls) imageDiv.appendChild(zoomControls);
    if (confidenceBadge) imageDiv.appendChild(confidenceBadge);
    imageDiv.appendChild(imgEl);

    // Initialize Panzoom on new image
    setTimeout(() => {
      if (quickPanzoomInstance) {
        quickPanzoomInstance.destroy();
      }
      quickPanzoomInstance = Panzoom(imgEl, {
        maxScale: 5,
        minScale: 0.5,
        step: 0.2,
        contain: 'inside'
      });
    }, 50);
  } else {
    imageDiv.innerHTML = `
      <div class="no-receipt">
        <div class="no-receipt-icon">📄</div>
        <div class="no-receipt-text">No receipt attached</div>
        <div style="font-size:11px;color:var(--muted);margin-top:4px">Press A to AI-match or drag & drop</div>
      </div>`;
    if (zoomControls) imageDiv.appendChild(zoomControls);
    if (confidenceBadge) imageDiv.appendChild(confidenceBadge);
  }

  // Check if this is an AI-matched receipt
  const isAIMatched = receipt['AI Note'] && receipt['AI Note'].trim() !== '';
  const confidence = parseFloat(receipt['AI Confidence'] || 0);

  // Show/hide confidence badge
  const badge = document.getElementById('quick-match-badge');
  if (isAIMatched && confidence > 0) {
    badge.style.display = 'flex';
    document.getElementById('quick-confidence-text').textContent = `${confidence}% Match`;

    // Color code by confidence
    badge.classList.remove('high', 'medium', 'low');
    if (confidence >= 85) badge.classList.add('high');
    else if (confidence >= 70) badge.classList.add('medium');
    else badge.classList.add('low');
  } else {
    badge.style.display = 'none';
  }

  // Update data with match highlighting
  updateQuickDataRow('quick-merchant', receipt['Chase Description'] || '—', isAIMatched);

  const amt = parseFloat(receipt['Chase Amount'] || 0);
  const amtSign = amt > 0 ? '-' : '+';
  updateQuickDataRow('quick-amount', `${amtSign}$${Math.abs(amt).toFixed(2)}`, isAIMatched, true);

  updateQuickDataRow('quick-date', receipt['Chase Date'] || '—', isAIMatched);

  // Update Business Type dropdown
  const businessSelect = document.getElementById('quick-business');
  businessSelect.value = receipt['Business Type'] || '';

  // Update Category (read-only)
  document.getElementById('quick-category').textContent = receipt['Chase Category'] || '—';

  // Update Status dropdown
  const statusSelect = document.getElementById('quick-status');
  statusSelect.value = receipt['Review Status'] || '';

  // Update Notes textarea
  const notesTextarea = document.getElementById('quick-notes');
  notesTextarea.value = receipt['Notes'] || '';

  // Update AI Note textarea
  const aiNoteTextarea = document.getElementById('quick-ai-note');
  aiNoteTextarea.value = receipt['AI Note'] || '';

  // Update position indicator
  document.getElementById('quick-position').textContent =
    `${quickViewerIndex + 1} / ${quickViewerReceipts.length}`;

  // Update button states
  document.getElementById('quick-prev').disabled = false;
  document.getElementById('quick-next').disabled = false;

  // ✅ FIX: Update selectedRow so hotkeys (M, D, P, etc.) work on the correct transaction
  selectedRow = receipt;

  // Preload adjacent images for smooth navigation
  preloadAdjacentReceipts();
}

// Helper to update data row with match highlighting
function updateQuickDataRow(elementId, value, isMatched, isLarge = false) {
  const element = document.getElementById(elementId);
  const row = element.closest('.data-row');

  element.textContent = value;

  if (isMatched) {
    row.classList.add('matched');
  } else {
    row.classList.remove('matched');
  }
}

// Quick Viewer Zoom Functions
function quickZoom(delta) {
  if (quickPanzoomInstance) {
    const currentScale = quickPanzoomInstance.getScale();
    quickPanzoomInstance.zoom(currentScale + delta);
  }
}

function quickResetZoom() {
  if (quickPanzoomInstance) {
    quickPanzoomInstance.reset();
  }
}

// Handle keyboard shortcuts in textareas (Ctrl+Enter to save, Escape to blur)
function handleTextareaKeys(event, field) {
  // Ctrl+Enter or Cmd+Enter to save
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault();
    const textarea = event.target;
    quickUpdateField(field, textarea.value);
    textarea.blur(); // Remove focus after saving
    showToast(`${field} saved`, '✓');
  }
  // Escape to cancel and blur
  else if (event.key === 'Escape') {
    event.preventDefault();
    event.target.blur();
  }
}

// Quick Viewer Field Update - Updates database AND refreshes display
async function quickUpdateField(field, value) {
  const currentReceipt = quickViewerReceipts[quickViewerIndex];
  if (!currentReceipt) return;

  const rowIndex = currentReceipt._index;

  // Update local data immediately for responsive UI
  currentReceipt[field] = value;

  // Also update selectedRow if it's the same transaction
  if (selectedRow && selectedRow._index === rowIndex) {
    selectedRow[field] = value;
  }

  // Update in csvData array
  const csvIndex = csvData.findIndex(r => r._index === rowIndex);
  if (csvIndex !== -1) {
    csvData[csvIndex][field] = value;
  }

  // Update in filteredData array
  const filteredIndex = filteredData.findIndex(r => r._index === rowIndex);
  if (filteredIndex !== -1) {
    filteredData[filteredIndex][field] = value;
  }

  try {
    // Save to backend (SQLite + CSV)
    const response = await fetch('/update_row', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        _index: rowIndex,
        patch: {[field]: value}
      })
    });

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}`);
    }

    // ✅ FIX: Re-apply filters - this handles renderTable() + updateDashboard()
    applyFilters();

    // Update the quick viewer UI to reflect the change
    if (field === 'Review Status') {
      document.getElementById('quick-status').value = value;
    } else if (field === 'Business Type') {
      document.getElementById('quick-business').value = value;
    } else if (field === 'Notes') {
      document.getElementById('quick-notes').value = value;
    } else if (field === 'AI Note') {
      document.getElementById('quick-ai-note').value = value;
    }

    // Show success toast
    showToast(`${field} updated`, '✓');

    debugLog(`✅ Quick Viewer: Updated ${field} = "${value}" for transaction #${rowIndex}`);
  } catch (e) {
    showToast(`Failed to update ${field}: ${e.message}`, '❌');
    console.error(`❌ Quick Viewer update failed:`, e);
  }
}

function preloadAdjacentReceipts() {
  const preloadIndices = [quickViewerIndex - 1, quickViewerIndex + 1];

  preloadIndices.forEach(idx => {
    if (idx >= 0 && idx < quickViewerReceipts.length) {
      const receipt = quickViewerReceipts[idx];
      const r2Url = receipt['r2_url'] || receipt['R2 URL'] || receipt['receipt_url'] || '';
      const receiptFile = receipt['Receipt File'] || '';

      if (r2Url || receiptFile) {
        const img = new Image();
        // Use R2 URL if available, otherwise local path
        if (r2Url && r2Url.startsWith('http')) {
          img.src = r2Url;
        } else if (receiptFile) {
          if (receiptFile.startsWith('http')) {
            img.src = receiptFile;
          } else {
            img.src = `/receipts/${receiptFile}`;
          }
        }
      }
    }
  });
}

// Keyboard shortcuts for quick viewer
document.addEventListener('keydown', (e) => {
  const modal = document.getElementById('quick-viewer');
  if (!modal.classList.contains('active')) return;
  // Don't interfere with input fields, textareas, or select dropdowns
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

  const key = e.key.toLowerCase();

  switch(key) {
    case 'arrowleft':
      e.preventDefault();
      navigateQuickViewer(-1);
      break;
    case 'arrowright':
      e.preventDefault();
      navigateQuickViewer(1);
      break;
    case 'escape':
      e.preventDefault();
      closeQuickViewer();
      break;
    // Status hotkeys
    case 'g':
      e.preventDefault();
      quickUpdateField('Review Status', 'good');
      break;
    case 'b':
      e.preventDefault();
      quickUpdateField('Review Status', 'bad');
      break;
    case 'n':
      e.preventDefault();
      quickUpdateField('Review Status', 'not needed');
      break;
    case 'c':
      e.preventDefault();
      quickUpdateField('Review Status', '');
      break;
    // Business type hotkeys
    case 'm':
      e.preventDefault();
      quickUpdateField('Business Type', 'Secondary');
      break;
    case 'd':
      e.preventDefault();
      quickUpdateField('Business Type', 'Business');
      break;
    case 'p':
      e.preventDefault();
      quickUpdateField('Business Type', 'Personal');
      break;
    // Action hotkeys
    case 'x':
      e.preventDefault();
      detachReceipt();
      break;
    case 'a':
      e.preventDefault();
      aiMatch();
      break;
    case 'j':
      e.preventDefault();
      aiNote();
      break;
    case 'f':
      e.preventDefault();
      closeQuickViewer();
      openMissingReceiptModal();
      break;
    case '1': case '2': case '3': case '4': case '5':
    case '6': case '7': case '8': case '9':
      e.preventDefault();
      jumpToQuickReceipt(parseInt(e.key));
      break;
    case 'home':
      e.preventDefault();
      quickViewerIndex = 0;
      updateQuickViewer();
      break;
    case 'end':
      e.preventDefault();
      quickViewerIndex = quickViewerReceipts.length - 1;
      updateQuickViewer();
      break;
    case '+':
    case '=':
      e.preventDefault();
      quickZoom(0.2);
      break;
    case '-':
    case '_':
      e.preventDefault();
      quickZoom(-0.2);
      break;
    case '0':
      e.preventDefault();
      quickResetZoom();
      break;
  }
});


// ========================================================================
// MAIN TABLE HOTKEYS (Arrow Up/Down, G/B/N, M/D/P, X, Enter, A, J)
// ========================================================================
document.addEventListener('keydown', (e) => {
  // Skip if in quick viewer modal
  const quickViewer = document.getElementById('quick-viewer');
  if (quickViewer && quickViewer.classList.contains('active')) return;

  // Skip if typing in input/textarea
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  // Skip if no row selected
  if (!selectedRow) return;

  const key = e.key.toLowerCase();

  switch(key) {
    case 'arrowup':
      e.preventDefault();
      navigateTable(-1);  // Move selection up
      break;

    case 'arrowdown':
      e.preventDefault();
      navigateTable(1);  // Move selection down
      break;

    case 'g':
      e.preventDefault();
      updateField('Review Status', 'good');
      showToast('Marked as GOOD', '✓');
      break;

    case 'b':
      e.preventDefault();
      updateField('Review Status', 'bad');
      showToast('Marked as BAD', '✗');
      break;

    case 'n':
      e.preventDefault();
      updateField('Review Status', 'not needed');
      showToast('Marked as NOT NEEDED', 'ℹ️');
      break;

    case 'm':
      e.preventDefault();
      updateField('Business Type', 'Secondary');
      showToast('Business Type: Secondary', '🎵');
      break;

    case 'd':
      e.preventDefault();
      updateField('Business Type', 'Business');
      showToast('Business Type: Business', '🏠');
      break;

    case 'p':
      e.preventDefault();
      updateField('Business Type', 'Personal');
      showToast('Business Type: Personal', '👤');
      break;

    case 'x':
      e.preventDefault();
      if (confirm('Detach receipt from this transaction?')) {
        detachReceipt();
      }
      break;

    case 'enter':
      e.preventDefault();
      openQuickViewer(selectedRow);
      break;

    case 'a':
      e.preventDefault();
      aiMatch();
      break;

    case 'j':
      e.preventDefault();
      aiNote();
      break;

    case 'q':
      e.preventDefault();
      openQuickViewer();
      showToast('Quick Viewer Opened', '⚡');
      break;

    case 'f':
      e.preventDefault();
      openMissingReceiptModal();
      break;
  }
});

// Navigate table rows with arrow keys
function navigateTable(direction) {
  const currentIndex = filteredData.findIndex(row => row._index === selectedRow._index);
  if (currentIndex === -1) return;

  const newIndex = currentIndex + direction;

  if (newIndex >= 0 && newIndex < filteredData.length) {
    selectRow(filteredData[newIndex]);

    // Scroll selected row into view
    const selectedTr = document.querySelector('tr.selected');
    if (selectedTr) {
      selectedTr.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
}


// Modals
function toggleHotkeyMenu() {
  const modal = document.getElementById('hotkey-modal');
  modal.classList.toggle('active');
}

function toggleSettings() {
  const modal = document.getElementById('settings-modal');
  modal.classList.toggle('active');

  // Update all settings info when opening
  if (modal.classList.contains('active')) {
    updateSettingsInfo();
    checkGmailStatus();
    checkSystemHealth();
  }
}

// Update settings info with live data
async function updateSettingsInfo() {
  // Update transaction count
  const transactionCount = DATA ? DATA.length : 0;
  const countEl = document.getElementById('transaction-count-setting');
  if (countEl) {
    countEl.textContent = transactionCount.toLocaleString() + ' transactions';
  }

  // Check calendar status when settings open
  checkCalendarStatus();
}

// Calendar settings state
let calendarSettings = {
  enabled_calendars: [] // List of enabled calendar emails
};

// Check calendar connection status and load settings
async function checkCalendarStatus() {
  const statusEl = document.getElementById('calendar-connection-status');
  const detailEl = document.getElementById('calendar-status-detail');
  const accountsList = document.getElementById('calendar-accounts-list');

  if (statusEl) statusEl.textContent = 'Checking...';
  if (detailEl) detailEl.textContent = 'Connecting to calendar service...';

  try {
    const res = await fetch('/settings/calendar/status');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (!data.connected) {
      if (statusEl) {
        statusEl.textContent = '❌ Not Connected';
        statusEl.style.color = '#ff4e6a';
      }
      if (detailEl) detailEl.textContent = data.message || 'Calendar not configured';
      if (accountsList) accountsList.style.display = 'none';
      return;
    }

    // Connected - show account count
    const accountCount = data.account_count || 1;
    if (statusEl) {
      statusEl.textContent = `✅ ${accountCount} Calendar${accountCount > 1 ? 's' : ''} Connected`;
      statusEl.style.color = '#00ff88';
    }
    if (detailEl) detailEl.textContent = data.message || `${accountCount} account(s) linked`;

    // Populate calendar list with checkboxes
    if (accountsList && data.accounts && data.accounts.length > 0) {
      accountsList.style.display = 'block';
      accountsList.innerHTML = '<div style="font-size:12px;color:var(--muted);margin-bottom:8px">Select which calendars to use for context:</div>';

      // Load saved settings
      await loadCalendarSettings();

      data.accounts.forEach(account => {
        const isEnabled = calendarSettings.enabled_calendars.length === 0 ||
                         calendarSettings.enabled_calendars.includes(account.email);

        const row = document.createElement('div');
        row.className = 'settings-row';
        row.style.padding = '10px 12px';
        row.style.background = isEnabled ? 'rgba(0,255,136,.08)' : 'transparent';
        row.style.borderRadius = '8px';
        row.style.marginBottom = '6px';
        row.style.transition = 'background .2s';

        row.innerHTML = `
          <div style="display:flex;align-items:center;gap:10px;flex:1">
            <input type="checkbox"
                   id="cal-${account.email.replace(/[@.]/g, '-')}"
                   ${isEnabled ? 'checked' : ''}
                   onchange="toggleCalendar('${account.email}', this.checked)"
                   style="width:18px;height:18px;accent-color:#00ff88;cursor:pointer">
            <div>
              <div style="font-size:13px;font-weight:500;color:var(--ink)">${account.name || account.email}</div>
              <div style="font-size:11px;color:var(--muted)">${account.email}</div>
            </div>
          </div>
          <span class="badge ${account.connected ? 'badge-good' : 'badge-bad'}">${account.connected ? 'Active' : 'Error'}</span>
        `;

        accountsList.appendChild(row);
      });

      // Add save button
      const saveBtn = document.createElement('button');
      saveBtn.className = 'btn-primary';
      saveBtn.style.marginTop = '12px';
      saveBtn.style.width = '100%';
      saveBtn.innerHTML = '💾 Save Calendar Settings';
      saveBtn.onclick = saveCalendarSettings;
      accountsList.appendChild(saveBtn);
    }

  } catch (err) {
    console.error('Calendar status check failed:', err);
    if (statusEl) {
      statusEl.textContent = '⚠️ Error';
      statusEl.style.color = '#ffd85e';
    }
    if (detailEl) detailEl.textContent = 'Could not check calendar status';
  }
}

// Load saved calendar settings
async function loadCalendarSettings() {
  try {
    const res = await fetch('/settings/calendar/preferences');
    if (res.ok) {
      const data = await res.json();
      if (data.enabled_calendars) {
        calendarSettings.enabled_calendars = data.enabled_calendars;
      }
    }
  } catch (err) {
    debugLog('No saved calendar settings found, using defaults');
  }
}

// Toggle calendar enabled state
function toggleCalendar(email, enabled) {
  const row = document.getElementById(`cal-${email.replace(/[@.]/g, '-')}`).closest('.settings-row');
  if (row) {
    row.style.background = enabled ? 'rgba(0,255,136,.08)' : 'transparent';
  }

  if (enabled) {
    if (!calendarSettings.enabled_calendars.includes(email)) {
      calendarSettings.enabled_calendars.push(email);
    }
  } else {
    calendarSettings.enabled_calendars = calendarSettings.enabled_calendars.filter(e => e !== email);
  }
}

// Save calendar settings
async function saveCalendarSettings() {
  // Get all checked calendars
  const checkboxes = document.querySelectorAll('#calendar-accounts-list input[type="checkbox"]');
  const enabledCalendars = [];

  checkboxes.forEach(cb => {
    if (cb.checked) {
      // Extract email from id (cal-email-domain-com -> email@domain.com)
      const idParts = cb.id.replace('cal-', '').split('-');
      // Reconstruct email (last part after last dash is domain)
      const email = cb.id.replace('cal-', '').replace(/-/g, function(match, offset, str) {
        // Count dashes - replace all but the one before domain
        const remaining = str.substring(offset + 1);
        if (remaining.includes('-')) return '.';
        return '@';
      });
      enabledCalendars.push(email);
    }
  });

  try {
    const res = await fetch('/settings/calendar/preferences', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ enabled_calendars: enabledCalendars })
    });

    if (res.ok) {
      showToast('Calendar settings saved!', 'success');
      calendarSettings.enabled_calendars = enabledCalendars;
    } else {
      showToast('Failed to save settings', 'error');
    }
  } catch (err) {
    console.error('Save calendar settings failed:', err);
    showToast('Error saving settings', 'error');
  }
}

// Store last health data for details panel
let lastHealthData = null;

// Check all system services
async function checkSystemHealth() {
  const btn = document.getElementById('health-check-btn');
  if (btn) btn.innerHTML = '⏳ Checking...';

  // Show checking state on all cards
  const elements = ['db-status', 'r2-status', 'ai-status', 'gmail-health-status'];
  elements.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<span style="color:#fbbf24">...</span>';
  });

  try {
    const response = await fetch('/api/health');
    if (!response.ok) throw new Error('Health check failed');

    const health = await response.json();
    lastHealthData = health;

    // Update timestamp
    const timestamp = document.getElementById('health-timestamp');
    if (timestamp && health.timestamp) {
      const date = new Date(health.timestamp);
      timestamp.textContent = `Last checked: ${date.toLocaleTimeString()}`;
    }

    // Update overall health indicator
    const healthTitle = document.getElementById('health-title');
    const services = health.services || {};
    const allGood = services.database?.status === 'connected' &&
                   services.r2_storage?.status === 'connected' &&
                   services.gemini_ai?.status === 'configured';

    if (healthTitle) {
      healthTitle.innerHTML = allGood ? '🟢 System Health' : '🟡 System Health';
    }

    // Database status
    const dbStatus = document.getElementById('db-status');
    const dbIcon = document.getElementById('db-icon');
    const dbLatency = document.getElementById('db-latency');
    const dbTypeDesc = document.getElementById('db-type-desc');

    if (services.database) {
      const db = services.database;
      if (db.status === 'connected') {
        if (dbIcon) dbIcon.textContent = '✅';
        if (dbStatus) dbStatus.innerHTML = `<span style="color:#00ff88">${db.type?.toUpperCase() || 'OK'}</span>`;
        if (dbLatency) dbLatency.textContent = `${db.response_ms || '--'}ms`;
        if (dbTypeDesc) dbTypeDesc.textContent = db.type === 'mysql' ? 'MySQL on Railway' : 'SQLite - receipts.db';
      } else {
        if (dbIcon) dbIcon.textContent = '❌';
        if (dbStatus) dbStatus.innerHTML = '<span style="color:#ef4444">Error</span>';
        if (dbLatency) dbLatency.textContent = db.error ? 'Failed' : '--';
      }

      // Update receipt stats
      if (db.receipts) {
        const statTotal = document.getElementById('stat-total');
        const statReceipts = document.getElementById('stat-receipts');
        const statMissing = document.getElementById('stat-missing');
        const total = db.receipts.total || 0;
        const withReceipts = db.receipts.with_receipts || 0;
        const missing = total - withReceipts - (db.receipts.deleted || 0);

        if (statTotal) statTotal.textContent = total.toLocaleString();
        if (statReceipts) statReceipts.textContent = withReceipts.toLocaleString();
        if (statMissing) {
          statMissing.textContent = missing.toLocaleString();
          statMissing.style.color = missing > 0 ? '#fbbf24' : '#00ff88';
        }
      }
    }

    // R2 Storage status
    const r2Status = document.getElementById('r2-status');
    const r2Icon = document.getElementById('r2-icon');
    const r2Bucket = document.getElementById('r2-bucket');

    if (services.r2_storage) {
      const r2 = services.r2_storage;
      if (r2.status === 'connected') {
        if (r2Icon) r2Icon.textContent = '✅';
        if (r2Status) r2Status.innerHTML = '<span style="color:#00ff88">Connected</span>';
        if (r2Bucket) r2Bucket.textContent = r2.bucket || 'receipts';
      } else {
        if (r2Icon) r2Icon.textContent = '⚠️';
        if (r2Status) r2Status.innerHTML = '<span style="color:#fbbf24">Not Set</span>';
        if (r2Bucket) r2Bucket.textContent = 'configure';
      }
    }

    // Gemini AI status
    const aiStatus = document.getElementById('ai-status');
    const aiIcon = document.getElementById('ai-icon');
    const aiAccuracy = document.getElementById('ai-accuracy');
    const geminiBadge = document.getElementById('gemini-badge');

    if (services.gemini_ai) {
      const ai = services.gemini_ai;
      if (ai.status === 'configured') {
        if (aiIcon) aiIcon.textContent = '✅';
        if (aiStatus) aiStatus.innerHTML = '<span style="color:#00ff88">Ready</span>';
        if (aiAccuracy) aiAccuracy.textContent = services.ocr?.accuracy || '99%+';
        if (geminiBadge) geminiBadge.className = 'badge badge-good';
      } else {
        if (aiIcon) aiIcon.textContent = '⚠️';
        if (aiStatus) aiStatus.innerHTML = '<span style="color:#fbbf24">No Key</span>';
        if (aiAccuracy) aiAccuracy.textContent = 'Donut fallback';
        if (geminiBadge) geminiBadge.className = 'badge badge-neutral';
      }
    }

    // Gmail status
    const gmailHealthStatus = document.getElementById('gmail-health-status');
    const gmailIcon = document.getElementById('gmail-icon');
    const gmailSummary = document.getElementById('gmail-accounts-summary');

    if (services.gmail) {
      const gmail = services.gmail;
      const connected = gmail.connected_count || 0;
      const total = gmail.accounts?.length || 3;

      if (gmailHealthStatus) {
        gmailHealthStatus.innerHTML = `<span style="color:${connected > 0 ? '#00ff88' : '#fbbf24'}">${connected}/${total}</span>`;
      }
      if (gmailIcon) gmailIcon.textContent = connected === total ? '✅' : connected > 0 ? '📧' : '⚠️';
      if (gmailSummary) gmailSummary.textContent = connected === total ? 'all connected' : 'accounts';
    }

    if (btn) btn.innerHTML = '🔄 Check All Services';
    showToast('System health check complete', 'success');

  } catch (error) {
    console.error('Health check error:', error);
    if (btn) btn.innerHTML = '🔄 Check All Services';

    // Show error state
    const dbStatus = document.getElementById('db-status');
    if (dbStatus) dbStatus.innerHTML = '<span style="color:#ef4444">Offline</span>';

    showToast('Health check failed: ' + error.message, 'error');
  }
}

// Toggle health details panel
function toggleHealthDetails(service) {
  const panel = document.getElementById('health-details-panel');
  const title = document.getElementById('health-details-title');
  const content = document.getElementById('health-details-content');

  if (!lastHealthData || !lastHealthData.services) {
    showToast('Run health check first', 'info');
    return;
  }

  // If already showing this service, close it
  if (panel.style.display !== 'none' && panel.dataset.service === service) {
    panel.style.display = 'none';
    return;
  }

  panel.dataset.service = service;
  const services = lastHealthData.services;

  let html = '';
  switch (service) {
    case 'db':
      const db = services.database || {};
      title.textContent = '💾 Database Details';
      html = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <div><strong>Type:</strong> ${db.type || 'Unknown'}</div>
          <div><strong>Host:</strong> ${db.host || 'Local'}</div>
          <div><strong>Status:</strong> ${db.status || 'Unknown'}</div>
          <div><strong>Latency:</strong> ${db.response_ms || '--'}ms</div>
          ${db.transaction_count ? `<div><strong>Transactions:</strong> ${db.transaction_count.toLocaleString()}</div>` : ''}
          ${db.receipts ? `<div><strong>With Receipts:</strong> ${db.receipts.with_receipts?.toLocaleString() || 0}</div>` : ''}
        </div>
        ${db.error ? `<div style="color:#ef4444;margin-top:8px">Error: ${db.error}</div>` : ''}
      `;
      break;

    case 'r2':
      const r2 = services.r2_storage || {};
      title.textContent = '☁️ R2 Storage Details';
      html = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <div><strong>Status:</strong> ${r2.status || 'Unknown'}</div>
          <div><strong>Bucket:</strong> ${r2.bucket || 'Not set'}</div>
          ${r2.endpoint ? `<div><strong>Account:</strong> ${r2.endpoint}</div>` : ''}
        </div>
        <div style="margin-top:8px;font-size:11px;color:var(--muted)">
          Receipt images are stored in Cloudflare R2 for fast global access.
        </div>
      `;
      break;

    case 'ai':
      const ai = services.gemini_ai || {};
      const ocr = services.ocr || {};
      title.textContent = '🤖 AI & OCR Details';
      html = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
          <div><strong>Gemini:</strong> ${ai.status || 'Unknown'}</div>
          <div><strong>OCR Provider:</strong> ${ocr.provider || 'Unknown'}</div>
          <div><strong>Accuracy:</strong> ${ocr.accuracy || 'Unknown'}</div>
          ${ai.key_prefix ? `<div><strong>API Key:</strong> ${ai.key_prefix}</div>` : ''}
        </div>
        <div style="margin-top:8px;font-size:11px;color:var(--muted)">
          Gemini Vision extracts merchant, date, and amount from receipt images.
        </div>
      `;
      break;

    case 'gmail':
      const gmail = services.gmail || {};
      title.textContent = '📧 Gmail Integration';
      html = '<div style="display:flex;flex-direction:column;gap:6px">';
      if (gmail.accounts && gmail.accounts.length > 0) {
        gmail.accounts.forEach(acc => {
          const statusColor = acc.connected ? '#00ff88' : '#fbbf24';
          const statusText = acc.connected ? 'Connected' : 'Not connected';
          html += `
            <div style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border)">
              <span>${acc.email}</span>
              <span style="color:${statusColor};font-size:11px">${statusText}</span>
            </div>
          `;
        });
      } else {
        html += '<div>No Gmail accounts configured</div>';
      }
      html += '</div>';
      html += `<div style="margin-top:8px;font-size:11px;color:var(--muted)">
        Gmail integration searches your inbox for receipt attachments.
      </div>`;
      break;
  }

  content.innerHTML = html;
  panel.style.display = 'block';
}

function closeHealthDetails() {
  const panel = document.getElementById('health-details-panel');
  panel.style.display = 'none';
}

// Manual Entry Modal
function openManualEntryModal() {
  const modal = document.getElementById('manual-entry-modal');
  modal.classList.add('active');

  // Set today's date as default
  const today = new Date().toISOString().split('T')[0];
  document.getElementById('manual-date').value = today;

  // Reset form
  document.getElementById('manual-entry-form').reset();
  document.getElementById('manual-date').value = today; // Re-set after reset
}

function closeManualEntryModal() {
  const modal = document.getElementById('manual-entry-modal');
  modal.classList.remove('active');
  document.getElementById('manual-entry-form').reset();

  // Reset OCR zone
  const dropZone = document.getElementById('ocr-drop-zone');
  dropZone.classList.remove('processing');
  document.getElementById('ocr-status').classList.remove('show', 'success', 'error');
  document.getElementById('ocr-preview').classList.remove('show');

  // Reset the stored receipt filename
  lastOCRReceiptFilename = null;
}

// ========================================================================
// MISSING RECEIPT FORM MODAL
// ========================================================================

function openMissingReceiptModal() {
  if (!selectedRow) {
    showToast('Select a transaction first', '⚠️');
    return;
  }

  // Check if transaction already has a receipt
  const hasReceipt = selectedRow['Receipt File'] || selectedRow['receipt_file'];
  if (hasReceipt) {
    if (!confirm('This transaction already has a receipt attached. Generate a Missing Receipt Form anyway?')) {
      return;
    }
  }

  const modal = document.getElementById('missing-receipt-modal');
  modal.classList.add('active');

  // Populate transaction details
  const merchant = selectedRow['mi_merchant'] || selectedRow['MI Merchant'] || selectedRow['Chase Description'] || selectedRow['chase_description'] || 'Unknown';
  const amount = parseFloat(selectedRow['Chase Amount'] || selectedRow['chase_amount'] || 0);
  const date = selectedRow['Chase Date'] || selectedRow['chase_date'] || '';

  document.getElementById('mrf-merchant').textContent = merchant;
  document.getElementById('mrf-amount').textContent = `$${Math.abs(amount).toFixed(2)}`;

  // Format date
  if (date) {
    try {
      const d = new Date(date);
      document.getElementById('mrf-date').textContent = d.toLocaleDateString('en-US');
    } catch {
      document.getElementById('mrf-date').textContent = date;
    }
  }

  // Pre-select company based on Business Type
  const bizType = (selectedRow['Business Type'] || selectedRow['business_type'] || '').toLowerCase();
  const companySelect = document.getElementById('mrf-company');
  if (bizType.includes('music') || bizType.includes('sec') || bizType.includes('rodeo')) {
    companySelect.value = 'sec';
  } else {
    companySelect.value = 'business';
  }

  // Reset form fields
  document.getElementById('mrf-reason-select').value = '';
  document.getElementById('mrf-reason').value = '';
  document.getElementById('mrf-is-meal').checked = false;
  document.getElementById('mrf-meal-section').style.display = 'none';
  document.getElementById('mrf-attendees').value = '';
  document.getElementById('mrf-purpose').value = '';

  // Check if this looks like a meal expense (restaurant/dining category)
  const category = (selectedRow['mi_category'] || selectedRow['MI Category'] || selectedRow['Category'] || '').toLowerCase();
  if (category.includes('restaurant') || category.includes('dining') || category.includes('food') || category.includes('meal')) {
    document.getElementById('mrf-is-meal').checked = true;
    toggleMealSection();
  }
}

function closeMissingReceiptModal() {
  const modal = document.getElementById('missing-receipt-modal');
  modal.classList.remove('active');
}

function updateReasonField() {
  const select = document.getElementById('mrf-reason-select');
  const input = document.getElementById('mrf-reason');

  if (select.value === 'custom') {
    input.value = '';
    input.focus();
  } else if (select.value) {
    input.value = select.value;
  }
}

function toggleMealSection() {
  const checkbox = document.getElementById('mrf-is-meal');
  const section = document.getElementById('mrf-meal-section');
  section.style.display = checkbox.checked ? 'block' : 'none';
}

async function submitMissingReceiptForm() {
  if (!selectedRow) {
    showToast('No transaction selected', '❌');
    return;
  }

  const reason = document.getElementById('mrf-reason').value.trim();
  if (!reason) {
    showToast('Please enter a reason', '⚠️');
    document.getElementById('mrf-reason').focus();
    return;
  }

  const company = document.getElementById('mrf-company').value;
  const isMeal = document.getElementById('mrf-is-meal').checked;
  const attendees = isMeal ? document.getElementById('mrf-attendees').value.trim() : '';
  const purpose = isMeal ? document.getElementById('mrf-purpose').value.trim() : '';

  showToast('Generating Missing Receipt Form...', '📝');

  try {
    const response = await fetch('/generate_missing_receipt_form', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        _index: selectedRow._index,
        reason: reason,
        company: company,
        meal_attendees: attendees,
        meal_purpose: purpose
      })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();

    if (result.ok) {
      // Update local data
      selectedRow['Receipt File'] = result.filename;
      selectedRow['receipt_file'] = result.filename;
      selectedRow['Review Status'] = 'good';
      selectedRow['Notes'] = `Missing Receipt Form - ${reason}`;

      // Refresh UI
      renderTable();
      updateDashboard();
      loadReceipt();

      closeMissingReceiptModal();
      showToast(`Missing Receipt Form generated!`, '✅');
    } else {
      showToast(`Error: ${result.error}`, '❌');
    }
  } catch (error) {
    console.error('Error generating form:', error);
    showToast(`Failed to generate form: ${error.message}`, '❌');
  }
}

// OCR Drag & Drop Functionality
function initOCRDropZone() {
  const dropZone = document.getElementById('ocr-drop-zone');
  const fileInput = document.getElementById('ocr-file-input');
  const preview = document.getElementById('ocr-preview');
  const status = document.getElementById('ocr-status');

  // Click to upload
  dropZone.addEventListener('click', (e) => {
    if (e.target === dropZone || e.target.closest('.ocr-drop-icon, .ocr-drop-text, .ocr-drop-hint')) {
      fileInput.click();
    }
  });

  // File input change
  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      processReceiptImage(e.target.files[0]);
    }
  });

  // Drag and drop events
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dragover');
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');

    const file = e.dataTransfer.files[0];
    if (file && (file.type.startsWith('image/') || file.type === 'application/pdf')) {
      processReceiptImage(file);
    } else {
      showOCRStatus('Please drop an image or PDF file', 'error');
    }
  });
}

// Store the receipt filename and R2 URL from OCR for use in submitManualEntry
let lastOCRReceiptFilename = null;
let lastOCRReceiptR2Url = null;

async function processReceiptImage(file) {
  const dropZone = document.getElementById('ocr-drop-zone');
  const preview = document.getElementById('ocr-preview');
  const status = document.getElementById('ocr-status');

  // Reset stored filename and R2 URL
  lastOCRReceiptFilename = null;
  lastOCRReceiptR2Url = null;

  // Show preview
  const reader = new FileReader();
  reader.onload = (e) => {
    preview.src = e.target.result;
    preview.classList.add('show');
  };
  reader.readAsDataURL(file);

  // Show processing state
  dropZone.classList.add('processing');
  showOCRStatus('🔍 Processing receipt with AI...', 'processing');

  try {
    // Upload to OCR API
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('/api/ocr/process', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();

    if (result.success) {
      // Auto-fill form fields
      if (result.merchant) {
        document.getElementById('manual-merchant').value = result.merchant;
      }

      if (result.date) {
        document.getElementById('manual-date').value = result.date;
      }

      if (result.total) {
        document.getElementById('manual-amount').value = result.total;
      }

      // IMPORTANT: Store the filename and R2 URL for later use when submitting the form
      if (result.filename) {
        lastOCRReceiptFilename = result.filename;
        debugLog('Receipt saved as:', result.filename);
      }
      // Store R2 URL (check both field names for compatibility)
      if (result.receipt_url || result.r2_url) {
        lastOCRReceiptR2Url = result.receipt_url || result.r2_url;
        debugLog('Receipt uploaded to R2:', lastOCRReceiptR2Url);
      }

      // Show success with confidence
      const confidence = Math.round(result.confidence * 100);
      const engines = result.engines_used ? result.engines_used.join(', ') : 'OCR';
      const uploadedTo = (result.receipt_url || result.r2_url) ? '☁️' : '💾';
      showOCRStatus(
        `${uploadedTo} Extracted! ${result.filename || 'N/A'} (${confidence}%)`,
        'success'
      );
    } else {
      showOCRStatus(`❌ ${result.error || 'Failed to process receipt'}`, 'error');
    }
  } catch (error) {
    console.error('OCR Error:', error);
    showOCRStatus('❌ Failed to connect to OCR service', 'error');
  } finally {
    dropZone.classList.remove('processing');
  }
}

function showOCRStatus(message, type) {
  const status = document.getElementById('ocr-status');
  status.textContent = message;
  status.className = 'ocr-status show';
  if (type) {
    status.classList.add(type);
  }
}

// Initialize OCR when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
  initOCRDropZone();
});

function updateCategoryOptions() {
  const businessType = document.getElementById('manual-business-type').value;
  const categorySelect = document.getElementById('manual-category');

  // Define categories by business type (placeholder - user will provide actual categories)
  const categories = {
    'Secondary': [
      'Artist Management',
      'Event Production',
      'Marketing & Advertising',
      'Venue Rental',
      'Equipment',
      'Travel & Lodging',
      'Meals & Entertainment',
      'Professional Services',
      'Other'
    ],
    'Business': [
      'Artist Development',
      'Recording & Production',
      'Marketing & PR',
      'Touring & Live Events',
      'Merchandising',
      'Professional Services',
      'Meals & Entertainment',
      'Travel',
      'Other'
    ],
    'Personal': [
      'Business Meals',
      'Travel',
      'Office Supplies',
      'Professional Development',
      'Subscriptions',
      'Other'
    ]
  };

  // Clear and repopulate
  categorySelect.innerHTML = '<option value="">Select Category (optional)</option>';

  if (businessType && categories[businessType]) {
    categories[businessType].forEach(cat => {
      const option = document.createElement('option');
      option.value = cat;
      option.textContent = cat;
      categorySelect.appendChild(option);
    });
  }
}

async function submitManualEntry(event) {
  event.preventDefault();

  const date = document.getElementById('manual-date').value;
  const merchant = document.getElementById('manual-merchant').value;
  const amount = parseFloat(document.getElementById('manual-amount').value);
  const businessType = document.getElementById('manual-business-type').value;
  const category = document.getElementById('manual-category').value;
  const notes = document.getElementById('manual-notes').value;

  if (!date || !merchant || !amount || !businessType) {
    showToast('Please fill in all required fields', '⚠️');
    return;
  }

  showToast('Adding manual entry...', '✍️');

  try {
    // Build request body, including receipt_file if we have one from OCR
    const requestBody = {
      date,
      merchant,
      amount,
      business_type: businessType,
      category,
      notes
    };

    // Include the receipt file and R2 URL from OCR if available
    if (lastOCRReceiptFilename) {
      requestBody.receipt_file = lastOCRReceiptFilename;
      debugLog('Including receipt file:', lastOCRReceiptFilename);
    }
    if (lastOCRReceiptR2Url) {
      requestBody.r2_url = lastOCRReceiptR2Url;
      debugLog('Including R2 URL:', lastOCRReceiptR2Url);
    }

    const res = await fetch('/add_manual_expense', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(requestBody)
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.ok) {
      // Add to local data
      csvData.push(data.expense);
      filteredData = [...csvData];

      // Refresh table and dashboard
      renderTable();
      updateDashboard();

      // Close modal
      closeManualEntryModal();

      showToast('Manual expense added successfully!', '✅');
    } else {
      showToast('Failed to add expense: ' + (data.error || 'Unknown error'), '❌');
    }
  } catch (e) {
    showToast('Failed to add expense: ' + e.message, '❌');
  }
}

// Close modal on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const modal = document.getElementById('manual-entry-modal');
    if (modal.classList.contains('active')) {
      closeManualEntryModal();
    }
  }
});

// Theme - unified with tallyups-theme
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme') || 'dark';
  const newTheme = current === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', newTheme);
  localStorage.setItem('tallyups-theme', newTheme);
  showToast('Theme changed', '🎨');
}

function loadTheme() {
  const saved = localStorage.getItem('tallyups-theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
}

// Logout
function logout() {
  if (confirm('Are you sure you want to logout?')) {
    window.location.href = '/logout';
  }
}

// Filters
function applyFilters() {
  let filtered = [...csvData];

  const activeFilter = document.querySelector('.chip[data-filter].active');
  if (activeFilter) {
    const filter = activeFilter.dataset.filter;
    if (filter === 'needs-review') {
      // Show items that haven't been reviewed yet (empty status or not finalized)
      // ✅ MUST have a receipt to be reviewed - no receipt = missing receipts
      filtered = filtered.filter(r => {
        const status = (r['Review Status'] || '').toLowerCase().trim();
        const receiptFile = (r['Receipt File'] || '').trim();
        const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
        const hasReceipt = receiptFile !== '' || r2Url !== '';
        return hasReceipt && (!status || (status !== 'good' && status !== 'bad' && status !== 'not needed'));
      });
    }
    else if (filter === 'good') {
      // ✅ MUST have a receipt to be marked good - no receipt = missing receipts
      filtered = filtered.filter(r => {
        const receiptFile = (r['Receipt File'] || '').trim();
        const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
        const hasReceipt = receiptFile !== '' || r2Url !== '';
        return hasReceipt && r['Review Status'] === 'good';
      });
    }
    else if (filter === 'bad') {
      // ✅ MUST have a receipt to be marked bad - no receipt = missing receipts
      filtered = filtered.filter(r => {
        const receiptFile = (r['Receipt File'] || '').trim();
        const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
        const hasReceipt = receiptFile !== '' || r2Url !== '';
        return hasReceipt && r['Review Status'] === 'bad';
      });
    }
    else if (filter === 'missing') {
      // Missing = no receipt (file or r2) AND not marked as "not needed"
      filtered = filtered.filter(r => {
        const receiptFile = (r['Receipt File'] || '').trim();
        const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
        const status = (r['Review Status'] || '').toLowerCase().trim();
        const hasReceipt = receiptFile !== '' || r2Url !== '';
        return !hasReceipt && status !== 'not needed';
      });
    }
    else if (filter === 'with-receipts') {
      // With receipts = has a receipt file or r2_url
      filtered = filtered.filter(r => {
        const receiptFile = (r['Receipt File'] || '').trim();
        const r2Url = (r.r2_url || r['R2 URL'] || '').trim();
        return receiptFile !== '' || r2Url !== '';
      });
    }
    else if (filter === 'not-needed') filtered = filtered.filter(r => r['Review Status'] === 'not needed');
    else if (filter === 'refunds') {
      // ✅ Refunds = negative amounts OR review_status = refund
      filtered = filtered.filter(r => {
        const amount = parseFloat(r['Chase Amount'] || r['Amount'] || 0);
        return amount < 0 || r['Review Status'] === 'refund';
      });
    }
    else if (filter === 'already-submitted') {
      // ✅ Already Submitted = expenses marked as already submitted
      filtered = filtered.filter(r => {
        const submitted = (r['Already Submitted'] || '').toLowerCase().trim();
        return submitted === 'yes';
      });
    }
    // Receipt validation status filters
    else if (filter === 'receipt-verified') {
      // ✅ Receipt verified by AI vision
      filtered = filtered.filter(r => r.receipt_validation_status === 'verified');
    }
    else if (filter === 'receipt-mismatch') {
      // ✗ Receipt doesn't match transaction (wrong date, amount, or merchant)
      filtered = filtered.filter(r => r.receipt_validation_status === 'mismatch');
    }
    else if (filter === 'receipt-error') {
      // ⚠ Error during validation (download failed, API error, etc)
      filtered = filtered.filter(r => r.receipt_validation_status === 'error');
    }
  }

  const activeBiz = document.querySelector('.chip[data-biz].active');
  if (activeBiz) {
    const bizType = activeBiz.dataset.biz;
    if (bizType === 'Unassigned') {
      // Show transactions with NULL, empty, or missing Business Type
      filtered = filtered.filter(r => {
        const bt = r['Business Type'];
        return !bt || bt === '' || bt === 'None' || bt === null;
      });
    } else {
      filtered = filtered.filter(r => r['Business Type'] === bizType);
    }
  }

  const activeConfidence = document.querySelector('.chip[data-confidence].active');
  if (activeConfidence) {
    const confLevel = activeConfidence.dataset.confidence;
    filtered = filtered.filter(r => {
      const conf = parseFloat(r['AI Confidence']) || 0;
      const hasReceipt = r['Receipt File'];

      if (confLevel === 'excellent') return hasReceipt && conf >= 90;
      if (confLevel === 'good-range') return hasReceipt && conf >= 70 && conf < 90;
      if (confLevel === 'needs-review') return hasReceipt && conf > 0 && conf < 70;
      if (confLevel === 'none') return hasReceipt && conf === 0;
      return true;
    });
  }

  const search = document.getElementById('search').value.toLowerCase().trim();
  if (search) {
    // Check if search is a number/amount (e.g., "22.44", "$22.44", "22")
    const searchAmount = parseFloat(search.replace(/[$,]/g, ''));
    const isAmountSearch = !isNaN(searchAmount) && /^[$]?[\d,]+\.?\d*$/.test(search.replace(/\s/g, ''));

    filtered = filtered.filter(r => {
      // Text search: check description and notes
      const textMatch =
        (r['Chase Description'] || '').toLowerCase().includes(search) ||
        (r['Notes'] || '').toLowerCase().includes(search);

      if (textMatch) return true;

      // Amount search: check if amount matches
      if (isAmountSearch) {
        const amount = parseFloat(r['Chase Amount'] || r['Amount'] || 0);
        const absAmount = Math.abs(amount);

        // Exact match (within 1 cent for floating point)
        if (Math.abs(absAmount - searchAmount) < 0.01) return true;

        // Also allow partial match for the amount string (e.g., "22" matches "22.50")
        const amountStr = absAmount.toFixed(2);
        if (amountStr.includes(search.replace(/[$,]/g, ''))) return true;
      }

      return false;
    });
  }

  filteredData = filtered;
  renderTable();
  updateDashboard();
}

// Event Listeners
function setupEventListeners() {
  // Filters - Toggle on/off behavior
  document.querySelectorAll('.chip[data-filter]').forEach(chip => {
    chip.addEventListener('click', () => {
      // If already active, deactivate (show all)
      if (chip.classList.contains('active')) {
        chip.classList.remove('active');
      } else {
        // Otherwise, activate this one and deactivate others
        document.querySelectorAll('.chip[data-filter]').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
      }
      applyFilters();
    });
  });

  // Business Type Filters - Toggle on/off behavior
  document.querySelectorAll('.chip[data-biz]').forEach(chip => {
    chip.addEventListener('click', () => {
      // If already active, deactivate (show all)
      if (chip.classList.contains('active')) {
        chip.classList.remove('active');
      } else {
        // Otherwise, activate this one and deactivate others
        document.querySelectorAll('.chip[data-biz]').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
      }
      applyFilters();
    });
  });

  document.getElementById('search').addEventListener('input', applyFilters);

  // Table sorting
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (sortColumn === col) {
        sortAsc = !sortAsc;
      } else {
        sortColumn = col;
        sortAsc = true;
      }

      filteredData.sort((a, b) => {
        let aVal = a[col] || '';
        let bVal = b[col] || '';
        if (col === 'Chase Amount') {
          aVal = parseFloat(aVal) || 0;
          bVal = parseFloat(bVal) || 0;
        }
        return sortAsc ?
          (aVal > bVal ? 1 : -1) :
          (aVal < bVal ? 1 : -1);
      });

      renderTable();

      document.querySelectorAll('th').forEach(h => h.classList.remove('sorted', 'asc'));
      th.classList.add('sorted');
      if (sortAsc) th.classList.add('asc');
    });
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT') return;

    const key = e.key.toLowerCase();

    if (key === 'escape') {
      closeQuickViewer();
      toggleHotkeyMenu();
      toggleSettings();
    } else if (key === '?') {
      e.preventDefault();
      toggleHotkeyMenu();
    } else if (key === 'q') {
      e.preventDefault();
      openQuickViewer();
    } else if (key === 'a') {
      e.preventDefault();
      aiMatch();
    } else if (key === 'j') {
      e.preventDefault();
      aiNote();
    } else if (key === 'x') {
      e.preventDefault();
      detachReceipt();
    } else if (key === 'g') {
      e.preventDefault();
      updateField('Review Status', 'good');
    } else if (key === 'b') {
      e.preventDefault();
      updateField('Review Status', 'bad');
    } else if (key === 'n') {
      e.preventDefault();
      updateField('Review Status', 'not needed');
    } else if (key === 'c') {
      e.preventDefault();
      updateField('Review Status', '');
    } else if (key === 'm') {
      e.preventDefault();
      updateField('Business Type', 'Secondary');
    } else if (key === 'd') {
      e.preventDefault();
      updateField('Business Type', 'Business');
    } else if (key === 'p') {
      e.preventDefault();
      updateField('Business Type', 'Personal');
    } else if (key === 'r') {
      e.preventDefault();
      rotateImage();
    } else if (key === '0') {
      e.preventDefault();
      resetZoom();
    } else if (key === '+' || key === '=') {
      e.preventDefault();
      zoomIn();
    } else if (key === '-') {
      e.preventDefault();
      zoomOut();
    } // ✅ FIX: Removed duplicate arrow key handlers (already handled at line ~2250)
    // else if (key === 'arrowup') {
    //   e.preventDefault();
    //   navigateRow(-1);
    // } else if (key === 'arrowdown') {
    //   e.preventDefault();
    //   navigateRow(1);
    // }
    else if (e.ctrlKey && key === 's') {
      e.preventDefault();
      saveCSV();
    }
    else if (e.ctrlKey && key === 'z') {
      e.preventDefault();
      undo();
    }
    else if (key === '/') {
      e.preventDefault();
      document.getElementById('search').focus();
    }
    else if (key === 'f' && !e.ctrlKey) {
      e.preventDefault();
      openMissingReceiptModal();
    }
    else if (key === 'arrowup') {
      e.preventDefault();
      navigateRow(-1);
    }
    else if (key === 'arrowdown') {
      e.preventDefault();
      navigateRow(1);
    }
  });
}

function navigateRow(delta) {
  if (!selectedRow || filteredData.length === 0) return;

  const idx = filteredData.findIndex(r => r._index === selectedRow._index);
  const newIdx = Math.max(0, Math.min(filteredData.length - 1, idx + delta));
  selectRow(filteredData[newIdx]);

  // Scroll into view
  const rows = document.querySelectorAll('#tbody tr');
  if (rows[newIdx]) {
    rows[newIdx].scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }
}

// Drag & Drop
function setupDragDrop() {
  const viewer = document.getElementById('viewer-content');

  ['dragenter', 'dragover'].forEach(evt => {
    viewer.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      viewer.style.borderColor = 'var(--brand)';
    });
  });

  ['dragleave', 'drop'].forEach(evt => {
    viewer.addEventListener(evt, (e) => {
      e.preventDefault();
      e.stopPropagation();
      viewer.style.borderColor = '';
    });
  });

  viewer.addEventListener('drop', async (e) => {
    const file = e.dataTransfer.files[0];
    if (!file || !(file.type.startsWith('image/') || file.type === 'application/pdf')) {
      return showToast('Please drop an image or PDF file', '⚠️');
    }

    // If a row is selected, use upload method
    if (selectedRow) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('_index', selectedRow._index);

      try {
        showToast('Uploading receipt...', '⏱️');
        const res = await fetch('/upload_receipt', {
          method: 'POST',
          body: formData
        });
        const data = await res.json();
        if (data.ok) {
          selectedRow['Receipt File'] = data.filename;
          const r2Url = data.r2_url || data.receipt_url;
          if (r2Url) {
            selectedRow.r2_url = r2Url;
          }
          applyFilters();  // Re-filter to update counts
          loadReceipt();
          const cloudIcon = r2Url ? '☁️' : '📎';
          showToast(`${cloudIcon} Receipt attached`, '✓');
        }
      } catch (e) {
        showToast('Upload failed: ' + e.message, '❌');
      }
      return;
    }

    // No row selected - use smart upload with Gemini OCR + create new transaction
    const formData = new FormData();
    formData.append('file', file);

    try {
      showToast('🔍 Processing receipt with Gemini AI...', '⏱️');

      // Try to match first
      const res = await fetch('/upload_receipt_auto', {
        method: 'POST',
        body: formData
      });
      const data = await res.json();

      if (data.ok && data.matched && data.auto_attached) {
        // Success! Auto-matched and attached to existing transaction
        showToast(`✅ ${data.message}`, '✓');
        await loadCSV();

        const matchedRow = csvData.find(r => r._index === data.transaction._index);
        if (matchedRow) {
          selectRow(matchedRow);
        }
      } else if (data.ok && data.matched && !data.auto_attached) {
        // Found possible match but confidence too low
        showToast(`🤔 ${data.message}`, '⚠️');

        const matchedRow = csvData.find(r => r._index === data.transaction._index);
        if (matchedRow) {
          selectRow(matchedRow);
        }
      } else {
        // No match found OR OCR failed - CREATE NEW TRANSACTION
        showToast('🆕 Creating new transaction from receipt...', '⏱️');

        // Re-upload to create new transaction
        const newFormData = new FormData();
        newFormData.append('file', file);

        const newRes = await fetch('/upload_receipt_new', {
          method: 'POST',
          body: newFormData
        });
        const newData = await newRes.json();

        if (newData.ok) {
          showToast(`✅ ${newData.message}`, '✓');
          await loadCSV();

          // Select the new transaction
          const newRow = csvData.find(r => r._index === newData.transaction._index);
          if (newRow) {
            selectRow(newRow);
          }
        } else {
          showToast(newData.message || 'Failed to create transaction', '❌');
        }
      }

    } catch (e) {
      showToast('Upload failed: ' + e.message, '❌');
    }
  });
}

// Resizable divider
function setupResizer() {
  const divider = document.getElementById('divider');
  const left = document.querySelector('.left');
  let isResizing = false;

  divider.addEventListener('mousedown', () => {
    isResizing = true;
    document.body.style.cursor = 'col-resize';
  });

  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const newWidth = (e.clientX / window.innerWidth) * 100;
    if (newWidth > 30 && newWidth < 80) {
      left.style.flex = `0 0 ${newWidth}%`;
    }
  });

  document.addEventListener('mouseup', () => {
    isResizing = false;
    document.body.style.cursor = '';
  });
}

// UI Helpers
function showStatus(state) {
  const el = document.getElementById('status');
  el.className = `status ${state}`;
  if (state === 'saved') {
    setTimeout(() => el.className = 'status', 2000);
  }
}

let toastTimeout = null;
function showToast(message, icon = '✓', duration = 3000) {
  const toast = document.getElementById('toast');
  document.getElementById('toast-icon').textContent = icon;
  document.getElementById('toast-message').textContent = message;
  toast.classList.add('active');
  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('active'), duration);
}

// Loading overlay functions for batch operations
function showLoading(text = 'Processing...', progress = '') {
  document.getElementById('loading-text').textContent = text;
  document.getElementById('loading-progress').textContent = progress;
  document.getElementById('loading-overlay').classList.add('active');
}
function updateLoading(text, progress = '') {
  document.getElementById('loading-text').textContent = text;
  document.getElementById('loading-progress').textContent = progress;
}
function hideLoading() {
  document.getElementById('loading-overlay').classList.remove('active');
}

// Click outside to close modals
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) {
      overlay.classList.remove('active');
    }
  });
});

// =============================================================================
// PAGE NAVIGATION
// =============================================================================

function switchPage(page) {
  // Special handling for Incoming page (separate HTML file)
  if (page === 'incoming') {
    window.location.href = '/incoming.html';
    return;
  }

  // Hide all pages
  document.querySelectorAll('.page-content').forEach(p => p.style.display = 'none');

  // Show selected page
  document.getElementById(`${page}-page`).style.display = 'block';

  // Update nav button styles
  document.querySelectorAll('[id^="nav-"]').forEach(btn => {
    btn.style.background = '';
    btn.style.color = '';
  });

  const activeBtn = document.getElementById(`nav-${page}`);
  activeBtn.style.background = 'var(--brand)';
  activeBtn.style.color = '#000';

  // Load data for Reports page
  if (page === 'reports') {
    loadArchivedReports();
  }

  // Load data for Stats page
  if (page === 'stats') {
    loadStatsPage();
  }
}

// =============================================================================
// STATS PAGE
// =============================================================================

async function loadStatsPage() {
  debugLog('📊 Loading stats page...');

  // Show loading state for key containers
  const containerIds = ['stats-business-breakdown', 'stats-top-merchants', 'stats-top-categories', 'stats-subscriptions', 'stats-receipt-sources'];
  containerIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">Loading...</div>';
  });

  try {
    // Fetch fresh data from database
    let transactions = [];
    debugLog('Fetching transactions from /api/transactions...');

    try {
      // Stats needs ALL transactions including already submitted ones AND those in reports
      const res = await fetch('/api/transactions?show_submitted=true&show_in_report=true&all=true', { credentials: 'same-origin' });
      debugLog('Transactions response status:', res.status);

      if (res.ok) {
        const contentType = res.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
          transactions = await res.json();
          debugLog('Loaded', transactions.length, 'transactions from database');
        } else {
          debugLog('Response is not JSON - likely redirected to login');
        }
      } else {
        debugLog('Transaction fetch failed:', res.status);
      }
    } catch (e) {
      debugLog('Could not fetch transaction data for stats:', e);
    }

    // If no data, show helpful message
    if (transactions.length === 0) {
      containerIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">No transaction data available. Load the Transactions page first.</div>';
      });
      // Still render with empty data to show zeroes in the overview cards
      renderStats(calculateStats([], []));
      return;
    }

    // Also fetch incoming receipts for source info
    let receipts = [];
    try {
      const receiptsRes = await fetch('/api/incoming/receipts?status=all&limit=500', { credentials: 'same-origin' });
      if (receiptsRes.ok) {
        const receiptsData = await receiptsRes.json();
        receipts = receiptsData.receipts || [];
        debugLog('Loaded', receipts.length, 'incoming receipts');
      }
    } catch (e) {
      debugLog('Could not fetch receipts for stats');
    }

    // Calculate stats
    debugLog('Calculating stats with', transactions.length, 'transactions');
    const stats = calculateStats(transactions, receipts);
    debugLog('Stats calculated:', stats);

    // Update UI
    renderStats(stats);
    debugLog('Stats rendered');
  } catch (e) {
    console.error('Error loading stats:', e);
    // Show error state
    containerIds.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = `<div style="color:#ff4e6a;text-align:center;padding:20px">Error loading data: ${e.message}</div>`;
    });
  }
}

function calculateStats(transactions, receipts) {
  const stats = {
    totalSpent: 0,
    totalCount: 0,
    receiptsMatched: 0,
    gmailReceipts: 0,
    totalReceipts: 0,  // Will be calculated from transactions with receipts
    refunds: { total: 0, count: 0 },
    payments: { total: 0, count: 0 },
    interest: 0,
    fees: 0,
    lateCharges: 0,
    byBusiness: {},
    byCategory: {},
    byMerchant: {},
    subscriptions: [],
    receiptSources: {}
  };

  // Track merchant frequencies for subscription detection
  const merchantCounts = {};

  transactions.forEach(t => {
    // Handle both prefixed (chase_) and unprefixed field names
    const amount = parseFloat(t.chase_amount || t.amount) || 0;
    const desc = (t.chase_description || t.description || '').toLowerCase();
    const merchant = t.mi_merchant || t.merchant || t.chase_description || t.description || 'Unknown';
    const category = t.chase_category || t.category || 'Uncategorized';
    const business = t.business_type || t['Business Type'] || 'Unassigned';

    // Count transactions with receipts
    if (t.receipt_file || t.receipt_url || t.receipt_path) {
      stats.receiptsMatched++;
    }

    // Transaction type detection using chase_type field and amount sign
    // In this database:
    //   - POSITIVE amounts = money OUT (expenses, interest, fees)
    //   - NEGATIVE amounts = money IN (payments, refunds, credits)
    //   - chase_type = 'Payment' = credit card payment
    const txnType = (t.chase_type || '').toLowerCase();
    const isInterest = desc.includes('interest') || category === 'Interest';
    const isFee = desc.includes('fee') && !desc.includes('coffee');
    const isLate = desc.includes('late') || desc.includes('penalty');

    // NEGATIVE amounts = money coming IN
    if (amount < 0) {
      if (txnType === 'payment' || desc.includes('payment thank you')) {
        // Credit card payment
        stats.payments.total += Math.abs(amount);
        stats.payments.count++;
      } else {
        // Refund/credit
        stats.refunds.total += Math.abs(amount);
        stats.refunds.count++;
      }
    }
    // POSITIVE amounts = money going OUT
    else if (isInterest) {
      stats.interest += amount;
      stats.totalSpent += amount;
      stats.totalCount++;
    } else if (isFee) {
      stats.fees += amount;
      stats.totalSpent += amount;
      stats.totalCount++;
    } else if (isLate) {
      stats.lateCharges += amount;
      stats.totalSpent += amount;
      stats.totalCount++;
    } else if (amount > 0) {
      // Regular expense
      stats.totalSpent += amount;
      stats.totalCount++;
    }

    // Track business, category, merchant for ALL positive amounts (expenses)
    const isSubmitted = (t.already_submitted || t['Already Submitted'] || '').toLowerCase() === 'yes';

    if (amount > 0) {
      // By business - track total AND submitted separately
      if (!stats.byBusiness[business]) {
        stats.byBusiness[business] = { total: 0, count: 0, submitted: 0, submittedCount: 0 };
      }
      stats.byBusiness[business].total += amount;
      stats.byBusiness[business].count++;
      if (isSubmitted) {
        stats.byBusiness[business].submitted += amount;
        stats.byBusiness[business].submittedCount++;
      }

      // By category
      if (!stats.byCategory[category]) {
        stats.byCategory[category] = { total: 0, count: 0 };
      }
      stats.byCategory[category].total += amount;
      stats.byCategory[category].count++;

      // By merchant
      if (!stats.byMerchant[merchant]) {
        stats.byMerchant[merchant] = { total: 0, count: 0 };
      }
      stats.byMerchant[merchant].total += amount;
      stats.byMerchant[merchant].count++;

      // Track for subscription detection
      if (!merchantCounts[merchant]) {
        merchantCounts[merchant] = { amounts: [], dates: [] };
      }
      merchantCounts[merchant].amounts.push(amount);
      merchantCounts[merchant].dates.push(t.chase_date || t.date);
    }
  });

  // Detect subscriptions (merchants with 3+ recurring charges OR known subscription services)
  const knownSubscriptions = ['apple', 'spotify', 'netflix', 'hulu', 'amazon prime', 'cursor', 'claude', 'midjourney', 'openai', 'chatgpt', 'expensify', 'cloudflare', 'adobe', 'microsoft', 'google one', 'icloud', 'dropbox', 'notion', 'slack', 'zoom', 'canva', 'figma', 'github', 'aws', 'digitalocean', 'heroku', 'vercel', 'anthropic', 'ada ai', 'hive', 'soho house'];

  Object.entries(merchantCounts).forEach(([merchant, data]) => {
    if (data.amounts.length >= 3) {
      const avgAmount = data.amounts.reduce((a, b) => a + b, 0) / data.amounts.length;
      const total = data.amounts.reduce((a, b) => a + b, 0);
      const merchantLower = merchant.toLowerCase();

      // Check if it's a known subscription OR has similar recurring amounts
      const isKnownSub = knownSubscriptions.some(sub => merchantLower.includes(sub));
      const allSimilar = data.amounts.every(a => Math.abs(a - avgAmount) / avgAmount < 0.15);

      // Include if: known subscription service OR recurring similar charges
      if (isKnownSub || (allSimilar && avgAmount > 5)) {
        stats.subscriptions.push({
          name: merchant,
          amount: avgAmount,
          total: total,
          count: data.amounts.length,
          isRecurring: allSimilar
        });
      }
    }
  });

  // Sort subscriptions by total spent
  stats.subscriptions.sort((a, b) => b.total - a.total);

  // Analyze receipt sources
  // Count matched receipts (transactions with receipt_file)
  transactions.forEach(t => {
    const receiptUrl = t.receipt_file || t.receipt_url || t.receipt_path || '';
    if (receiptUrl) {
      stats.totalReceipts++;
      if (!stats.receiptSources['Matched']) {
        stats.receiptSources['Matched'] = 0;
      }
      stats.receiptSources['Matched']++;
    }
  });

  // Count Gmail receipts from incoming_receipts (they have gmail_account field)
  if (receipts.length > 0) {
    receipts.forEach(r => {
      // incoming_receipts with gmail_account are from Gmail
      if (r.gmail_account || r.email_id) {
        stats.gmailReceipts++;
        if (!stats.receiptSources['Gmail (Incoming)']) {
          stats.receiptSources['Gmail (Incoming)'] = 0;
        }
        stats.receiptSources['Gmail (Incoming)']++;
      } else {
        if (!stats.receiptSources['Other Incoming']) {
          stats.receiptSources['Other Incoming'] = 0;
        }
        stats.receiptSources['Other Incoming']++;
      }
    });
  }

  // Count missing receipts (positive amount transactions without receipt)
  const missingCount = transactions.filter(t => {
    const amount = parseFloat(t.chase_amount || t.amount) || 0;
    const hasReceipt = t.receipt_file || t.receipt_url || t.receipt_path;
    return amount > 0 && !hasReceipt;
  }).length;

  if (missingCount > 0) {
    stats.receiptSources['Missing'] = missingCount;
  }

  return stats;
}

function renderStats(stats) {
  debugLog('🎨 renderStats called with:', stats);
  const fmt = (n) => '$' + Math.abs(n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // Helper to safely set text content
  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = text;
    } else {
      console.warn(`Element #${id} not found`);
    }
  };

  // Helper to safely set innerHTML
  const setHTML = (id, html) => {
    const el = document.getElementById(id);
    if (el) {
      el.innerHTML = html;
    } else {
      console.warn(`Element #${id} not found`);
    }
  };

  try {
    // Overview cards
    setText('stats-total-spent', fmt(stats.totalSpent));
    setText('stats-total-count', `${stats.totalCount || 0} transactions`);

    setText('stats-receipts-matched', stats.receiptsMatched || 0);
    const matchRate = stats.totalCount > 0 ? Math.round((stats.receiptsMatched / stats.totalCount) * 100) : 0;
    setText('stats-match-rate', `${matchRate}% coverage`);

    setText('stats-gmail-receipts', stats.gmailReceipts || 0);
    const gmailPct = stats.totalReceipts > 0 ? Math.round((stats.gmailReceipts / stats.totalReceipts) * 100) : 0;
    setText('stats-gmail-pct', `${gmailPct}% of receipts`);

    setText('stats-refunds', fmt(stats.refunds?.total || 0));
    setText('stats-refund-count', `${stats.refunds?.count || 0} transactions`);

    setText('stats-payments', fmt(stats.payments?.total || 0));
    setText('stats-payment-count', `${stats.payments?.count || 0} transactions`);
    debugLog('✓ Overview cards rendered');
  } catch (e) {
    console.error('Error rendering overview cards:', e);
  }

  try {
    // Interest & Fees
    setText('stats-interest-total', fmt(stats.interest));
    setText('stats-fees-total', fmt(stats.fees));
    setText('stats-late-total', fmt(stats.lateCharges));
    setText('stats-total-fees', fmt((stats.interest || 0) + (stats.fees || 0) + (stats.lateCharges || 0)));
    debugLog('✓ Interest & Fees rendered');
  } catch (e) {
    console.error('Error rendering interest/fees:', e);
  }

  try {
    // Business breakdown
    const businessContainer = document.getElementById('stats-business-breakdown');
    const businessEntries = Object.entries(stats.byBusiness || {}).sort((a, b) => b[1].total - a[1].total);

    if (!businessContainer) {
      console.warn('stats-business-breakdown not found');
    } else if (businessEntries.length === 0) {
      businessContainer.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">No business data yet</div>';
    } else {
      const maxBusiness = businessEntries[0][1].total || 1;
      businessContainer.innerHTML = businessEntries.map(([name, data]) => {
        const pct = Math.round((data.total / maxBusiness) * 100);
        const submittedPct = data.submitted > 0 ? Math.round((data.submitted / data.total) * 100) : 0;
        const color = name === 'Business' ? '#00ff88' : name === 'Secondary' ? '#ffd85e' : name === 'Personal' ? '#6eb5ff' : '#888';
        const unreported = data.total - (data.submitted || 0);
        const hasSubmitted = data.submitted > 0;
        return `
          <div style="margin-bottom:16px">
            <div style="display:flex;justify-content:space-between;margin-bottom:6px">
              <span style="font-weight:600">${name}</span>
              <span style="color:${color};font-weight:700">${fmt(data.total)}</span>
            </div>
            <div style="background:var(--panel2);height:8px;border-radius:4px;overflow:hidden;position:relative">
              <div style="background:${color};height:100%;width:${pct}%;border-radius:4px;transition:width .3s"></div>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:4px">
              <span>${data.count} transactions</span>
              ${hasSubmitted ? `<span style="color:#00ff88">Reported: ${fmt(data.submitted)} (${data.submittedCount})</span>` : ''}
            </div>
            ${hasSubmitted && unreported > 0 ? `<div style="font-size:11px;color:#ffd85e;margin-top:2px">Unreported: ${fmt(unreported)} (${data.count - data.submittedCount})</div>` : ''}
          </div>
        `;
      }).join('');
    }
    debugLog('✓ Business breakdown rendered');
  } catch (e) {
    console.error('Error rendering business breakdown:', e);
  }

  try {
    // Top merchants
    const merchantContainer = document.getElementById('stats-top-merchants');
    const merchantEntries = Object.entries(stats.byMerchant || {}).sort((a, b) => b[1].total - a[1].total).slice(0, 10);

    if (!merchantContainer) {
      console.warn('stats-top-merchants not found');
    } else if (merchantEntries.length === 0) {
      merchantContainer.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">No merchant data yet</div>';
    } else {
      const maxMerchant = merchantEntries[0][1].total || 1;
      merchantContainer.innerHTML = merchantEntries.map(([name, data], i) => {
        const pct = Math.round((data.total / maxMerchant) * 100);
        return `
          <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--panel2);border-radius:8px">
            <div style="width:24px;height:24px;background:rgba(0,255,136,.2);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#00ff88">${i + 1}</div>
            <div style="flex:1;min-width:0">
              <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${name}</div>
              <div style="background:var(--edge);height:4px;border-radius:2px;margin-top:4px">
                <div style="background:#00ff88;height:100%;width:${pct}%;border-radius:2px"></div>
              </div>
            </div>
            <div style="text-align:right">
              <div style="font-weight:700;color:#00ff88">${fmt(data.total)}</div>
              <div style="font-size:11px;color:var(--muted)">${data.count}x</div>
            </div>
          </div>
        `;
      }).join('');
    }
    debugLog('✓ Top merchants rendered');
  } catch (e) {
    console.error('Error rendering top merchants:', e);
  }

  try {
    // Top categories
    const categoryContainer = document.getElementById('stats-top-categories');
    const categoryEntries = Object.entries(stats.byCategory || {}).sort((a, b) => b[1].total - a[1].total).slice(0, 8);

    if (!categoryContainer) {
      console.warn('stats-top-categories not found');
    } else if (categoryEntries.length === 0) {
      categoryContainer.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px">No category data yet</div>';
    } else {
      const maxCategory = categoryEntries[0][1].total || 1;
      categoryContainer.innerHTML = categoryEntries.map(([name, data]) => {
        const pct = Math.round((data.total / maxCategory) * 100);
        return `
          <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--panel2);border-radius:8px">
            <div style="flex:1">
              <div style="font-weight:600">${name}</div>
              <div style="background:var(--edge);height:4px;border-radius:2px;margin-top:4px">
                <div style="background:#00ff88;height:100%;width:${pct}%;border-radius:2px"></div>
              </div>
            </div>
            <div style="text-align:right">
              <div style="font-weight:700;color:#00ff88">${fmt(data.total)}</div>
              <div style="font-size:11px;color:var(--muted)">${data.count}x</div>
            </div>
          </div>
        `;
      }).join('');
    }
    debugLog('✓ Top categories rendered');
  } catch (e) {
    console.error('Error rendering top categories:', e);
  }

  try {
    // Subscriptions
    const subsContainer = document.getElementById('stats-subscriptions');
    const subscriptions = stats.subscriptions || [];
    const totalSubSpend = subscriptions.reduce((sum, s) => sum + (s.total || 0), 0);
    setText('stats-monthly-subs', fmt(totalSubSpend));

    if (!subsContainer) {
      console.warn('stats-subscriptions not found');
    } else if (subscriptions.length === 0) {
      subsContainer.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px;grid-column:1/-1">No recurring subscriptions detected</div>';
    } else {
      subsContainer.innerHTML = subscriptions.slice(0, 15).map(sub => `
        <div style="background:var(--panel2);padding:14px;border-radius:10px;border:1px solid var(--edge)">
          <div style="font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:4px">${sub.name || 'Unknown'}</div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <span style="font-size:18px;font-weight:700;color:#00ff88">${fmt(sub.total || 0)}</span>
            <span style="font-size:11px;color:var(--muted);background:var(--panel);padding:2px 8px;border-radius:4px">${sub.count || 0}x</span>
          </div>
          <div style="font-size:11px;color:var(--muted)">~${fmt(sub.amount || 0)}/charge${sub.isRecurring ? ' • recurring' : ''}</div>
        </div>
      `).join('');
    }
    debugLog('✓ Subscriptions rendered');
  } catch (e) {
    console.error('Error rendering subscriptions:', e);
  }

  try {
    // Receipt sources
    const sourcesContainer = document.getElementById('stats-receipt-sources');
    const sourceEntries = Object.entries(stats.receiptSources || {}).sort((a, b) => b[1] - a[1]);

    if (!sourcesContainer) {
      console.warn('stats-receipt-sources not found');
    } else if (sourceEntries.length === 0) {
      sourcesContainer.innerHTML = '<div style="color:var(--muted);text-align:center;padding:20px;grid-column:1/-1">No receipt source data</div>';
    } else {
      const sourceIcons = {
        'Gmail': '📧',
        'Manual Upload': '📤',
        'Scanner': '📷',
        'Google Photos': '🖼️',
        'Unknown': '❓'
      };
      sourcesContainer.innerHTML = sourceEntries.map(([source, count]) => {
        const icon = sourceIcons[source] || '📄';
        const pct = stats.totalReceipts > 0 ? Math.round((count / stats.totalReceipts) * 100) : 0;
        return `
          <div style="background:var(--panel2);padding:16px;border-radius:10px;border:1px solid var(--edge);text-align:center">
            <div style="font-size:32px;margin-bottom:8px">${icon}</div>
            <div style="font-weight:600;margin-bottom:4px">${source}</div>
            <div style="font-size:28px;font-weight:800;color:#00ff88">${count}</div>
            <div style="font-size:11px;color:var(--muted)">${pct}% of receipts</div>
          </div>
        `;
      }).join('');
    }
    debugLog('✓ Receipt sources rendered');
  } catch (e) {
    console.error('Error rendering receipt sources:', e);
  }

  debugLog('✅ renderStats complete');
}

// =============================================================================
// REPORTS PAGE
// =============================================================================

let reportPreviewData = [];
let currentReportId = null;

async function loadReportPreview() {
  const businessType = document.getElementById('report-business-type').value;
  const dateFrom = document.getElementById('report-date-from').value;
  const dateTo = document.getElementById('report-date-to').value;

  if (!businessType) {
    showToast('Please select a business type', '⚠️');
    return;
  }

  showToast('Loading preview...', '🔄');

  try {
    const res = await fetch('/reports/preview', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        business_type: businessType,
        date_from: dateFrom || null,
        date_to: dateTo || null
      })
    });

    const data = await res.json();

    if (data.ok) {
      reportPreviewData = data.expenses;

      // Generate human-readable notes
      const notesRes = await fetch('/reports/generate_notes', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ expenses: reportPreviewData })
      });

      const notesData = await notesRes.json();
      if (notesData.ok) {
        reportPreviewData = notesData.expenses_with_notes;
      }

      // Count receipts
      const receiptCount = reportPreviewData.filter(exp => exp['Receipt File']).length;

      // Update stat cards
      document.getElementById('report-total-amount').textContent =
        `$${data.total_amount.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
      document.getElementById('report-expense-count').textContent = data.count;
      document.getElementById('report-receipt-count').textContent = receiptCount;

      // Populate table
      const tbody = document.getElementById('report-preview-table');
      tbody.innerHTML = '';

      if (reportPreviewData.length === 0) {
        tbody.innerHTML = `
          <tr>
            <td colspan="5" style="padding:40px;text-align:center;color:var(--muted)">
              No expenses found matching the criteria
            </td>
          </tr>
        `;
      } else {
        reportPreviewData.forEach(exp => {
          const tr = document.createElement('tr');
          tr.style.borderBottom = '1px solid var(--edge)';

          const notes = exp['Notes'] || exp['AI Note'] || '';
          const notesDisplay = notes.length > 60 ? notes.substring(0, 60) + '...' : notes;

          const hasReceipt = exp['Receipt File'] ? '📎' : '';

          tr.innerHTML = `
            <td style="padding:10px">${exp['Chase Date'] || ''}</td>
            <td style="padding:10px">${hasReceipt} ${exp['Chase Description'] || ''}</td>
            <td style="padding:10px;text-align:right">$${Math.abs(exp['Chase Amount'] || 0).toFixed(2)}</td>
            <td style="padding:10px">${exp['Category'] || '-'}</td>
            <td style="padding:10px;font-size:12px;color:var(--muted)" title="${notes}">${notesDisplay || '-'}</td>
          `;

          tbody.appendChild(tr);
        });
      }

      // Show preview section
      document.getElementById('report-preview-section').style.display = 'block';

      // Hide report actions until submitted
      document.getElementById('report-actions').style.display = 'none';

      showToast(`Found ${data.count} expenses • ${receiptCount} receipts`, '✅');
    } else {
      showToast('Failed to load preview: ' + (data.error || 'Unknown error'), '❌');
    }
  } catch (e) {
    showToast('Failed to load preview: ' + e.message, '❌');
  }
}

async function submitReport() {
  const reportName = document.getElementById('report-name').value.trim();
  const businessType = document.getElementById('report-business-type').value;

  if (!reportName) {
    showToast('Please enter a report name', '⚠️');
    return;
  }

  if (reportPreviewData.length === 0) {
    showToast('No expenses to submit', '⚠️');
    return;
  }

  showToast('Submitting report...', '📤');

  try {
    const expenseIndexes = reportPreviewData.map(exp => exp._index);

    const res = await fetch('/reports/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        report_name: reportName,
        business_type: businessType,
        expense_indexes: expenseIndexes
      })
    });

    const data = await res.json();

    if (data.ok) {
      currentReportId = data.report_id;
      showToast(`Report ${data.report_id} created successfully!`, '✅');

      // Show report actions
      document.getElementById('report-actions').style.display = 'block';

      // Reload main data (these expenses are now archived)
      await loadCSV();

      // Reload archived reports list
      await loadArchivedReports();
    } else {
      showToast('Failed to submit report: ' + (data.error || 'Unknown error'), '❌');
    }
  } catch (e) {
    showToast('Failed to submit report: ' + e.message, '❌');
  }
}

function viewReportPage() {
  if (!currentReportId) {
    showToast('No report selected', '⚠️');
    return;
  }
  window.open(`/reports/${currentReportId}/page`, '_blank');
}

function downloadReportCSV() {
  if (!currentReportId) {
    showToast('No report selected', '⚠️');
    return;
  }
  window.location.href = `/reports/${currentReportId}/export/business`;
  showToast('Downloading CSV...', '📥');
}

function downloadReportReceipts() {
  if (!currentReportId) {
    showToast('No report selected', '⚠️');
    return;
  }
  window.location.href = `/reports/${currentReportId}/receipts.zip`;
  showToast('Downloading receipts ZIP...', '📥');
}

async function copyReportLink() {
  if (!currentReportId) {
    showToast('No report selected', '⚠️');
    return;
  }
  const url = `${window.location.origin}/reports/${currentReportId}/page`;
  try {
    await navigator.clipboard.writeText(url);
    showToast('Report link copied to clipboard!', '✅');
  } catch (e) {
    showToast('Failed to copy link', '❌');
  }
}

function startNewReport() {
  // Hide report actions
  document.getElementById('report-actions').style.display = 'none';

  // Hide preview section
  document.getElementById('report-preview-section').style.display = 'none';

  // Clear the preview data
  reportPreviewData = [];
  currentReportId = null;

  // Clear the report name input
  document.getElementById('report-name').value = '';

  // Keep the date range and business type selections so they can create another report
  // with the same or different criteria

  showToast('Ready to create a new report', '✨');
}

async function deleteReport(reportId) {
  if (!confirm(`Are you sure you want to delete report ${reportId}?\n\nThis will return all expenses to the available pool.`)) {
    return;
  }

  showToast('Deleting report...', '🗑️');

  try {
    const res = await fetch(`/reports/${reportId}/delete`, {
      method: 'POST'
    });

    const data = await res.json();

    if (data.ok) {
      showToast('Report deleted! Expenses returned to available pool.', '✅');

      // Reload archived reports list
      await loadArchivedReports();

      // Reload main data
      await loadCSV();

      // Close report modal if it's open
      const modal = document.getElementById('report-view-modal');
      if (modal) {
        modal.remove();
      }
    } else {
      showToast('Failed to delete report', '❌');
    }
  } catch (e) {
    console.error('Delete report failed:', e);
    showToast('Failed to delete report: ' + e.message, '❌');
  }
}

async function loadArchivedReports() {
  try {
    const res = await fetch('/reports/list');
    const data = await res.json();

    if (data.ok) {
      const container = document.getElementById('archived-reports-list');

      if (data.reports.length === 0) {
        container.innerHTML = `
          <div style="grid-column:1/-1;padding:60px 20px;text-align:center;color:var(--muted);background:var(--panel2);border-radius:12px;border:1px dashed var(--edge)">
            <div style="font-size:48px;margin-bottom:16px;opacity:.6">📁</div>
            <h4 style="margin:0 0 8px 0;font-size:16px;color:var(--ink)">No Reports Yet</h4>
            <p style="margin:0;font-size:13px">Create your first expense report above to get started</p>
          </div>
        `;
      } else {
        container.innerHTML = data.reports.map(report => {
          // Get business type color/gradient
          const businessColors = {
            'Secondary': 'linear-gradient(135deg, #f59e0b, #d97706)',
            'Business': 'linear-gradient(135deg, #8b5cf6, #7c3aed)',
            'Personal': 'linear-gradient(135deg, #10b981, #059669)'
          };
          const businessGradient = businessColors[report.business_type] || 'linear-gradient(135deg, #6b7280, #4b5563)';

          return `
          <div class="report-card" style="background:linear-gradient(145deg, var(--panel2), rgba(11,17,23,.8));padding:0;border-radius:14px;border:1px solid var(--edge);overflow:hidden;transition:all .2s ease;cursor:pointer"
               onclick="openReport('${report.report_id}')"
               onmouseenter="this.style.transform='translateY(-4px)';this.style.boxShadow='0 12px 32px rgba(0,0,0,.3)';this.style.borderColor='rgba(59,130,246,.4)'"
               onmouseleave="this.style.transform='';this.style.boxShadow='';this.style.borderColor='var(--edge)'">

            <!-- Card Header with gradient -->
            <div style="background:${businessGradient};padding:16px 20px;position:relative;overflow:hidden">
              <div style="position:absolute;top:-20px;right:-20px;width:80px;height:80px;background:rgba(255,255,255,.1);border-radius:50%"></div>
              <div style="position:relative;z-index:1">
                <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;opacity:.9;margin-bottom:6px">${report.business_type}</div>
                <div style="font-size:16px;font-weight:700;line-height:1.3;color:white">${report.report_name}</div>
              </div>
            </div>

            <!-- Card Body -->
            <div style="padding:20px">
              <!-- Stats Row -->
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:16px">
                <div style="text-align:center;padding:12px;background:rgba(59,130,246,.1);border-radius:10px">
                  <div style="font-size:20px;font-weight:800;color:var(--brand)">$${parseFloat(report.total_amount).toFixed(0)}</div>
                  <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px">Total</div>
                </div>
                <div style="text-align:center;padding:12px;background:rgba(139,92,246,.1);border-radius:10px">
                  <div style="font-size:20px;font-weight:800;color:#a78bfa">${report.expense_count}</div>
                  <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px">Expenses</div>
                </div>
                <div style="text-align:center;padding:12px;background:rgba(34,197,94,.1);border-radius:10px">
                  <div style="font-size:20px;font-weight:800;color:#4ade80">${report.receipt_count || '—'}</div>
                  <div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px">Receipts</div>
                </div>
              </div>

              <!-- Date -->
              <div style="font-size:12px;color:var(--muted);margin-bottom:16px;display:flex;align-items:center;gap:6px">
                <span style="opacity:.7">📅</span>
                Created ${new Date(report.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
              </div>

              <!-- Action Buttons -->
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
                <button onclick="event.stopPropagation();window.open('/reports/${report.report_id}/page', '_blank')"
                  style="padding:10px 12px;background:linear-gradient(135deg, #3b82f6, #2563eb);color:white;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px"
                  onmouseenter="this.style.transform='scale(1.02)'" onmouseleave="this.style.transform=''">
                  📊 View
                </button>
                <button onclick="event.stopPropagation();window.location.href='/reports/${report.report_id}/export/business'"
                  style="padding:10px 12px;background:rgba(59,130,246,.15);color:var(--brand);border:1px solid rgba(59,130,246,.3);border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px"
                  onmouseenter="this.style.background='rgba(59,130,246,.25)'" onmouseleave="this.style.background='rgba(59,130,246,.15)'">
                  📄 CSV
                </button>
                <button onclick="event.stopPropagation();window.location.href='/reports/${report.report_id}/receipts.zip'"
                  style="padding:10px 12px;background:rgba(139,92,246,.15);color:#a78bfa;border:1px solid rgba(139,92,246,.3);border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px"
                  onmouseenter="this.style.background='rgba(139,92,246,.25)'" onmouseleave="this.style.background='rgba(139,92,246,.15)'">
                  📦 ZIP
                </button>
                <button onclick="event.stopPropagation();deleteReport('${report.report_id}')"
                  style="padding:10px 12px;background:rgba(239,68,68,.1);color:#f87171;border:1px solid rgba(239,68,68,.2);border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center;gap:6px"
                  onmouseenter="this.style.background='rgba(239,68,68,.2)'" onmouseleave="this.style.background='rgba(239,68,68,.1)'">
                  🗑️ Delete
                </button>
              </div>
            </div>
          </div>
        `}).join('');
      }
    }
  } catch (e) {
    console.error('Failed to load archived reports:', e);
  }
}

async function openReport(reportId) {
  showToast('Loading report...', '📂');

  try {
    const res = await fetch(`/reports/${reportId}`);
    const data = await res.json();

    if (data.ok) {
      // Create modal HTML
      const modalHTML = `
        <div class="modal-overlay active" id="report-view-modal" style="z-index:10000">
          <div class="modal" style="max-width:1000px;max-height:80vh">
            <div class="modal-header">
              <div class="modal-title">📊 Report: ${reportId}</div>
              <button class="modal-close" onclick="closeReportModal()">×</button>
            </div>
            <div class="modal-body" style="max-height:60vh;overflow-y:auto">
              <div style="margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid var(--edge)">
                <h3 style="margin:0 0 8px 0">${data.count} Expenses</h3>
                <p style="margin:0;color:var(--muted)">Total: $${data.total_amount.toFixed(2)}</p>
              </div>

              <table style="width:100%;border-collapse:collapse">
                <thead style="background:var(--panel2)">
                  <tr>
                    <th style="padding:10px;text-align:left;border-bottom:1px solid var(--edge);font-size:12px">Date</th>
                    <th style="padding:10px;text-align:left;border-bottom:1px solid var(--edge);font-size:12px">Description</th>
                    <th style="padding:10px;text-align:right;border-bottom:1px solid var(--edge);font-size:12px">Amount</th>
                    <th style="padding:10px;text-align:left;border-bottom:1px solid var(--edge);font-size:12px">Category</th>
                    <th style="padding:10px;text-align:left;border-bottom:1px solid var(--edge);font-size:12px">Notes</th>
                  </tr>
                </thead>
                <tbody>
                  ${data.expenses.map(exp => {
                    const notes = exp['Notes'] || exp['AI Note'] || '';
                    return `
                    <tr style="border-bottom:1px solid var(--edge)">
                      <td style="padding:10px">${exp['Chase Date'] || ''}</td>
                      <td style="padding:10px">${exp['Chase Description'] || ''}</td>
                      <td style="padding:10px;text-align:right">$${Math.abs(exp['Chase Amount'] || 0).toFixed(2)}</td>
                      <td style="padding:10px">${exp['Category'] || '-'}</td>
                      <td style="padding:10px;font-size:12px;color:var(--muted)">${notes || '-'}</td>
                    </tr>
                  `}).join('')}
                </tbody>
              </table>
            </div>
            <div class="modal-footer">
              <button class="btn-ghost" onclick="closeReportModal()">Close</button>
            </div>
          </div>
        </div>
      `;

      // Add to body
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = modalHTML;
      document.body.appendChild(tempDiv.firstElementChild);

      showToast('Report loaded', '✅');
    } else {
      showToast('Failed to load report: ' + (data.error || 'Unknown error'), '❌');
    }
  } catch (e) {
    showToast('Failed to load report: ' + e.message, '❌');
  }
}

function closeReportModal() {
  const modal = document.getElementById('report-view-modal');
  if (modal) {
    modal.remove();
  }
}

// ============================================
// MOBILE RECEIPT VIEWER
// ============================================

let mobileReceiptModal = null;
let mobileReceiptPanzoom = null;

function initMobileReceiptModal() {
  // Create modal if it doesn't exist
  if (!document.getElementById('mobile-receipt-modal')) {
    const modal = document.createElement('div');
    modal.id = 'mobile-receipt-modal';
    modal.className = 'mobile-receipt-modal';
    modal.innerHTML = `
      <div class="mobile-receipt-header">
        <div class="mobile-receipt-title" id="mobile-receipt-title">Receipt</div>
        <button class="mobile-receipt-close" onclick="closeMobileReceiptViewer()">×</button>
      </div>
      <div class="mobile-receipt-image" id="mobile-receipt-image">
        <button class="mobile-receipt-nav prev" onclick="navigateMobileReceipt(-1)" id="mobile-prev">‹</button>
        <button class="mobile-receipt-nav next" onclick="navigateMobileReceipt(1)" id="mobile-next">›</button>
        <img id="mobile-receipt-img" src="" alt="Receipt" style="display:none">
        <div id="mobile-no-receipt" style="text-align:center;color:var(--muted);padding:40px">
          <div style="font-size:48px;opacity:0.3;margin-bottom:16px">📄</div>
          <div>No receipt attached</div>
        </div>
      </div>
      <div class="mobile-receipt-info" id="mobile-receipt-info">
        <div class="mobile-receipt-row">
          <span class="mobile-receipt-label">Merchant</span>
          <span class="mobile-receipt-value" id="mobile-merchant">—</span>
        </div>
        <div class="mobile-receipt-row">
          <span class="mobile-receipt-label">Amount</span>
          <span class="mobile-receipt-value" id="mobile-amount">—</span>
        </div>
        <div class="mobile-receipt-row">
          <span class="mobile-receipt-label">Date</span>
          <span class="mobile-receipt-value" id="mobile-date">—</span>
        </div>
        <div class="mobile-receipt-row">
          <span class="mobile-receipt-label">Business</span>
          <span class="mobile-receipt-value" id="mobile-business">—</span>
        </div>
        <div class="mobile-receipt-row">
          <span class="mobile-receipt-label">Status</span>
          <span class="mobile-receipt-value" id="mobile-status">—</span>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn-success" onclick="mobileMarkStatus('good')" style="flex:1;min-width:80px">✓ Good</button>
          <button class="btn-danger" onclick="mobileMarkStatus('bad')" style="flex:1;min-width:80px">✗ Bad</button>
          <button class="btn-ghost" onclick="openQuickViewerFromMobile()" style="flex:1;min-width:80px">✏️ Edit</button>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
    mobileReceiptModal = modal;
  }
}

function showMobileReceiptViewer(idx) {
  initMobileReceiptModal();
  const modal = document.getElementById('mobile-receipt-modal');
  const row = DATA[idx];

  if (!row) return;

  // Store current index
  modal.dataset.currentIdx = idx;

  // Update title
  document.getElementById('mobile-receipt-title').textContent =
    row['Vendor/Merchant'] || 'Receipt Details';

  // Update info
  document.getElementById('mobile-merchant').textContent =
    row['Vendor/Merchant'] || '—';
  document.getElementById('mobile-amount').textContent =
    row['Amount'] || '—';
  document.getElementById('mobile-date').textContent =
    row['Transaction Date'] || '—';
  document.getElementById('mobile-business').textContent =
    row['Business Type'] || '—';
  document.getElementById('mobile-status').textContent =
    row['Review Status'] || 'Pending';

  // Update receipt image
  const img = document.getElementById('mobile-receipt-img');
  const noReceipt = document.getElementById('mobile-no-receipt');
  const receiptUrl = row['receipt_url'] || row['Receipt URL'] || '';

  if (receiptUrl) {
    img.src = receiptUrl;
    img.style.display = 'block';
    noReceipt.style.display = 'none';

    // Initialize panzoom for pinch-to-zoom
    if (mobileReceiptPanzoom) {
      mobileReceiptPanzoom.destroy();
    }
    img.onload = () => {
      if (typeof Panzoom !== 'undefined') {
        mobileReceiptPanzoom = Panzoom(img, {
          maxScale: 5,
          minScale: 0.5,
          contain: 'inside'
        });
        img.parentElement.addEventListener('wheel', (e) => {
          e.preventDefault();
          mobileReceiptPanzoom.zoomWithWheel(e);
        });
      }
    };
  } else {
    img.style.display = 'none';
    noReceipt.style.display = 'block';
  }

  // Update navigation buttons
  updateMobileNavButtons(idx);

  // Show modal
  modal.classList.add('active');
  document.body.style.overflow = 'hidden';
}

function closeMobileReceiptViewer() {
  const modal = document.getElementById('mobile-receipt-modal');
  if (modal) {
    modal.classList.remove('active');
    document.body.style.overflow = '';
  }
  if (mobileReceiptPanzoom) {
    mobileReceiptPanzoom.destroy();
    mobileReceiptPanzoom = null;
  }
}

function navigateMobileReceipt(direction) {
  const modal = document.getElementById('mobile-receipt-modal');
  const currentIdx = parseInt(modal.dataset.currentIdx || 0);
  const newIdx = currentIdx + direction;

  if (newIdx >= 0 && newIdx < FILTERED.length) {
    const dataIdx = FILTERED[newIdx];
    showMobileReceiptViewer(dataIdx);
  }
}

function updateMobileNavButtons(dataIdx) {
  const currentFilteredIdx = FILTERED.indexOf(dataIdx);
  const prevBtn = document.getElementById('mobile-prev');
  const nextBtn = document.getElementById('mobile-next');

  if (prevBtn) prevBtn.disabled = currentFilteredIdx <= 0;
  if (nextBtn) nextBtn.disabled = currentFilteredIdx >= FILTERED.length - 1;
}

function mobileMarkStatus(status) {
  const modal = document.getElementById('mobile-receipt-modal');
  const dataIdx = parseInt(modal.dataset.currentIdx || 0);

  if (DATA[dataIdx]) {
    DATA[dataIdx]['Review Status'] = status;
    saveRow(dataIdx, 'Review Status', status);

    // Update display
    document.getElementById('mobile-status').textContent = status;

    // Show toast
    showToast(`Marked as ${status}`, status === 'good' ? '✅' : '❌');

    // Auto-advance to next
    setTimeout(() => navigateMobileReceipt(1), 500);
  }
}

function openQuickViewerFromMobile() {
  const modal = document.getElementById('mobile-receipt-modal');
  const dataIdx = parseInt(modal.dataset.currentIdx || 0);
  closeMobileReceiptViewer();
  showQuickViewer(dataIdx);
}

// Override row click behavior on mobile
function handleRowClick(idx, e) {
  // Check if we're on mobile/tablet
  if (window.innerWidth <= 1024) {
    e.preventDefault();
    e.stopPropagation();
    showMobileReceiptViewer(idx);
    return false;
  }
  // Desktop behavior - select row and show in side panel
  selectRow(idx);
}

// Add touch event handling for swipe navigation in mobile viewer
document.addEventListener('DOMContentLoaded', () => {
  initMobileReceiptModal();

  // Add swipe support to mobile receipt viewer
  let touchStartX = 0;
  let touchEndX = 0;

  document.addEventListener('touchstart', (e) => {
    const modal = document.getElementById('mobile-receipt-modal');
    if (modal && modal.classList.contains('active')) {
      touchStartX = e.changedTouches[0].screenX;
    }
  }, { passive: true });

  document.addEventListener('touchend', (e) => {
    const modal = document.getElementById('mobile-receipt-modal');
    if (modal && modal.classList.contains('active')) {
      touchEndX = e.changedTouches[0].screenX;
      const diff = touchStartX - touchEndX;

      // Minimum swipe distance of 50px
      if (Math.abs(diff) > 50) {
        if (diff > 0) {
          navigateMobileReceipt(1); // Swipe left - next
        } else {
          navigateMobileReceipt(-1); // Swipe right - previous
        }
      }
    }
  }, { passive: true });

  // Close on escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeMobileReceiptViewer();
    }
  });
});

// Helper to check if we're on mobile
function isMobileDevice() {
  return window.innerWidth <= 1024 ||
    ('ontouchstart' in window) ||
    (navigator.maxTouchPoints > 0);
}

// ============================================
// BATCH OPERATIONS
// ============================================
let batchMode = false;
let selectedTransactions = new Set();

function toggleBatchMode() {
  batchMode = !batchMode;
  const btn = document.getElementById('batch-select-btn');
  const actions = document.getElementById('batch-actions');

  if (batchMode) {
    btn.style.background = 'var(--brand)';
    btn.style.color = '#000';
    actions.style.display = 'flex';
    showToast('Batch mode ON - Click rows to select', 'info');
  } else {
    btn.style.background = '';
    btn.style.color = '';
    actions.style.display = 'none';
    selectedTransactions.clear();
    renderTable();
  }
}

function toggleTransactionSelection(index, event) {
  if (!batchMode) return;
  event.stopPropagation();

  if (selectedTransactions.has(index)) {
    selectedTransactions.delete(index);
  } else {
    selectedTransactions.add(index);
  }

  updateBatchCount();
  renderTable();
}

function selectAllVisible() {
  filteredData.forEach(row => selectedTransactions.add(row._index));
  updateBatchCount();
  renderTable();
  showToast(`Selected ${selectedTransactions.size} transactions`, 'info');
}

function clearSelection() {
  selectedTransactions.clear();
  updateBatchCount();
  renderTable();
}

function updateBatchCount() {
  const countEl = document.getElementById('batch-count');
  if (countEl) {
    countEl.textContent = `${selectedTransactions.size} selected`;
  }
}

async function batchSetBusiness(businessType) {
  if (!businessType || selectedTransactions.size === 0) return;

  const count = selectedTransactions.size;
  if (!confirm(`Set ${count} transactions to "${businessType}"?`)) {
    document.getElementById('batch-business-select').value = '';
    return;
  }

  showToast(`Updating ${count} transactions...`, 'info');

  let success = 0;
  for (const index of selectedTransactions) {
    try {
      const res = await fetch('/update_row', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ _index: index, patch: { 'Business Type': businessType }})
      });
      if (res.ok) {
        success++;
        const row = csvData.find(r => r._index === index);
        if (row) row['Business Type'] = businessType;
      }
    } catch (e) { console.error(e); }
  }

  showToast(`Updated ${success}/${count} transactions`, 'success');
  document.getElementById('batch-business-select').value = '';
  selectedTransactions.clear();
  updateBatchCount();
  renderTable();
  updateDashboard();
}

async function batchSetStatus(status) {
  if (!status || selectedTransactions.size === 0) return;

  const count = selectedTransactions.size;
  if (!confirm(`Set ${count} transactions to "${status}"?`)) {
    document.getElementById('batch-status-select').value = '';
    return;
  }

  showToast(`Updating ${count} transactions...`, 'info');

  let success = 0;
  for (const index of selectedTransactions) {
    try {
      const res = await fetch('/update_row', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ _index: index, patch: { 'Review Status': status }})
      });
      if (res.ok) {
        success++;
        const row = csvData.find(r => r._index === index);
        if (row) row['Review Status'] = status;
      }
    } catch (e) { console.error(e); }
  }

  showToast(`Updated ${success}/${count} transactions`, 'success');
  document.getElementById('batch-status-select').value = '';
  selectedTransactions.clear();
  updateBatchCount();
  renderTable();
}

// ============================================
// ADVANCED SEARCH
// ============================================
let advancedSearchVisible = false;

function toggleAdvancedSearch() {
  advancedSearchVisible = !advancedSearchVisible;
  const panel = document.getElementById('advanced-search-panel');
  const btn = document.getElementById('advanced-search-btn');

  if (advancedSearchVisible) {
    panel.style.display = 'flex';
    btn.style.background = 'var(--brand)';
    btn.style.color = '#000';
  } else {
    panel.style.display = 'none';
    btn.style.background = '';
    btn.style.color = '';
  }
}

function applyAdvancedSearch() {
  const amountMin = parseFloat(document.getElementById('search-amount-min').value) || null;
  const amountMax = parseFloat(document.getElementById('search-amount-max').value) || null;
  const dateFrom = document.getElementById('search-date-from').value || null;
  const dateTo = document.getElementById('search-date-to').value || null;
  const merchant = document.getElementById('search-merchant').value.toLowerCase().trim();

  filteredData = csvData.filter(row => {
    const amount = Math.abs(parseFloat(row['Chase Amount']) || 0);
    const date = row['Chase Date'] || '';
    const merchantName = (row['MI Merchant'] || row['Chase Description'] || '').toLowerCase();

    if (amountMin !== null && amount < amountMin) return false;
    if (amountMax !== null && amount > amountMax) return false;
    if (dateFrom && date < dateFrom) return false;
    if (dateTo && date > dateTo) return false;
    if (merchant && !merchantName.includes(merchant)) return false;

    return true;
  });

  renderTable();
  showToast(`Found ${filteredData.length} matching transactions`, 'success');
}

function clearAdvancedSearch() {
  document.getElementById('search-amount-min').value = '';
  document.getElementById('search-amount-max').value = '';
  document.getElementById('search-date-from').value = '';
  document.getElementById('search-date-to').value = '';
  document.getElementById('search-merchant').value = '';
  document.getElementById('search').value = '';

  filteredData = [...csvData];
  renderTable();
  showToast('Filters cleared', 'info');
}

// ============================================
// AUTO-CATEGORIZATION LEARNING
// ============================================
const categoryRules = JSON.parse(localStorage.getItem('categoryRules') || '{}');

function learnCategorization(merchant, businessType, category) {
  const key = merchant.toLowerCase().replace(/[^a-z0-9]/g, '').substring(0, 20);
  if (!key) return;

  categoryRules[key] = { businessType, category, lastUsed: Date.now() };
  localStorage.setItem('categoryRules', JSON.stringify(categoryRules));
}

function suggestCategorization(merchant) {
  const key = merchant.toLowerCase().replace(/[^a-z0-9]/g, '').substring(0, 20);
  return categoryRules[key] || null;
}

// Auto-apply learned rules when loading
function applyLearnedRules() {
  let applied = 0;

  csvData.forEach(row => {
    if (row['Business Type']) return; // Already categorized

    const merchant = row['MI Merchant'] || row['Chase Description'] || '';
    const suggestion = suggestCategorization(merchant);

    if (suggestion) {
      row['Business Type'] = suggestion.businessType;
      if (suggestion.category) row['MI Category'] = suggestion.category;
      applied++;
    }
  });

  if (applied > 0) {
    showToast(`Auto-categorized ${applied} transactions from learned rules`, 'success');
    renderTable();
    updateDashboard();
  }
}

// ============================================
// CALENDAR VIEW
// ============================================
function openCalendarView() {
  // Create calendar modal
  let modal = document.getElementById('calendar-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'calendar-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
      <div class="modal" style="max-width:900px;max-height:90vh">
        <div class="modal-header">
          <div class="modal-title">📅 Calendar View</div>
          <button class="modal-close" onclick="closeCalendarView()">×</button>
        </div>
        <div class="modal-body" style="padding:0">
          <div id="calendar-container" style="padding:20px"></div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);
  }

  modal.classList.add('active');
  renderCalendar();
}

function closeCalendarView() {
  const modal = document.getElementById('calendar-modal');
  if (modal) modal.classList.remove('active');
}

function renderCalendar() {
  const container = document.getElementById('calendar-container');
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();

  // Group transactions by date
  const transactionsByDate = {};
  csvData.forEach(row => {
    const date = row['Chase Date'];
    if (date) {
      if (!transactionsByDate[date]) transactionsByDate[date] = [];
      transactionsByDate[date].push(row);
    }
  });

  // Get days in month
  const firstDay = new Date(year, month, 1);
  const lastDay = new Date(year, month + 1, 0);
  const daysInMonth = lastDay.getDate();
  const startDay = firstDay.getDay();

  let html = `
    <div style="text-align:center;margin-bottom:20px">
      <h3 style="margin:0">${today.toLocaleString('default', { month: 'long', year: 'numeric' })}</h3>
    </div>
    <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;text-align:center">
      <div style="font-weight:600;color:var(--muted);padding:8px">Sun</div>
      <div style="font-weight:600;color:var(--muted);padding:8px">Mon</div>
      <div style="font-weight:600;color:var(--muted);padding:8px">Tue</div>
      <div style="font-weight:600;color:var(--muted);padding:8px">Wed</div>
      <div style="font-weight:600;color:var(--muted);padding:8px">Thu</div>
      <div style="font-weight:600;color:var(--muted);padding:8px">Fri</div>
      <div style="font-weight:600;color:var(--muted);padding:8px">Sat</div>
  `;

  // Empty cells before first day
  for (let i = 0; i < startDay; i++) {
    html += '<div></div>';
  }

  // Days
  for (let day = 1; day <= daysInMonth; day++) {
    const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
    const dayTxns = transactionsByDate[dateStr] || [];
    const total = dayTxns.reduce((sum, t) => sum + Math.abs(parseFloat(t['Chase Amount']) || 0), 0);
    const isToday = day === today.getDate();

    html += `
      <div style="padding:8px;background:var(--panel2);border-radius:8px;min-height:60px;cursor:${dayTxns.length ? 'pointer' : 'default'};${isToday ? 'border:2px solid var(--brand);' : ''}"
           onclick="${dayTxns.length ? `showDayTransactions('${dateStr}')` : ''}">
        <div style="font-weight:600;${isToday ? 'color:var(--brand)' : ''}">${day}</div>
        ${dayTxns.length ? `
          <div style="font-size:11px;color:var(--muted)">${dayTxns.length} txn</div>
          <div style="font-size:12px;font-weight:600;color:var(--bad)">$${total.toFixed(0)}</div>
        ` : ''}
      </div>
    `;
  }

  html += '</div>';
  container.innerHTML = html;
}

function showDayTransactions(dateStr) {
  // Filter to show only that day's transactions
  document.getElementById('search').value = dateStr;
  applyFilters();
  closeCalendarView();
  showToast(`Showing transactions for ${dateStr}`, 'info');
}

// ============================================
// SMART NOTIFICATIONS
// ============================================
let notificationPermission = Notification.permission;

async function requestNotificationPermission() {
  if ('Notification' in window) {
    notificationPermission = await Notification.requestPermission();
    return notificationPermission === 'granted';
  }
  return false;
}

function showNotification(title, body, icon = '/favicon.ico') {
  if (notificationPermission !== 'granted') return;

  new Notification(title, { body, icon, badge: icon });
}

// Check for weekly summaries (call on page load)
async function checkWeeklySummary() {
  const lastSummary = localStorage.getItem('lastWeeklySummary');
  const now = Date.now();
  const oneWeek = 7 * 24 * 60 * 60 * 1000;

  if (lastSummary && (now - parseInt(lastSummary)) < oneWeek) return;

  // Generate summary
  const unmatched = csvData.filter(r => !r['Receipt File']).length;
  const thisWeek = csvData.filter(r => {
    const date = new Date(r['Chase Date']);
    return (now - date.getTime()) < oneWeek;
  });
  const weeklyTotal = thisWeek.reduce((sum, r) => sum + Math.abs(parseFloat(r['Chase Amount']) || 0), 0);

  if (unmatched > 0 || weeklyTotal > 0) {
    showNotification(
      'Weekly Expense Summary',
      `${unmatched} receipts missing | $${weeklyTotal.toFixed(2)} spent this week`
    );
    localStorage.setItem('lastWeeklySummary', now.toString());
  }
}

// Check for subscription reminders
function checkSubscriptionReminders() {
  const subscriptions = csvData.filter(r => r.mi_is_subscription);
  const now = new Date();

  subscriptions.forEach(sub => {
    const lastCharge = new Date(sub['Chase Date']);
    const daysSince = Math.floor((now - lastCharge) / (1000 * 60 * 60 * 24));

    // Remind if subscription is due soon (around 25-31 days)
    if (daysSince >= 25 && daysSince <= 31) {
      showNotification(
        'Subscription Reminder',
        `${sub.mi_subscription_name || sub['MI Merchant']} may renew soon ($${Math.abs(parseFloat(sub['Chase Amount'])).toFixed(2)})`
      );
    }
  });
}

// Initialize notifications on load
document.addEventListener('DOMContentLoaded', () => {
  requestNotificationPermission().then(granted => {
    if (granted) {
      checkWeeklySummary();
      checkSubscriptionReminders();
    }
  });
});

// Add calendar button to stats page
setTimeout(() => {
  const statsHeader = document.querySelector('#stats-page h2');
  if (statsHeader) {
    const calBtn = document.createElement('button');
    calBtn.className = 'btn-ghost';
    calBtn.style.marginLeft = '16px';
    calBtn.innerHTML = '📅 Calendar View';
    calBtn.onclick = openCalendarView;
    statsHeader.parentNode.appendChild(calBtn);
  }
}, 100);

// ============================================
// KEYBOARD SHORTCUTS INTEGRATION
// ============================================
// ReviewInterface adapter - bridges KeyboardHandler to existing functions
const ReviewInterface = {
  // Navigation
  navigate: (delta) => navigateRow(delta),
  navigateToIndex: (idx) => {
    if (idx === -1) idx = filteredData.length - 1;
    if (idx >= 0 && idx < filteredData.length) {
      const row = filteredData[idx];
      selectRow(row);
      document.querySelector(`tr[data-index="${row._index}"]`)?.scrollIntoView({ block: 'center' });
    }
  },
  togglePreview: (open) => {
    if (open && selectedRow) loadReceipt();
  },
  closeAll: () => {
    closeQuickViewer();
    const modal = document.querySelector('.modal-overlay.active');
    if (modal) modal.classList.remove('active');
  },

  // Quick actions - map to updateField
  setReviewStatus: (status) => updateField('Review Status', status),
  setValidationStatus: (status) => updateField('MI Validation', status),
  detachReceipt: () => detachReceipt(),

  // Business type
  setBusinessType: (type) => updateField('Business Type', type),
  setPersonal: () => updateField('Business Type', 'Personal'),

  // AI actions
  aiMatch: () => aiMatch(),
  generateAINote: () => aiNote(),
  aiCategorize: async () => {
    if (!selectedRow) return showToast('Select a transaction first', 'warning');
    try {
      const resp = await fetch('/api/ai/categorize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ _index: selectedRow._index })
      });
      const data = await resp.json();
      if (data.ok) {
        showToast(`Categorized: ${data.category}`, 'success');
        await loadCSV();
      }
    } catch (e) {
      showToast('AI categorization failed', 'error');
    }
  },

  // Bulk selection (simplified for now)
  extendSelection: (delta) => {
    // Future: implement shift-selection
    navigateRow(delta);
  },
  selectAll: () => showToast('Select all: Use Ctrl+Click', 'info'),
  selectSameMerchant: () => showToast('Select same merchant: Coming soon', 'info'),
  openBulkActions: () => {
    if (typeof BulkActions !== 'undefined') {
      window.bulkActions?.show();
    }
  },

  // Search & Filter
  focusSearch: () => {
    const search = document.getElementById('search');
    if (search) search.focus();
  },
  toggleFilterPanel: () => {
    const filters = document.querySelector('.filter-controls');
    if (filters) filters.classList.toggle('expanded');
  },
  quickFilter: (type, value) => {
    if (type === 'business') {
      const select = document.getElementById('filterBusiness');
      if (select) {
        select.value = value;
        applyFilters();
      }
    } else if (type === 'receipt') {
      const select = document.getElementById('filterReceipt');
      if (select) {
        select.value = value;
        applyFilters();
      }
    } else if (type === 'status') {
      const select = document.getElementById('filterStatus');
      if (select) {
        select.value = value;
        applyFilters();
      }
    }
  },

  // Image controls
  rotateImage: () => rotateImage(),
  zoomIn: () => zoomIn(),
  zoomOut: () => zoomOut(),
  resetZoom: () => resetZoom(),

  // System
  openQuickViewer: () => openQuickViewer(),
  undo: () => undo(),
  save: () => saveCSV(),
  exportSelected: () => showToast('Export: Use Reports page', 'info')
};

// Initialize keyboard handler after DOM ready
document.addEventListener('DOMContentLoaded', () => {
  if (typeof KeyboardHandler !== 'undefined') {
    window.keyboardHandler = new KeyboardHandler(ReviewInterface);
    debugLog('Keyboard shortcuts enabled. Press ? for help.');
  }
});
